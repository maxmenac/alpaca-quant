"""Event-driven, point-in-time backtest engine (zero lookahead).

The engine SCORES caller-provided weights. It does NOT generate alpha, signals, predictions, or
any strategy logic — weights are an input the caller is responsible for producing causally
(using only information available at/before each timestamp). The engine's job is correct, honest
alignment: position at t earns the return realized from t to t+horizon, minus costs on turnover.

No live execution. No order submission. No Alpaca API. No network. No .env.
"""

from dataclasses import dataclass, field
from datetime import date

import polars as pl

from alpaca_quant.backtest.costs.model import CostModel
from alpaca_quant.backtest.metrics.metrics import (
    DEFAULT_PERIODS_PER_YEAR,
    BacktestMetrics,
    compute_metrics,
    equity_curve,
)
from alpaca_quant.backtest.outcomes import forward_returns
from alpaca_quant.data.pit.reader import assert_no_lookahead

SYMBOL_COL = "symbol"
TIMESTAMP_COL = "timestamp"
PRICE_COL = "close"
_FORWARD_COL = "_forward_return"

# The backtester must never create or require any of these columns.
FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {"signal", "alpha", "prediction", "target", "order", "trade"}
)


class BacktestError(RuntimeError):
    """Raised when a backtest cannot be run safely."""


@dataclass(frozen=True)
class BacktestResult:
    """Result of one backtest: per-period series + summary metrics. Evaluation only."""

    periods: pl.DataFrame
    metrics: BacktestMetrics
    config: dict = field(default_factory=dict)
    no_live_execution: bool = True
    no_order_submission: bool = True


def run_backtest(
    df: pl.DataFrame,
    *,
    weight_col: str = "weight",
    horizon: int = 1,
    cost_model: CostModel | None = None,
    as_of: str | date | None = None,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> BacktestResult:
    """Backtest caller-supplied weights against point-in-time bars.

    - Requires columns: symbol, timestamp, close, <weight_col>. Weights are an input; the engine
      never invents them.
    - Causal alignment: pnl_t = weight_t * forward_return(t -> t+horizon). Rows whose forward
      return is unknown (the last `horizon` bars per symbol) are excluded from PnL.
    - Costs charged on turnover |weight_t - weight_{t-1}| per symbol; the first realizable bar
      counts as an entry from flat (previous weight 0).
    - If `as_of` is given, enforces zero lookahead via the PIT layer.
    """
    cost_model = cost_model or CostModel()

    if horizon < 1:
        raise BacktestError("horizon must be at least 1")

    required = (SYMBOL_COL, TIMESTAMP_COL, PRICE_COL, weight_col)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise BacktestError(f"backtest input is missing required columns: {', '.join(missing)}")

    if df.is_empty():
        raise BacktestError("backtest input is empty")

    if df.select([SYMBOL_COL, TIMESTAMP_COL]).is_duplicated().any():
        raise BacktestError("backtest input contains duplicate symbol/timestamp rows")

    weights = df[weight_col].cast(pl.Float64)
    if weights.is_null().any() or weights.is_nan().any() or weights.is_infinite().any():
        raise BacktestError("weights must be finite (no null/NaN/inf)")

    if as_of is not None:
        assert_no_lookahead(df, as_of)

    # Compute forward-return outcomes, then keep only rows whose outcome is realizable.
    scored = forward_returns(df, horizon=horizon, price_col=PRICE_COL, out_col=_FORWARD_COL)
    scored = scored.filter(pl.col(_FORWARD_COL).is_not_null())
    if scored.is_empty():
        raise BacktestError(
            f"no realizable rows after applying horizon={horizon} (forward return all unknown)"
        )

    scored = scored.sort([SYMBOL_COL, TIMESTAMP_COL])
    prev_weight = pl.col(weight_col).shift(1).over(SYMBOL_COL).fill_null(0.0)
    per_symbol = scored.with_columns(
        (pl.col(weight_col).cast(pl.Float64) * pl.col(_FORWARD_COL)).alias("_pnl"),
        (pl.col(weight_col).cast(pl.Float64) - prev_weight).abs().alias("_turnover"),
    ).with_columns((pl.col("_turnover") * cost_model.rate).alias("_cost"))

    # Aggregate to a portfolio time series (sum across symbols per timestamp).
    periods = (
        per_symbol.group_by(TIMESTAMP_COL)
        .agg(
            pl.col("_pnl").sum().alias("gross_return"),
            pl.col("_cost").sum().alias("cost"),
            pl.col("_turnover").sum().alias("turnover"),
        )
        .sort(TIMESTAMP_COL)
        .with_columns((pl.col("gross_return") - pl.col("cost")).alias("net_return"))
    )

    net = periods["net_return"].to_list()
    turnover = periods["turnover"].to_list()
    equity = equity_curve(net)
    periods = periods.with_columns(pl.Series("equity", equity)).select(
        [TIMESTAMP_COL, "gross_return", "cost", "net_return", "equity"]
    )

    forbidden = sorted(c for c in periods.columns if c in FORBIDDEN_COLUMNS)
    if forbidden:
        raise BacktestError(f"backtest output must not contain strategy columns: {forbidden}")

    metrics = compute_metrics(net, turnover, periods_per_year=periods_per_year)
    config = {
        "horizon": horizon,
        "commission_bps": cost_model.commission_bps,
        "slippage_bps": cost_model.slippage_bps,
        "periods_per_year": periods_per_year,
    }
    return BacktestResult(periods=periods, metrics=metrics, config=config)
