"""Phase 4C purged/embargoed split tests. No CV, no training — index definitions only."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.research.splits import (
    SplitDefinitionError,
    assert_split_disjoint_and_purged,
    make_temporal_split,
    split_summary,
)


def _panel(n: int, symbols: tuple[str, ...] = ("AAPL",)) -> pl.DataFrame:
    rows_symbol: list[str] = []
    rows_ts: list[datetime] = []
    for symbol in symbols:
        for i in range(n):
            rows_symbol.append(symbol)
            rows_ts.append(datetime(2024, 1, 1, tzinfo=UTC).replace(day=1 + i))
    return pl.DataFrame({"symbol": rows_symbol, "timestamp": rows_ts})


def test_split_blocks_are_disjoint_and_ordered() -> None:
    split = make_temporal_split(_panel(20), max_horizon=2)
    assert_split_disjoint_and_purged(_panel(20), split)
    train = set(split.train_index)
    val = set(split.validation_index)
    test = set(split.test_index)
    assert not (train & val) and not (train & test) and not (val & test)


def test_no_train_row_within_horizon_of_evaluation() -> None:
    panel = _panel(20)
    horizon = 3
    split = make_temporal_split(panel, max_horizon=horizon)
    timestamps = sorted(panel["timestamp"].unique().to_list())
    pos = {ts: i for i, ts in enumerate(timestamps)}
    row_ts = panel.sort(["symbol", "timestamp"])["timestamp"].to_list()
    eval_positions = [pos[row_ts[i]] for i in (*split.validation_index, *split.test_index)]
    first_eval = min(eval_positions)
    for i in split.train_index:
        p = pos[row_ts[i]]
        # label window must not reach into eval, and embargo must hold
        assert p + horizon < first_eval
        assert first_eval - p > split.embargo


def test_embargo_at_least_max_horizon() -> None:
    split = make_temporal_split(_panel(30), max_horizon=4)
    assert split.embargo >= split.max_horizon


def test_explicit_embargo_below_horizon_rejected() -> None:
    with pytest.raises(SplitDefinitionError):
        make_temporal_split(_panel(30), max_horizon=4, embargo=2)


def test_split_is_deterministic() -> None:
    a = make_temporal_split(_panel(25), max_horizon=2)
    b = make_temporal_split(_panel(25), max_horizon=2)
    assert a.train_index == b.train_index
    assert a.validation_index == b.validation_index
    assert a.test_index == b.test_index


def test_multi_symbol_split_keeps_both_symbols_per_block() -> None:
    panel = _panel(20, symbols=("AAPL", "MSFT"))
    split = make_temporal_split(panel, max_horizon=1)
    assert_split_disjoint_and_purged(panel, split)
    ordered = panel.sort(["symbol", "timestamp"])
    test_symbols = {ordered["symbol"][i] for i in split.test_index}
    assert test_symbols == {"AAPL", "MSFT"}


def test_too_few_timestamps_rejected() -> None:
    with pytest.raises(SplitDefinitionError):
        make_temporal_split(_panel(2), max_horizon=1)


def test_invalid_fractions_rejected() -> None:
    with pytest.raises(SplitDefinitionError):
        make_temporal_split(_panel(20), max_horizon=1, train_fraction=0.8, validation_fraction=0.3)


def test_invalid_max_horizon_rejected() -> None:
    with pytest.raises(SplitDefinitionError):
        make_temporal_split(_panel(20), max_horizon=0)


def test_split_summary_serializable() -> None:
    split = make_temporal_split(_panel(20), max_horizon=2)
    summary = split_summary(split)
    assert summary["n_train"] == len(split.train_index)
    assert summary["max_horizon"] == 2
    assert set(summary["boundary_timestamps"]) >= {"train_start", "test_end"}


def test_manual_purge_violation_is_detected() -> None:
    panel = _panel(20)
    good = make_temporal_split(panel, max_horizon=2)
    # Inject a train index that sits adjacent to the first eval row -> must be caught.
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
    with pytest.raises(SplitDefinitionError):
        assert_split_disjoint_and_purged(panel, tampered)
