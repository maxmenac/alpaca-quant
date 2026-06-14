# Backtest (Phase 3A — engine core)

An event-driven, point-in-time backtest engine that **scores caller-provided weights**. It is
deterministic, dependency-light (Polars + stdlib), and local-only.

**No alpha. No signals. No predictions. No model training. No live execution. No order
submission. No Alpaca API. No network. No `.env`.**

## What it does

```python
from alpaca_quant.backtest import run_backtest, CostModel

result = run_backtest(
    df,                       # columns: symbol, timestamp, close, weight
    weight_col="weight",      # caller-provided positions (the engine never invents them)
    horizon=1,                # forward-return horizon in bars
    cost_model=CostModel(commission_bps=0.0, slippage_bps=5.0),
    as_of="2024-01-31",       # optional PIT cutoff (zero-lookahead guard)
)
result.periods   # Polars frame: timestamp, gross_return, cost, net_return, equity
result.metrics   # BacktestMetrics: sharpe, sortino, max_drawdown, annual_turnover, ...
```

## How lookahead is prevented

1. **Causal alignment** — `pnl_t = weight_t * forward_return(t -> t+horizon)`. The weight at `t`
   is an input the caller produced from information available at/before `t`; the return is what
   happened *after* `t`. The engine only multiplies the two — it never lets a weight see its own
   forward return.
2. **Unknown future excluded** — the last `horizon` bars of each symbol have a null forward
   return and are dropped, so no PnL is fabricated on bars whose outcome is unknown.
3. **PIT guard** — when `as_of` is given, the engine calls `assert_no_lookahead` (from the PIT
   layer); any row dated after the cutoff makes the run fail closed.

## How it avoids generating alpha

The engine takes a `weight` column as input and never derives it. There is no strategy,
signal, prediction, or optimization logic anywhere in this package. Producing weights causally
is the caller's responsibility (a later phase). The engine also **never creates or requires** a
column named `signal`, `alpha`, `prediction`, `target`, `order`, or `trade` — enforced on the
output and covered by tests.

## forward_returns are OUTCOMES, not features

`alpaca_quant.backtest.outcomes.forward_returns` computes realized future returns used **only**
to score positions. They must never be fed into feature generation or used as model inputs —
that would be lookahead. They live strictly on the evaluation side.

## Costs

`CostModel(commission_bps, slippage_bps)` charges `total_bps` proportionally to turnover
(`|weight_t - weight_{t-1}|` per symbol; the first realizable bar is an entry from flat).
`load_cost_model("configs/costs.yaml", stress="none"|"2x"|"5x")` reads the committed cost
assumptions; the stress multipliers are defined for the null-model battery in a later sprint.

## Scope (Phase 3A)

In: forward-return outcomes, linear cost model, honest metrics (Sharpe, Sortino, max drawdown,
turnover, total return, CAGR; 252-day annualization; Sharpe/Sortino = 0.0 when variance is
zero), multi-symbol portfolio aggregation.

Deferred: null-model battery (3B), experiment-registry-integrated runs + report + CLI (3C),
real alphas (Phase 4).
