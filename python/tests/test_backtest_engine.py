"""Tests for the PIT backtest engine. Synthetic / tmp_path only — no .env, no network."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.backtest.costs.model import CostModel
from alpaca_quant.backtest.engine.engine import (
    FORBIDDEN_COLUMNS,
    BacktestError,
    BacktestResult,
    run_backtest,
)
from alpaca_quant.data.pit.reader import PITReadError


def _frame(closes, weights, symbol: str = "AAPL") -> pl.DataFrame:
    n = len(closes)
    return pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "close": [float(c) for c in closes],
            "weight": [float(w) for w in weights],
        }
    )


class TestBasic:
    def test_returns_result_type(self) -> None:
        res = run_backtest(_frame([100, 110, 121], [1.0, 1.0, 1.0]))
        assert isinstance(res, BacktestResult)

    def test_zero_weights_zero_return(self) -> None:
        res = run_backtest(_frame([100, 110, 121, 130], [0.0, 0.0, 0.0, 0.0]))
        assert all(r == 0.0 for r in res.periods["net_return"].to_list())
        assert all(e == pytest.approx(1.0) for e in res.periods["equity"].to_list())

    def test_constant_weight_matches_forward_returns_gross(self) -> None:
        res = run_backtest(
            _frame([100, 110, 121], [1.0, 1.0, 1.0]), cost_model=CostModel()
        )
        # last bar excluded; gross returns = forward returns of first two bars = 0.10, 0.10
        gross = res.periods["gross_return"].to_list()
        assert gross == pytest.approx([0.10, 0.10])

    def test_flags(self) -> None:
        res = run_backtest(_frame([100, 110], [1.0, 1.0]))
        assert res.no_live_execution is True
        assert res.no_order_submission is True


class TestLastBarExcluded:
    def test_last_unknown_forward_excluded(self) -> None:
        # 4 bars, horizon 1 => 3 realizable periods (last bar has no forward return)
        res = run_backtest(_frame([100, 110, 121, 133], [1.0, 1.0, 1.0, 1.0]))
        assert len(res.periods) == 3
        last_ts = res.periods["timestamp"].max()
        assert last_ts == datetime(2024, 1, 4, tzinfo=UTC)  # 2024-01-05 bar is excluded

    def test_horizon_too_large_rejected(self) -> None:
        with pytest.raises(BacktestError, match="no realizable rows"):
            run_backtest(_frame([100, 110], [1.0, 1.0]), horizon=5)


class TestCosts:
    def test_cost_on_first_entry_from_flat(self) -> None:
        # weight 1.0 throughout: first realizable bar is an entry from flat (turnover 1.0),
        # subsequent bars have zero turnover.
        model = CostModel(commission_bps=0.0, slippage_bps=10.0)  # rate = 0.001
        res = run_backtest(_frame([100, 110, 121], [1.0, 1.0, 1.0]), cost_model=model)
        costs = res.periods["cost"].to_list()
        assert costs[0] == pytest.approx(0.001)  # entry from flat
        assert costs[1] == pytest.approx(0.0)

    def test_cost_reduces_net_vs_gross(self) -> None:
        model = CostModel(slippage_bps=10.0)
        res = run_backtest(_frame([100, 110, 121], [1.0, 1.0, 1.0]), cost_model=model)
        row0 = res.periods.row(0, named=True)
        assert row0["net_return"] < row0["gross_return"]

    def test_no_cost_when_no_cost_model(self) -> None:
        res = run_backtest(_frame([100, 110, 121], [1.0, 1.0, 1.0]))
        assert all(c == 0.0 for c in res.periods["cost"].to_list())


class TestNoLookahead:
    def test_future_bars_rejected_with_as_of(self) -> None:
        # frame contains rows after the cutoff -> engine rejects via PIT guard
        df = _frame([100, 110, 121, 133], [1.0, 1.0, 1.0, 1.0])
        with pytest.raises(PITReadError, match="lookahead"):
            run_backtest(df, as_of="2024-01-03")

    def test_cutoff_sample_result_stable(self) -> None:
        full = _frame([100, 110, 121, 133, 140], [1.0, 1.0, 1.0, 1.0, 1.0])
        cutoff = datetime(2024, 1, 4, tzinfo=UTC)
        truncated = full.filter(pl.col("timestamp") <= cutoff)

        res_trunc = run_backtest(truncated)
        # full data pre-filtered to the cutoff must give an identical result
        res_prefiltered = run_backtest(full.filter(pl.col("timestamp") <= cutoff))
        assert res_trunc.periods.equals(res_prefiltered.periods)
        assert res_trunc.metrics == res_prefiltered.metrics


class TestMultiSymbol:
    def test_portfolio_aggregation(self) -> None:
        aapl = _frame([100, 110], [0.5, 0.5], symbol="AAPL")  # fwd 0.10
        msft = _frame([200, 220], [0.5, 0.5], symbol="MSFT")  # fwd 0.10
        df = pl.concat([aapl, msft])
        res = run_backtest(df)
        # one realizable timestamp (2024-01-02); gross = 0.5*0.10 + 0.5*0.10 = 0.10
        assert len(res.periods) == 1
        assert res.periods["gross_return"][0] == pytest.approx(0.10)


class TestNoForbiddenColumns:
    def test_output_has_no_strategy_columns(self) -> None:
        res = run_backtest(_frame([100, 110, 121], [1.0, 1.0, 1.0]))
        for col in res.periods.columns:
            assert col not in FORBIDDEN_COLUMNS
        assert set(res.periods.columns) == {
            "timestamp",
            "gross_return",
            "cost",
            "net_return",
            "equity",
        }

    def test_forbidden_input_columns_ignored(self) -> None:
        df = _frame([100, 110, 121], [1.0, 1.0, 1.0]).with_columns(
            pl.lit(0.42).alias("signal"), pl.lit(1.0).alias("alpha")
        )
        res = run_backtest(df)
        assert "signal" not in res.periods.columns
        assert "alpha" not in res.periods.columns


class TestValidation:
    def test_missing_column_rejected(self) -> None:
        df = _frame([100, 110], [1.0, 1.0]).drop("close")
        with pytest.raises(BacktestError, match="missing required columns"):
            run_backtest(df)

    def test_empty_rejected(self) -> None:
        df = _frame([100, 110], [1.0, 1.0]).head(0)
        with pytest.raises(BacktestError, match="empty"):
            run_backtest(df)

    def test_duplicate_keys_rejected(self) -> None:
        df = pl.concat([_frame([100, 110], [1.0, 1.0]), _frame([100, 110], [1.0, 1.0])])
        with pytest.raises(BacktestError, match="duplicate"):
            run_backtest(df)

    def test_non_finite_weight_rejected_inf(self) -> None:
        df = _frame([100, 110, 121], [1.0, float("inf"), 1.0])
        with pytest.raises(BacktestError, match="finite"):
            run_backtest(df)

    def test_non_finite_weight_rejected_nan(self) -> None:
        df = _frame([100, 110, 121], [1.0, float("nan"), 1.0])
        with pytest.raises(BacktestError, match="finite"):
            run_backtest(df)

    def test_horizon_below_one_rejected(self) -> None:
        with pytest.raises(BacktestError, match="horizon must be at least 1"):
            run_backtest(_frame([100, 110], [1.0, 1.0]), horizon=0)


class TestDeterminism:
    def test_same_input_same_metrics(self) -> None:
        df = _frame([100, 110, 121, 133], [1.0, 0.5, 1.0, 0.5])
        a = run_backtest(df)
        b = run_backtest(df)
        assert a.metrics == b.metrics
        assert a.periods.equals(b.periods)
