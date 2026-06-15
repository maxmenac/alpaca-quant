"""Phase 4C dataset manifest tests. Synthetic only: no .env, network, API, or artifacts."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.research.data_contract import ADJ_UNKNOWN, FeatureSpec
from alpaca_quant.research.dataset_manifest import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    DatasetManifestError,
    render_dataset_manifest_markdown,
)
from alpaca_quant.research.ml_dataset import DatasetConfig, assemble_ml_dataset
from alpaca_quant.research.splits import (
    make_temporal_split,
    split_definitions_for_manifest,
)
from alpaca_quant.research.targets import (
    build_forward_return_labels,
    build_target_manifest,
)

LABEL = "label_forward_return_1d"


def _day(n: int) -> datetime:
    return datetime(2024, 1, n, tzinfo=UTC)


def _bars(symbol: str, closes: list[float], start: int = 2) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(closes),
            "timestamp": [_day(start + i) for i in range(len(closes))],
            "close": closes,
        }
    )


def _labels(bars: pl.DataFrame) -> pl.DataFrame:
    return build_forward_return_labels(bars.select(["symbol", "timestamp", "close"]))


def _features(bars: pl.DataFrame) -> pl.DataFrame:
    return bars.select(["symbol", "timestamp"]).with_columns(
        pl.Series("dollar_volume", [float(i + 1) * 1000.0 for i in range(bars.height)])
    )


def _frozen_clock():
    return datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


def _assemble(**kwargs):
    bars = kwargs.pop("bars", _bars("AAPL", [100.0, 110.0, 121.0, 130.0, 140.0, 150.0]))
    return assemble_ml_dataset(
        labels=_labels(bars),
        features=_features(bars),
        feature_specs=kwargs.pop("feature_specs", [FeatureSpec("dollar_volume")]),
        label_columns=[LABEL],
        config=kwargs.pop("config", DatasetConfig(synthetic_no_universe=True)),
        clock=_frozen_clock,
        **kwargs,
    )


def test_manifest_core_fields_present() -> None:
    manifest = _assemble().manifest
    assert manifest.schema_version == DATASET_MANIFEST_SCHEMA_VERSION
    assert manifest.generated_at_utc == _frozen_clock().isoformat()
    assert manifest.dataset_id.startswith("ds-")
    assert manifest.fingerprint.startswith("sha256:")
    assert manifest.target_columns == [LABEL]
    assert manifest.feature_columns == ["dollar_volume"]
    assert manifest.config_hash.startswith("sha256:")
    assert manifest.boundary_statement


def test_injectable_clock_freezes_generated_at() -> None:
    assert _assemble().manifest.generated_at_utc == "2026-06-16T12:00:00+00:00"


def test_null_matrix_records_label_and_feature_nulls() -> None:
    manifest = _assemble().manifest
    assert LABEL in manifest.null_matrix
    assert "dollar_volume" in manifest.null_matrix
    # last row label is null (no future bar)
    assert manifest.null_matrix[LABEL]["null_count"] >= 1


def test_excluded_by_reason_and_universe_coverage_present() -> None:
    manifest = _assemble().manifest
    assert manifest.row_count == 6
    assert manifest.eligible_row_count <= manifest.row_count
    assert sum(manifest.excluded_by_reason.values()) == (
        manifest.row_count - manifest.eligible_row_count
    )
    assert "no_universe_data" in manifest.universe_coverage


def test_no_universe_synthetic_mode_is_suspect() -> None:
    manifest = _assemble().manifest
    assert manifest.verdict == "SUSPECT"
    codes = {w["code"] for w in manifest.warnings}
    assert "no_universe_synthetic_mode" in codes
    assert "missing_symbol_identity" in codes


def test_ambiguous_adjustment_marks_suspect() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    features = bars.select(["symbol", "timestamp", "close"]).rename({"close": "px_level"})
    res = assemble_ml_dataset(
        labels=_labels(bars),
        features=features,
        feature_specs=[FeatureSpec("px_level", price_level=True, adjustment=ADJ_UNKNOWN)],
        label_columns=[LABEL],
        universe=pl.DataFrame(
            {"symbol": ["AAPL"], "valid_from": [_day(1)], "valid_to": [None]},
            schema_overrides={"valid_to": pl.Datetime(time_zone="UTC")},
        ),
        identity=pl.DataFrame(
            {
                "permanent_id": ["pid"],
                "symbol": ["AAPL"],
                "valid_from": [_day(1)],
                "valid_to": [None],
            },
            schema_overrides={"valid_to": pl.Datetime(time_zone="UTC")},
        ),
        config=DatasetConfig(),
        clock=_frozen_clock,
    )
    assert res.manifest.verdict == "SUSPECT"
    assert "px_level" in res.manifest.suspect_features


def test_config_hash_is_deterministic_for_same_payload() -> None:
    a = _assemble(config_payload={"k": 1}).manifest.config_hash
    b = _assemble(config_payload={"k": 1}).manifest.config_hash
    c = _assemble(config_payload={"k": 2}).manifest.config_hash
    assert a == b
    assert a != c


def test_split_definitions_recorded_in_manifest() -> None:
    res = _assemble()
    split = make_temporal_split(res.frame, max_horizon=1)
    defs = split_definitions_for_manifest([split])
    assert defs[0]["n_train"] == len(split.train_index)
    assert defs[0]["embargo"] >= defs[0]["max_horizon"]


def test_markdown_render_contains_sections() -> None:
    res = _assemble()
    tm = build_target_manifest(_labels(_bars("AAPL", [100.0, 110.0, 121.0])), horizon=1)
    md = render_dataset_manifest_markdown(res.manifest)
    assert "# ML Dataset Manifest (Phase 4C)" in md
    assert "## Null Matrix" in md
    assert "## Safety Boundary" in md
    assert "no model training" not in md.lower() or "NO model training" in md
    assert tm.fingerprint.startswith("sha256:")


def test_markdown_render_rejects_bad_schema() -> None:
    with pytest.raises(DatasetManifestError):
        render_dataset_manifest_markdown({"schema_version": 999})


def test_manifest_declares_no_training_flags() -> None:
    manifest = _assemble().manifest
    assert manifest.no_model_training is True
    assert manifest.no_cross_validation is True
    assert manifest.no_alpha is True
    assert manifest.split_definitions_only is True


# --- Change 2: declared corporate-action / adjustment status propagation ----


def test_partial_adjustment_declaration_carried_and_flagged() -> None:
    manifest = _assemble(
        data_declaration={"corporate_actions_status": "partial"}
    ).manifest
    # carried verbatim, never inferred
    assert manifest.declared_corporate_actions_status == "partial"
    codes = {w["code"] for w in manifest.warnings}
    assert "ambiguous_adjustment_declaration" in codes
    assert manifest.verdict == "SUSPECT"


def test_absent_adjustment_declaration_is_ambiguous() -> None:
    manifest = _assemble().manifest  # no declaration passed
    assert manifest.declared_corporate_actions_status is None
    codes = {w["code"] for w in manifest.warnings}
    assert "ambiguous_adjustment_declaration" in codes


def test_clean_adjustment_declaration_emits_no_adjustment_warning() -> None:
    manifest = _assemble(
        data_declaration={"corporate_actions_status": "full"}
    ).manifest
    assert manifest.declared_corporate_actions_status == "full"
    codes = {w["code"] for w in manifest.warnings}
    assert "ambiguous_adjustment_declaration" not in codes


def test_declared_status_round_trips_through_to_dict() -> None:
    manifest = _assemble(
        data_declaration={"data_declaration": {"corporate_actions_status": "best_effort"}}
    ).manifest
    payload = manifest.to_dict()
    assert payload["declared_corporate_actions_status"] == "best_effort"
    # nested wrapping (repo convention) is read but the value is carried verbatim
    assert manifest.declared_corporate_actions_status == "best_effort"
