"""Backtest (ARCHITECTURE.md §3.6, ROADMAP Phase 3): event-driven, PIT, zero lookahead.

Phase 3A: deterministic engine core that scores caller-provided weights. It does not generate
alpha/signals/predictions, train models, execute trades, or submit orders.
"""

from alpaca_quant.backtest.costs.model import CostModel, CostModelError, load_cost_model
from alpaca_quant.backtest.engine.engine import (
    FORBIDDEN_COLUMNS,
    BacktestError,
    BacktestResult,
    run_backtest,
)
from alpaca_quant.backtest.metrics.metrics import (
    BacktestMetrics,
    compute_metrics,
    equity_curve,
)
from alpaca_quant.backtest.null_models import (
    NullBatteryError,
    NullBatteryReport,
    NullModelResult,
    future_leak_weights,
    random_weights,
    run_null_battery,
    shifted_weights,
    shuffled_weights,
)
from alpaca_quant.backtest.outcomes import OutcomeError, forward_returns

__all__ = [
    "FORBIDDEN_COLUMNS",
    "BacktestError",
    "BacktestMetrics",
    "BacktestResult",
    "CostModel",
    "CostModelError",
    "NullBatteryError",
    "NullBatteryReport",
    "NullModelResult",
    "OutcomeError",
    "compute_metrics",
    "equity_curve",
    "forward_returns",
    "future_leak_weights",
    "load_cost_model",
    "random_weights",
    "run_backtest",
    "run_null_battery",
    "shifted_weights",
    "shuffled_weights",
]
