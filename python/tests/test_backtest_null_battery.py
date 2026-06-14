"""Integration tests for the null-model battery. Synthetic + tmp_path only — no .env, no net."""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
import yaml

from alpaca_quant.backtest.engine.engine import run_backtest
from alpaca_quant.backtest.null_models import (
    NullBatteryError,
    NullBatteryReport,
    future_leak_weights,
    run_null_battery,
    shifted_weights,
)

# Oscillating factors with varying magnitude: forward returns alternate sign with different
# sizes, so a sign(forward) leak yields all-positive PnL with non-zero variance (finite, high
# Sharpe) — and turnover-heavy baselines make costs bite every period.
_FACTORS = [1.03, 0.98, 1.05, 0.97, 1.04, 0.96]


def _frame(n: int = 30, symbol: str = "AAPL") -> pl.DataFrame:
    closes = [100.0]
    for i in range(n - 1):
        closes.append(closes[-1] * _FACTORS[i % len(_FACTORS)])
    # Neutral buy-and-hold baseline: uncorrelated with the alternating forward-return signs,
    # so the deliberate future leak must clearly beat it.
    weights = [1.0] * n
    return pl.DataFrame(
        {
            "symbol": [symbol] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "close": closes,
            "weight": weights,
        }
    )


def _costs_yaml(tmp_path: Path) -> str:
    path = tmp_path / "costs.yaml"
    path.write_text(
        yaml.dump(
            {
                "commission_bps": 0,
                "slippage_bps_daily": 5,
                "slippage_bps_stress_2x": 10,
                "slippage_bps_stress_5x": 25,
            }
        )
    )
    return str(path)


class TestBatteryReport:
    def test_returns_report(self, tmp_path: Path) -> None:
        report = run_null_battery(_frame(), costs_path=_costs_yaml(tmp_path))
        assert isinstance(report, NullBatteryReport)

    def test_future_leak_explodes(self, tmp_path: Path) -> None:
        report = run_null_battery(_frame(), costs_path=_costs_yaml(tmp_path))
        assert report.future_leak_detected is True
        assert report.future_leak.sharpe > report.baseline.sharpe
        assert report.future_leak.sharpe > report.random_weights.sharpe
        assert report.future_leak.sharpe > report.shuffled_weights.sharpe

    def test_cost_stress_monotonic(self, tmp_path: Path) -> None:
        report = run_null_battery(_frame(), costs_path=_costs_yaml(tmp_path))
        assert report.baseline.total_return >= report.cost_stress_2x.total_return
        assert report.cost_stress_2x.total_return >= report.cost_stress_5x.total_return

    def test_determinism_same_seed(self, tmp_path: Path) -> None:
        costs = _costs_yaml(tmp_path)
        a = run_null_battery(_frame(), seed=42, costs_path=costs)
        b = run_null_battery(_frame(), seed=42, costs_path=costs)
        assert a.as_dict() == b.as_dict()

    def test_different_seed_changes_noise_not_leak(self, tmp_path: Path) -> None:
        costs = _costs_yaml(tmp_path)
        a = run_null_battery(_frame(), seed=1, costs_path=costs)
        b = run_null_battery(_frame(), seed=2, costs_path=costs)
        assert a.random_weights != b.random_weights
        assert a.future_leak == b.future_leak  # leak has no seed
        assert a.baseline == b.baseline

    def test_repo_default_costs_config(self) -> None:
        # committed configs/costs.yaml is read-only source, not a data artifact
        report = run_null_battery(_frame())
        assert report.future_leak_detected is True


class TestShiftDestroysEdge:
    def test_shifting_leak_collapses_sharpe(self) -> None:
        """Shifting a winning (leaked) signal by one period destroys its edge."""
        df = _frame()
        leaked = future_leak_weights(df)
        leak_sharpe = run_backtest(leaked).metrics.sharpe
        shifted = shifted_weights(leaked)
        shifted_sharpe = run_backtest(shifted).metrics.sharpe
        assert leak_sharpe > shifted_sharpe
        assert shifted_sharpe < 5.0  # the absurd edge is gone


class TestValidation:
    def test_missing_column_rejected(self, tmp_path: Path) -> None:
        df = _frame().drop("close")
        with pytest.raises(NullBatteryError, match="missing required columns"):
            run_null_battery(df, costs_path=_costs_yaml(tmp_path))

    def test_horizon_below_one_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(NullBatteryError, match="horizon must be at least 1"):
            run_null_battery(_frame(), horizon=0, costs_path=_costs_yaml(tmp_path))

    def test_bad_costs_path_rejected(self) -> None:
        from alpaca_quant.backtest.costs.model import CostModelError

        with pytest.raises(CostModelError, match="not found"):
            run_null_battery(_frame(), costs_path="does/not/exist.yaml")
