"""Tests for backtest metrics. Synthetic only — no .env, no network."""

from math import sqrt

import pytest

from alpaca_quant.backtest.metrics.metrics import (
    BacktestMetrics,
    compute_metrics,
    equity_curve,
)


class TestEquityCurve:
    def test_basic(self) -> None:
        eq = equity_curve([0.1, 0.0, -0.1])
        assert eq[0] == pytest.approx(1.1)
        assert eq[1] == pytest.approx(1.1)
        assert eq[2] == pytest.approx(1.1 * 0.9)

    def test_empty(self) -> None:
        assert equity_curve([]) == []


class TestComputeMetrics:
    def test_returns_metrics_type(self) -> None:
        m = compute_metrics([0.01, -0.02, 0.03], [0.0, 0.0, 0.0])
        assert isinstance(m, BacktestMetrics)

    def test_sharpe_known_value(self) -> None:
        returns = [0.01, -0.01, 0.01, -0.01]
        m = compute_metrics(returns, [0.0] * 4)
        import polars as pl

        s = pl.Series(returns, dtype=pl.Float64)
        expected = float(s.mean() / s.std() * sqrt(252))
        assert m.sharpe == pytest.approx(expected)

    def test_zero_variance_sharpe_zero(self) -> None:
        m = compute_metrics([0.01, 0.01, 0.01], [0.0] * 3)
        assert m.sharpe == 0.0

    def test_no_downside_sortino_zero(self) -> None:
        m = compute_metrics([0.01, 0.02, 0.03], [0.0] * 3)
        assert m.sortino == 0.0

    def test_sortino_positive_with_downside(self) -> None:
        m = compute_metrics([0.02, -0.01, 0.03, -0.02], [0.0] * 4)
        assert m.sortino != 0.0

    def test_max_drawdown(self) -> None:
        # equity: 1.1, 0.88 (drop 20%), 0.968 -> trough relative to peak 1.1 is 0.88/1.1-1 = -0.2
        m = compute_metrics([0.1, -0.2, 0.1], [0.0] * 3)
        assert m.max_drawdown == pytest.approx(-0.2)

    def test_no_drawdown_is_zero(self) -> None:
        m = compute_metrics([0.01, 0.01, 0.01], [0.0] * 3)
        assert m.max_drawdown == 0.0

    def test_total_return(self) -> None:
        m = compute_metrics([0.1, 0.1], [0.0, 0.0])
        assert m.total_return == pytest.approx(1.1 * 1.1 - 1.0)

    def test_annual_turnover(self) -> None:
        m = compute_metrics([0.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0])
        assert m.annual_turnover == pytest.approx(0.25 * 252)

    def test_n_periods(self) -> None:
        m = compute_metrics([0.01, 0.02], [0.0, 0.0])
        assert m.n_periods == 2

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty return series"):
            compute_metrics([], [])
