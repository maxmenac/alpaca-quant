"""Phase 4C ML dataset assembly tests. Synthetic only: no .env, network, API, or artifacts.

These tests prove the anti-leakage contract: as-of delay, PIT universe, no feature peek,
feature/label non-overlap, back-adjustment trap, no silent fill, no global scaling, and
reproducible fingerprints with Phase 4A lineage. No model is trained and no CV is executed.
"""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.research.data_contract import (
    ADJ_BACK_ADJUSTED,
    ADJ_PIT_SAFE,
    DataContractError,
    FeatureSpec,
)
from alpaca_quant.research.ml_dataset import (
    ELIGIBILITY_REASON_COL,
    ELIGIBLE_COL,
    FEATURE_CUTOFF_COL,
    MAX_LABEL_HORIZON_COL,
    REASON_ALL_LABELS_NULL,
    REASON_ELIGIBLE,
    REASON_INSUFFICIENT_FEATURE_HISTORY,
    REASON_NOT_IN_UNIVERSE,
    DatasetConfig,
    MLDatasetError,
    assemble_ml_dataset,
)
from alpaca_quant.research.targets import (
    build_forward_return_labels,
    build_target_manifest,
)

LABEL = "label_forward_return_1d"


def _day(n: int) -> datetime:
    return datetime(2024, 1, n, tzinfo=UTC)


def _bars(symbol: str, closes: list[float | None], start: int = 2) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(closes),
            "timestamp": [_day(start + i) for i in range(len(closes))],
            "close": closes,
        }
    )


def _labels(frame: pl.DataFrame) -> pl.DataFrame:
    return build_forward_return_labels(frame.select(["symbol", "timestamp", "close"]))


def _features(frame: pl.DataFrame, *, feature: str = "dollar_volume") -> pl.DataFrame:
    return frame.select(["symbol", "timestamp"]).with_columns(
        pl.Series(
            feature,
            [float(i + 1) * 1000.0 for i in range(frame.height)],
        )
    )


def _assemble(labels, features, **kwargs):
    config = kwargs.pop("config", DatasetConfig(synthetic_no_universe=True))
    specs = kwargs.pop("feature_specs", [FeatureSpec("dollar_volume")])
    return assemble_ml_dataset(
        labels=labels,
        features=features,
        feature_specs=specs,
        label_columns=kwargs.pop("label_columns", [LABEL]),
        config=config,
        **kwargs,
    )


# --- shape & metadata ------------------------------------------------------


def test_assembled_frame_has_metadata_columns() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    res = _assemble(_labels(bars), _features(bars))
    for column in (
        ELIGIBLE_COL,
        ELIGIBILITY_REASON_COL,
        FEATURE_CUTOFF_COL,
        MAX_LABEL_HORIZON_COL,
        "permanent_id",
        "universe_status",
    ):
        assert column in res.frame.columns


def test_frame_is_stably_sorted_by_id_timestamp() -> None:
    bars = pl.concat([_bars("MSFT", [10.0, 11.0, 12.0]), _bars("AAPL", [100.0, 110.0, 121.0])])
    res = _assemble(_labels(bars), _features(bars))
    syms = res.frame["symbol"].to_list()
    assert syms == sorted(syms)


# --- feature/label non-overlap (contract item 5) ---------------------------


def test_feature_cutoff_strictly_before_timestamp_for_eligible_rows() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0, 140.0])
    res = _assemble(_labels(bars), _features(bars))
    eligible = res.frame.filter(pl.col(ELIGIBLE_COL))
    assert eligible.height > 0
    assert (eligible[FEATURE_CUTOFF_COL] < eligible["timestamp"]).all()
    assert eligible[MAX_LABEL_HORIZON_COL].to_list() == [1] * eligible.height


def test_first_row_per_symbol_is_insufficient_history() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0])
    res = _assemble(_labels(bars), _features(bars))
    first = res.frame.sort("timestamp").row(0, named=True)
    assert first[ELIGIBILITY_REASON_COL] == REASON_INSUFFICIENT_FEATURE_HISTORY
    assert first[ELIGIBLE_COL] is False


# --- no feature peek (contract item: corrupting t+1 must not change t) ------


def test_corrupting_future_feature_does_not_change_earlier_value() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    features = _features(bars)
    baseline = _assemble(_labels(bars), features).frame
    base_val = baseline.filter(pl.col("timestamp") == _day(3))["dollar_volume"].item()

    corrupted = features.with_columns(
        pl.when(pl.col("timestamp") == _day(4))
        .then(pl.lit(-999999.0))
        .otherwise(pl.col("dollar_volume"))
        .alias("dollar_volume")
    )
    after = _assemble(_labels(bars), corrupted).frame
    after_val = after.filter(pl.col("timestamp") == _day(3))["dollar_volume"].item()
    assert after_val == base_val


# --- no silent fill / no global scaling ------------------------------------


