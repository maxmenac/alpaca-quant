"""Phase 4A forward-return target tests. Synthetic only: no .env, network, or artifacts."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.research.targets import (
    NULL_REASON_COL,
    TargetLabelError,
    TargetManifest,
    build_forward_return_labels,
    build_target_manifest,
    fingerprint_target_labels,
    summarize_target_labels,
)


def _bars(
    closes: list[float | None],
    symbol: str = "AAPL",
    *,
    start_day: int = 2,
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": [symbol] * len(closes),
            "timestamp": [
                datetime(2024, 1, start_day + index, tzinfo=UTC)
                for index in range(len(closes))
            ],
            "close": closes,
        }
    )


def test_forward_return_values_and_tail_null() -> None:
    labelled = build_forward_return_labels(_bars([100.0, 110.0, 121.0]))
    values = labelled["label_forward_return_1d"].to_list()
    assert values[0] == pytest.approx(0.10)
    assert values[1] == pytest.approx(0.10)
    assert values[2] is None
    assert labelled[NULL_REASON_COL].to_list() == [
        None,
        None,
        "insufficient_future_rows",
    ]


def test_horizon_two_keeps_two_tail_rows_null() -> None:
    labelled = build_forward_return_labels(_bars([100.0, 110.0, 120.0, 132.0]), horizon=2)
    values = labelled["label_forward_return_2d"].to_list()
    assert values[0] == pytest.approx(0.20)
    assert values[1] == pytest.approx(0.20)
    assert values[2:] == [None, None]


def test_multi_symbol_shift_never_bleeds_between_symbols() -> None:
    mixed = pl.concat(
        [
            _bars([200.0, 220.0], "MSFT"),
            _bars([100.0, 110.0], "AAPL"),
        ]
    ).reverse()
    labelled = build_forward_return_labels(mixed)
    aapl = labelled.filter(pl.col("symbol") == "AAPL")["label_forward_return_1d"].to_list()
    msft = labelled.filter(pl.col("symbol") == "MSFT")["label_forward_return_1d"].to_list()
    assert aapl == pytest.approx([0.10, None], nan_ok=True)
    assert msft == pytest.approx([0.10, None], nan_ok=True)


def test_output_is_stably_sorted_by_symbol_timestamp() -> None:
    mixed = pl.concat(
        [
            _bars([200.0, 210.0], "MSFT"),
            _bars([100.0, 101.0], "AAPL"),
        ]
    ).reverse()
    labelled = build_forward_return_labels(mixed)
    keys = list(
        zip(
            labelled["symbol"].to_list(),
            labelled["timestamp"].to_list(),
            strict=True,
        )
    )
    assert keys == sorted(keys)


def test_null_labels_are_never_filled_with_zero() -> None:
    labelled = build_forward_return_labels(_bars([100.0, 100.0]))
    assert labelled["label_forward_return_1d"].to_list() == [0.0, None]
    assert labelled["label_forward_return_1d"].null_count() == 1


def test_source_and_future_price_nulls_have_distinct_reasons() -> None:
    labelled = build_forward_return_labels(_bars([100.0, None, 121.0, 133.1]))
    assert labelled["label_forward_return_1d"].to_list() == [
        None,
        None,
        pytest.approx(0.10),
        None,
    ]
    assert labelled[NULL_REASON_COL].to_list() == [
        "future_price_null",
        "source_price_null",
        None,
        "insufficient_future_rows",
    ]


def test_truncated_input_does_not_reach_past_its_available_future() -> None:
    full = _bars([100.0, 110.0, 121.0, 133.1, 146.41])
    cutoff = full.head(4)
    full_labels = build_forward_return_labels(full)
    cutoff_labels = build_forward_return_labels(cutoff)

    # Outcomes whose t+1 price exists within the cutoff are unchanged.
    assert cutoff_labels["label_forward_return_1d"][:3].to_list() == pytest.approx(
        full_labels["label_forward_return_1d"][:3].to_list()
    )
    # The cutoff tail stays unknown instead of borrowing the excluded future row.
    assert cutoff_labels["label_forward_return_1d"][-1] is None


def test_custom_label_column() -> None:
    labelled = build_forward_return_labels(_bars([100.0, 110.0]), label_col="future_return")
    assert "future_return" in labelled.columns


@pytest.mark.parametrize("label_col", ["alpha", "signal", "weight", "target_null_reason"])
def test_strategy_or_reserved_custom_label_column_rejected(label_col: str) -> None:
    with pytest.raises(TargetLabelError, match="reserved"):
        build_forward_return_labels(_bars([100.0, 110.0]), label_col=label_col)


@pytest.mark.parametrize("horizon", [0, -1, 1.5, True])
def test_invalid_horizon_rejected(horizon: object) -> None:
    with pytest.raises(TargetLabelError, match="horizon"):
        build_forward_return_labels(_bars([100.0, 110.0]), horizon=horizon)  # type: ignore[arg-type]


def test_empty_input_rejected() -> None:
    with pytest.raises(TargetLabelError, match="empty"):
        build_forward_return_labels(_bars([100.0]).head(0))


@pytest.mark.parametrize("column", ["symbol", "timestamp", "close"])
def test_missing_required_column_rejected(column: str) -> None:
    with pytest.raises(TargetLabelError, match="missing required"):
        build_forward_return_labels(_bars([100.0, 110.0]).drop(column))


def test_duplicate_symbol_timestamp_rejected() -> None:
    frame = pl.concat([_bars([100.0, 110.0]), _bars([100.0, 110.0])])
    with pytest.raises(TargetLabelError, match="duplicate"):
        build_forward_return_labels(frame)


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_non_null_price_rejected(price: float) -> None:
    with pytest.raises(TargetLabelError, match="price column"):
        build_forward_return_labels(_bars([100.0, price]))


def test_non_numeric_price_rejected() -> None:
    frame = _bars([100.0, 110.0]).with_columns(pl.col("close").cast(pl.String))
    with pytest.raises(TargetLabelError, match="numeric"):
        build_forward_return_labels(frame)


def test_existing_label_or_strategy_column_rejected() -> None:
    with pytest.raises(TargetLabelError, match="strategy or existing label"):
        build_forward_return_labels(_bars([100.0, 110.0]).with_columns(pl.lit(1.0).alias("alpha")))
    with pytest.raises(TargetLabelError, match="strategy or existing label"):
        build_forward_return_labels(
            _bars([100.0, 110.0]).with_columns(pl.lit(1.0).alias("label_existing"))
        )


def test_summary_reports_null_breakdown() -> None:
    labelled = build_forward_return_labels(_bars([100.0, None, 121.0, 133.1]))
    summary = summarize_target_labels(labelled, label_col="label_forward_return_1d")
    assert summary.row_count == 4
    assert summary.valid_label_count == 1
    assert summary.null_label_count == 3
    assert summary.null_fraction == pytest.approx(0.75)
    assert summary.null_breakdown == {
        "future_price_null": 1,
        "insufficient_future_rows": 1,
        "source_price_null": 1,
    }


def test_fingerprint_is_order_independent_and_deterministic() -> None:
    labelled = build_forward_return_labels(
        pl.concat([_bars([200.0, 220.0], "MSFT"), _bars([100.0, 110.0], "AAPL")])
    )
    first = fingerprint_target_labels(labelled, horizon=1)
    second = fingerprint_target_labels(labelled.reverse(), horizon=1)
    assert first == second
    assert first.startswith("sha256:")


def test_fingerprint_changes_with_source_values_or_horizon() -> None:
    one = build_forward_return_labels(_bars([100.0, 110.0, 121.0]))
    changed = build_forward_return_labels(_bars([100.0, 111.0, 121.0]))
    assert fingerprint_target_labels(one, horizon=1) != fingerprint_target_labels(
        changed, horizon=1
    )

    two = build_forward_return_labels(_bars([100.0, 110.0, 121.0]), horizon=2)
    assert fingerprint_target_labels(one, horizon=1) != fingerprint_target_labels(
        two, horizon=2
    )


def test_manifest_is_deterministic_except_creation_time() -> None:
    labelled = build_forward_return_labels(_bars([100.0, 110.0, 121.0]))
    first = build_target_manifest(
        labelled,
        horizon=1,
        source_dataset_id="rds-test",
        known_gaps=["holiday calendar not modelled"],
    )
    second = build_target_manifest(labelled, horizon=1, source_dataset_id="rds-test")
    assert isinstance(first, TargetManifest)
    assert first.target_id == second.target_id
    assert first.fingerprint == second.fingerprint
    assert first.target_id.startswith("tgt-")
    assert first.source_dataset_id == "rds-test"
    assert first.known_gaps == ["holiday calendar not modelled"]


def test_manifest_safety_boundary_is_labels_only() -> None:
    manifest = build_target_manifest(
        build_forward_return_labels(_bars([100.0, 110.0])),
        horizon=1,
    ).to_dict()
    for field in (
        "no_alpha",
        "no_strategy",
        "no_model_training",
        "no_signal_generation",
        "no_weights",
        "no_trading",
        "no_order_submission",
        "no_api_calls",
    ):
        assert manifest[field] is True
