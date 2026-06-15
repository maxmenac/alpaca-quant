"""Phase 4D dataset inspection report tests. Synthetic only: no .env, network, API, artifacts."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.research.data_contract import FeatureSpec
from alpaca_quant.research.dataset_report import (
    BOUNDARY_NOTE,
    DatasetReportConfig,
    DatasetReportError,
    attach_feature_set_id,
    build_dataset_inspection_report,
    render_dataset_inspection_markdown,
)
from alpaca_quant.research.feature_registry import (
    VERDICT_OK,
    VERDICT_REJECTED,
    VERDICT_SUSPECT,
    FeatureDefinition,
    build_registry,
    compute_feature_set_id,
)
from alpaca_quant.research.ml_dataset import DatasetConfig, assemble_ml_dataset
from alpaca_quant.research.splits import make_temporal_split
from alpaca_quant.research.targets import build_forward_return_labels

LABEL = "label_forward_return_1d"
FEATURE = "bar_volume_raw"


def _day(n: int) -> datetime:
    return datetime(2024, 1, n, tzinfo=UTC)


def _neutral(name: str = FEATURE, **overrides) -> FeatureDefinition:
    base = {
        "name": name,
        "family": "mechanical",
        "description": "neutral pass-through feature",
        "dtype": "float64",
        "source": "caller_provided",
        "pit_safe": True,
    }
    base.update(overrides)
    return FeatureDefinition(**base)


def _frozen_clock():
    return datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


def _dataset(
    *,
    universe: pl.DataFrame | None = None,
    identity: pl.DataFrame | None = None,
    feature_values: list[float | None] | None = None,
):
    closes = [100.0, 110.0, 121.0, 130.0, 140.0, 150.0, 160.0, 170.0]
    bars = pl.DataFrame(
        {
            "symbol": ["AAPL"] * len(closes),
            "timestamp": [_day(2 + i) for i in range(len(closes))],
            "close": closes,
        }
    )
    labels = build_forward_return_labels(bars)
    values = feature_values or [float(i + 1) * 1000.0 for i in range(len(closes))]
    features = bars.select(["symbol", "timestamp"]).with_columns(pl.Series(FEATURE, values))
    config = DatasetConfig(synthetic_no_universe=universe is None)
    return assemble_ml_dataset(
        labels=labels,
        features=features,
        feature_specs=[FeatureSpec(FEATURE)],
        label_columns=[LABEL],
        universe=universe,
        identity=identity,
        config=config,
        clock=_frozen_clock,
    )


def _report(result, registry, requested=(FEATURE,), **kwargs):
    return build_dataset_inspection_report(
        result.frame,
        manifest=result.manifest,
        registry=registry,
        requested_features=list(requested),
        clock=_frozen_clock,
        **kwargs,
    )


# --- coverage & content ----------------------------------------------------


def test_report_core_fields_and_coverage() -> None:
    res = _dataset()
    registry = build_registry([_neutral()])
    report = _report(res, registry)
    assert report["schema_version"] == 1
    assert report["generated_at_utc"] == "2026-06-16T12:00:00+00:00"
    assert report["row_count"] == 8
    assert report["eligible_row_count"] + report["ineligible_row_count"] == 8
    assert report["feature_coverage"][0]["name"] == FEATURE
    assert report["feature_coverage"][0]["in_dataset"] is True
    assert report["feature_safety"][0]["verdict"] == VERDICT_OK


def test_null_matrix_and_no_fill() -> None:
    values = [1000.0, None, 3000.0, 4000.0, 5000.0, 6000.0, 7000.0, 8000.0]
    res = _dataset(feature_values=values)
    registry = build_registry([_neutral()])
    report = _report(res, registry)
    # null preserved, never filled
    assert res.frame.filter(pl.col("timestamp") == _day(3))[FEATURE].item() is None
    assert report["null_matrix"][FEATURE]["null_count"] >= 1


def test_pit_and_identity_coverage_present() -> None:
    res = _dataset()
    report = _report(res, build_registry([_neutral()]))
    assert "no_universe_data" in report["universe_coverage"]
    assert report["symbol_identity_coverage"]["identity_used"] is False


# --- verdict precedence ----------------------------------------------------


def test_verdict_ok_when_fully_specified() -> None:
    # A genuinely fully-specified dataset declares universe, identity, AND availability
    # semantics (a reference table carrying available_at).
    closes = [100.0, 110.0, 121.0, 130.0, 140.0, 150.0]
    bars = pl.DataFrame(
        {
            "symbol": ["AAPL"] * len(closes),
            "timestamp": [_day(2 + i) for i in range(len(closes))],
            "close": closes,
        }
    )
    labels = build_forward_return_labels(bars)
    features = bars.select(["symbol", "timestamp"]).with_columns(
        pl.Series(FEATURE, [float(i + 1) * 1000.0 for i in range(len(closes))])
    )
    universe = pl.DataFrame(
        {"symbol": ["AAPL"], "valid_from": [_day(1)], "valid_to": [None]},
        schema_overrides={"valid_to": pl.Datetime(time_zone="UTC")},
    )
    identity = pl.DataFrame(
        {
            "permanent_id": ["pid-aapl"],
            "symbol": ["AAPL"],
            "valid_from": [_day(1)],
            "valid_to": [None],
        },
        schema_overrides={"valid_to": pl.Datetime(time_zone="UTC")},
    )
    reference = pl.DataFrame({"symbol": ["AAPL"], "available_at": [_day(2)], "eps": [1.5]})
    res = assemble_ml_dataset(
        labels=labels,
        features=features,
        feature_specs=[FeatureSpec(FEATURE)],
        label_columns=[LABEL],
        universe=universe,
        identity=identity,
        reference=reference,
        reference_value_columns=["eps"],
        config=DatasetConfig(),
        clock=_frozen_clock,
    )
    report = _report(res, build_registry([_neutral()]))
    assert report["verdict"] == VERDICT_OK
    assert report["symbol_identity_coverage"]["identity_used"] is True


def test_verdict_suspect_for_missing_universe() -> None:
    res = _dataset()  # synthetic no-universe
    report = _report(res, build_registry([_neutral()]))
    assert report["verdict"] == VERDICT_SUSPECT
    codes = {w["code"] for w in report["warnings"]}
    assert "missing_pit_universe" in codes


def test_verdict_rejected_for_alpha_like_requested_feature() -> None:
    res = _dataset()
    # registry declares the requested feature as future-looking -> REJECTED dominates SUSPECT
    registry = build_registry([_neutral(uses_future_data=True)])
    report = _report(res, registry)
    assert report["verdict"] == VERDICT_REJECTED


def test_verdict_rejected_for_invalid_split() -> None:
    res = _dataset()
    registry = build_registry([_neutral()])
    good = make_temporal_split(res.frame, max_horizon=1)
    tampered = good.__class__(
        id_column=good.id_column,
        max_horizon=good.max_horizon,
        embargo=good.embargo,
        n_timestamps=good.n_timestamps,
        train_index=(*good.train_index, min(good.validation_index) - 1),
        validation_index=good.validation_index,
        test_index=good.test_index,
        purged_count=good.purged_count,
        embargoed_count=good.embargoed_count,
        boundary_timestamps=good.boundary_timestamps,
    )
    report = _report(res, registry, splits=[tampered])
    assert report["verdict"] == VERDICT_REJECTED
    assert any(w["code"] == "invalid_split_definition" for w in report["warnings"])


def test_undeclared_and_missing_features_warn() -> None:
    res = _dataset()
    registry = build_registry([_neutral("other_feature")])
    # request a feature not in dataset; the real dataset column is undeclared in the set
    report = _report(res, registry, requested=("other_feature",))
    codes = {w["code"] for w in report["warnings"]}
    assert "feature_missing_from_dataset" in codes
    assert "undeclared_dataset_column" in codes
    assert "missing_feature_metadata" not in codes  # other_feature IS in registry


def test_null_ratio_threshold_triggers_suspect() -> None:
    values = [1000.0, None, None, None, None, None, None, None]
    res = _dataset(feature_values=values)
    registry = build_registry([_neutral()])
    report = _report(res, registry, config=DatasetReportConfig(max_null_fraction=0.2))
    codes = {w["code"] for w in report["warnings"]}
    assert "null_ratio_above_threshold" in codes


# --- markdown & attachments ------------------------------------------------


def test_markdown_contains_boundary_note_verbatim() -> None:
    res = _dataset()
    report = _report(res, build_registry([_neutral()]))
    md = render_dataset_inspection_markdown(report)
    assert BOUNDARY_NOTE in md
    assert "# Dataset Inspection Report (Phase 4D)" in md
    assert "## Feature Safety" in md
    assert "## Null" in md or "null" in md.lower()


def test_attach_feature_set_id_records_id() -> None:
    res = _dataset()
    report = _report(res, build_registry([_neutral()]))
    fsid = compute_feature_set_id([_neutral()])
    updated = attach_feature_set_id(report, fsid)
    assert updated["feature_set_id"] == fsid
    assert report["feature_set_id"] is None  # original untouched


def test_markdown_rejects_bad_schema() -> None:
    with pytest.raises(DatasetReportError):
        render_dataset_inspection_markdown({"schema_version": 99})


# --- Change 1: standalone "source lacks availability semantics" flag --------

_NO_AVAIL_MSG = "source carries no availability time; as-of provenance cannot be proven."


def test_missing_available_at_semantics_flagged_when_source_has_none() -> None:
    res = _dataset()  # bars-only dataset, no available_at, no reference table
    report = _report(res, build_registry([_neutral()]))
    assert any(
        w["code"] == "missing_available_at_semantics" and w["message"] == _NO_AVAIL_MSG
        for w in report["warnings"]
    )
    assert report["verdict"] in {VERDICT_SUSPECT, VERDICT_REJECTED}


def _dataset_with_reference():
    closes = [100.0, 110.0, 121.0, 130.0, 140.0, 150.0]
    bars = pl.DataFrame(
        {
            "symbol": ["AAPL"] * len(closes),
            "timestamp": [_day(2 + i) for i in range(len(closes))],
            "close": closes,
        }
    )
    labels = build_forward_return_labels(bars)
    features = bars.select(["symbol", "timestamp"]).with_columns(
        pl.Series(FEATURE, [float(i + 1) * 1000.0 for i in range(len(closes))])
    )
    reference = pl.DataFrame(
        {"symbol": ["AAPL"], "available_at": [_day(2)], "eps": [1.5]}
    )
    return assemble_ml_dataset(
        labels=labels,
        features=features,
        feature_specs=[FeatureSpec(FEATURE)],
        label_columns=[LABEL],
        reference=reference,
        reference_value_columns=["eps"],
        config=DatasetConfig(synthetic_no_universe=True),
        clock=_frozen_clock,
    )


def test_standalone_availability_flag_absent_when_reference_provides_semantics() -> None:
    res = _dataset_with_reference()
    report = _report(res, build_registry([_neutral()]))
    # the as-of reference column IS present -> no standalone "no availability time" warning
    assert not any(w["message"] == _NO_AVAIL_MSG for w in report["warnings"])