def test_null_feature_and_null_label_remain_null() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    features = _features(bars).with_columns(
        pl.when(pl.col("timestamp") == _day(3))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col("dollar_volume"))
        .alias("dollar_volume")
    )
    res = _assemble(_labels(bars), features)
    null_feat = res.frame.filter(pl.col("timestamp") == _day(3))["dollar_volume"].item()
    assert null_feat is None
    # last row label is null (no future bar) and must stay null, never 0.0
    last_label = res.frame.sort("timestamp")[LABEL].to_list()[-1]
    assert last_label is None


def test_feature_values_are_passed_through_unscaled() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    features = _features(bars)
    res = _assemble(_labels(bars), features)
    merged = features.join(
        res.frame.select(["symbol", "timestamp", "dollar_volume"]),
        on=["symbol", "timestamp"],
        suffix="_out",
    )
    assert (merged["dollar_volume"] == merged["dollar_volume_out"]).all()


# --- PIT universe ----------------------------------------------------------


def test_delisted_and_not_yet_listed_rows_are_ineligible() -> None:
    old = _bars("OLD", [10.0, 11.0, 12.0, 13.0, 14.0])
    new = _bars("NEW", [20.0, 21.0, 22.0, 23.0, 24.0])
    bars = pl.concat([old, new])
    universe = pl.DataFrame(
        {
            "symbol": ["OLD", "NEW"],
            "valid_from": [_day(2), _day(5)],
            "valid_to": [_day(4), None],
        },
        schema_overrides={"valid_to": pl.Datetime(time_zone="UTC")},
    )
    res = assemble_ml_dataset(
        labels=_labels(bars),
        features=_features(bars),
        feature_specs=[FeatureSpec("dollar_volume")],
        label_columns=[LABEL],
        universe=universe,
        config=DatasetConfig(),
    )
    frame = res.frame
    old_day5 = frame.filter((pl.col("symbol") == "OLD") & (pl.col("timestamp") == _day(5)))
    assert old_day5[ELIGIBILITY_REASON_COL].item() == REASON_NOT_IN_UNIVERSE
    new_day3 = frame.filter((pl.col("symbol") == "NEW") & (pl.col("timestamp") == _day(3)))
    assert new_day3[ELIGIBILITY_REASON_COL].item() == REASON_NOT_IN_UNIVERSE
    # day5 is in-universe, has prior history (cutoff day4) and a valid forward label.
    new_day5 = frame.filter((pl.col("symbol") == "NEW") & (pl.col("timestamp") == _day(5)))
    assert new_day5[ELIGIBLE_COL].item() is True


# --- as-of reference -------------------------------------------------------


def test_reference_value_respects_available_at() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0, 140.0])
    reference = pl.DataFrame(
        {"symbol": ["AAPL"], "available_at": [_day(5)], "eps": [2.5]}
    )
    res = assemble_ml_dataset(
        labels=_labels(bars),
        features=_features(bars),
        feature_specs=[FeatureSpec("dollar_volume")],
        label_columns=[LABEL],
        reference=reference,
        reference_value_columns=["eps"],
        config=DatasetConfig(synthetic_no_universe=True),
    )
    frame = res.frame.sort("timestamp")
    eps = frame["eps"].to_list()
    assert eps[0] is None and eps[1] is None and eps[2] is None  # days 2,3,4
    assert eps[3] == 2.5 and eps[4] == 2.5  # days 5,6


# --- back-adjustment trap --------------------------------------------------


def test_back_adjusted_price_feature_is_rejected() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0])
    features = bars.select(["symbol", "timestamp"]).with_columns(
        pl.col("timestamp").cum_count().over("symbol").cast(pl.Float64).alias("adj_close_level")
    )
    with pytest.raises(DataContractError):
        assemble_ml_dataset(
            labels=_labels(bars),
            features=features,
            feature_specs=[
                FeatureSpec("adj_close_level", price_level=True, adjustment=ADJ_BACK_ADJUSTED)
            ],
            label_columns=[LABEL],
            config=DatasetConfig(synthetic_no_universe=True),
        )


def test_pit_safe_price_feature_unchanged_by_future_split_row() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    features = bars.select(["symbol", "timestamp", "close"]).rename({"close": "close_level"})
    spec = [FeatureSpec("close_level", price_level=True, adjustment=ADJ_PIT_SAFE)]
    before = assemble_ml_dataset(
        labels=_labels(bars),
        features=features,
        feature_specs=spec,
        label_columns=[LABEL],
        config=DatasetConfig(synthetic_no_universe=True),
    ).frame
    before_val = before.filter(pl.col("timestamp") == _day(3))["close_level"].item()

    # Append a future split day; pit-safe (as-reported) prices must NOT rewrite earlier rows.
    bars_split = pl.concat([bars, _bars("AAPL", [65.0], start=6)])
    features_split = bars_split.select(["symbol", "timestamp", "close"]).rename(
        {"close": "close_level"}
    )
    after = assemble_ml_dataset(
        labels=_labels(bars_split),
        features=features_split,
        feature_specs=spec,
        label_columns=[LABEL],
        config=DatasetConfig(synthetic_no_universe=True),
    ).frame
    after_val = after.filter(pl.col("timestamp") == _day(3))["close_level"].item()
    assert after_val == before_val


# --- eligibility reasons ---------------------------------------------------


def test_all_labels_null_row_is_ineligible() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    res = _assemble(_labels(bars), _features(bars))
    last = res.frame.sort("timestamp").row(-1, named=True)
    assert last[ELIGIBILITY_REASON_COL] == REASON_ALL_LABELS_NULL
    eligible_reasons = set(res.frame[ELIGIBILITY_REASON_COL].to_list())
    assert REASON_ELIGIBLE in eligible_reasons


# --- fail closed -----------------------------------------------------------


def test_duplicate_rows_rejected() -> None:
    labels = pl.DataFrame(
        {
            "symbol": ["AAPL", "AAPL"],
            "timestamp": [_day(2), _day(2)],
            LABEL: [0.1, 0.2],
        }
    )
    features = pl.DataFrame(
        {"symbol": ["AAPL", "AAPL"], "timestamp": [_day(2), _day(3)], "dollar_volume": [1.0, 2.0]}
    )
    with pytest.raises(MLDatasetError):
        _assemble(labels, features)


def test_non_datetime_timestamp_rejected() -> None:
    labels = pl.DataFrame(
        {"symbol": ["AAPL", "AAPL"], "timestamp": [1, 2], LABEL: [0.1, None]}
    )
    features = pl.DataFrame(
        {"symbol": ["AAPL", "AAPL"], "timestamp": [1, 2], "dollar_volume": [1.0, 2.0]}
    )
    with pytest.raises(MLDatasetError):
        _assemble(labels, features)


def test_missing_label_column_rejected() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0])
    with pytest.raises(MLDatasetError):
        assemble_ml_dataset(
            labels=_labels(bars),
            features=_features(bars),
            feature_specs=[FeatureSpec("dollar_volume")],
            label_columns=["does_not_exist"],
            config=DatasetConfig(synthetic_no_universe=True),
        )


def test_missing_required_feature_rejected() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0])
    with pytest.raises(MLDatasetError):
        assemble_ml_dataset(
            labels=_labels(bars),
            features=_features(bars),
            feature_specs=[FeatureSpec("absent_feature")],
            label_columns=[LABEL],
            config=DatasetConfig(synthetic_no_universe=True),
        )


# --- Change 3: feature/bar timezone mismatch detected at assembly ----------


def test_feature_timezone_mismatch_flagged_and_not_mutated() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    labels = _labels(bars)
    features = _features(bars)
    # feature timestamps in a DIFFERENT timezone than the UTC bars (test fixture setup only)
    foreign = features.with_columns(
        pl.col("timestamp").dt.convert_time_zone("Europe/Copenhagen")
    )
    before_ts = foreign["timestamp"].to_list()

    res = _assemble(labels, foreign)
    assert res.manifest.timezone_alignment["mismatch"] is True
    codes = {w["code"] for w in res.manifest.warnings}
    assert "feature_timezone_mismatch" in codes
    assert res.verdict == "SUSPECT"
    # the feature was NOT joined (refused) and the source timestamps were NOT altered
    assert "dollar_volume" not in res.frame.columns
    assert foreign["timestamp"].to_list() == before_ts
    assert foreign.schema["timestamp"].time_zone == "Europe/Copenhagen"


def test_matching_timezone_has_no_mismatch_warning() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    res = _assemble(_labels(bars), _features(bars))
    assert res.manifest.timezone_alignment["mismatch"] is False
    codes = {w["code"] for w in res.manifest.warnings}
    assert "feature_timezone_mismatch" not in codes
    assert "dollar_volume" in res.frame.columns


# --- reproducibility & lineage ---------------------------------------------


def test_fingerprint_stable_under_row_reordering() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    labels = _labels(bars)
    features = _features(bars)
    a = _assemble(labels, features).manifest.fingerprint
    b = _assemble(labels.reverse(), features.reverse()).manifest.fingerprint
    assert a == b


def test_fingerprint_changes_when_feature_value_changes() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    labels = _labels(bars)
    features = _features(bars)
    a = _assemble(labels, features).manifest.fingerprint
    bumped = features.with_columns((pl.col("dollar_volume") + 1.0).alias("dollar_volume"))
    b = _assemble(labels, bumped).manifest.fingerprint
    assert a != b


def test_manifest_lineage_includes_phase_4a_fingerprint() -> None:
    bars = _bars("AAPL", [100.0, 110.0, 121.0, 130.0])
    labels = _labels(bars)
    tm = build_target_manifest(labels, horizon=1)
    res = _assemble(labels, _features(bars), target_manifest=tm)
    assert res.manifest.source_label_fingerprint == tm.fingerprint
