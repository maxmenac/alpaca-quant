"""Null-model battery: diagnostics that test whether the backtest engine is sane.

RESEARCH_PROTOCOL.md §2. These are DIAGNOSTICS, not strategies. They take whatever weights
they are handed, transform them (random / shuffled / shifted / deliberate future leak) or rerun
them under cost stress, and push them through the existing `run_backtest(...)`. They make NO
alpha claim and gate nothing automatically — the human reads the report and decides.

A good engine makes noise score ≈ 0 and makes a deliberate, controlled future leak EXPLODE. If
the leak does not explode, the engine (or the trap) is broken and must be fixed before any real
result is trusted.

Pure library, local-only, deterministic seeds. No network, no Alpaca API, no .env, no live
trading, no order logic, no model training, no real alpha, no optimizer.
"""

import random
from dataclasses import asdict, dataclass

import polars as pl

from alpaca_quant.backtest.costs.model import CostModel, load_cost_model
from alpaca_quant.backtest.engine.engine import BacktestResult, run_backtest
from alpaca_quant.backtest.outcomes import forward_returns

SYMBOL_COL = "symbol"
TIMESTAMP_COL = "timestamp"
PRICE_COL = "close"
_LEAK_FORWARD_COL = "_leak_forward_return"


class NullBatteryError(RuntimeError):
    """Raised when the null-model battery cannot be built or run safely."""


# --------------------------------------------------------------------------------------------
# Weight transforms — each returns a NEW frame with `weight_col` replaced by finite values.
# Non-weight columns (symbol, timestamp, close) are never modified.
# --------------------------------------------------------------------------------------------


def random_weights(
    df: pl.DataFrame,
    *,
    seed: int,
    weight_col: str = "weight",
    low: float = -1.0,
    high: float = 1.0,
) -> pl.DataFrame:
    """Replace weights with seeded uniform draws in [low, high] (uncorrelated with outcomes)."""
    if high < low:
        raise NullBatteryError("high must be >= low")
    rng = random.Random(seed)
    values = [rng.uniform(low, high) for _ in range(df.height)]
    return df.with_columns(pl.Series(weight_col, values, dtype=pl.Float64))


def shuffled_weights(
    df: pl.DataFrame,
    *,
    seed: int,
    weight_col: str = "weight",
) -> pl.DataFrame:
    """Seeded permutation of the existing weights, destroying weight<->outcome alignment."""
    values = df[weight_col].cast(pl.Float64).to_list()
    rng = random.Random(seed)
    rng.shuffle(values)
    return df.with_columns(pl.Series(weight_col, values, dtype=pl.Float64))


def shifted_weights(
    df: pl.DataFrame,
    *,
    weight_col: str = "weight",
    periods: int = 1,
) -> pl.DataFrame:
    """Shift weights +periods per symbol (today uses an earlier intended weight)."""
    if periods < 1:
        raise NullBatteryError("periods must be at least 1")
    return df.sort([SYMBOL_COL, TIMESTAMP_COL]).with_columns(
        pl.col(weight_col)
        .cast(pl.Float64)
        .shift(periods)
        .over(SYMBOL_COL)
        .fill_null(0.0)
        .alias(weight_col)
    )


def future_leak_weights(
    df: pl.DataFrame,
    *,
    horizon: int = 1,
    weight_col: str = "weight",
    price_col: str = PRICE_COL,
) -> pl.DataFrame:
    """Controlled leak: weight = sign(forward_return(t -> t+horizon)).

    The position deliberately peeks at its own outcome. A correct engine turns this into
    |forward_return| PnL — an unrealistically high Sharpe. The last `horizon` rows per symbol
    have an unknown forward return and are set to 0.0 (the engine drops them anyway).
    """
    leaked = forward_returns(df, horizon=horizon, price_col=price_col, out_col=_LEAK_FORWARD_COL)
    return leaked.with_columns(
        pl.col(_LEAK_FORWARD_COL).sign().fill_null(0.0).cast(pl.Float64).alias(weight_col)
    ).drop(_LEAK_FORWARD_COL)


# --------------------------------------------------------------------------------------------
# Battery
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NullModelResult:
    """Key metrics for one variant in the battery."""

    name: str
    sharpe: float
    sortino: float
    total_return: float
    max_drawdown: float
    annual_turnover: float
    n_periods: int
    seed: int | None = None


@dataclass(frozen=True)
class NullBatteryReport:
    """All variants + advisory diagnostics. Diagnostics gate nothing; the human decides."""

    baseline: NullModelResult
    random_weights: NullModelResult
    shuffled_weights: NullModelResult
    shifted_weights: NullModelResult
    future_leak: NullModelResult
    cost_stress_2x: NullModelResult
    cost_stress_5x: NullModelResult
    future_leak_detected: bool
    random_near_zero: bool
    shuffled_near_zero: bool
    seed: int

    def as_dict(self) -> dict:
        return asdict(self)


def _result(name: str, res: BacktestResult, *, seed: int | None = None) -> NullModelResult:
    m = res.metrics
    return NullModelResult(
        name=name,
        sharpe=m.sharpe,
        sortino=m.sortino,
        total_return=m.total_return,
        max_drawdown=m.max_drawdown,
        annual_turnover=m.annual_turnover,
        n_periods=m.n_periods,
        seed=seed,
    )


def run_null_battery(
    df: pl.DataFrame,
    *,
    base_weight_col: str = "weight",
    horizon: int = 1,
    seed: int = 12345,
    costs_path: str = "configs/costs.yaml",
    periods_per_year: int = 252,
    noise_sharpe_threshold: float = 0.5,
    leak_min_sharpe: float = 3.0,
) -> NullBatteryReport:
    """Run the full null-model battery against caller-provided baseline weights.

    Baseline and the noise/leak variants run at base cost; cost stress reruns the BASELINE
    weights at slippage x2 and x5. Returns a report with advisory diagnostics only.
    """
    if horizon < 1:
        raise NullBatteryError("horizon must be at least 1")
    required = (SYMBOL_COL, TIMESTAMP_COL, PRICE_COL, base_weight_col)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise NullBatteryError(f"battery input is missing required columns: {', '.join(missing)}")

    base_cost = load_cost_model(costs_path, stress="none")
    cost_2x = load_cost_model(costs_path, stress="2x")
    cost_5x = load_cost_model(costs_path, stress="5x")

    random_seed = seed
    shuffled_seed = seed + 1

    def _bt(frame: pl.DataFrame, cost_model: CostModel) -> BacktestResult:
        return run_backtest(
            frame,
            weight_col=base_weight_col,
            horizon=horizon,
            cost_model=cost_model,
            periods_per_year=periods_per_year,
        )

    baseline = _result("baseline", _bt(df, base_cost))
    random_res = _result(
        "random_weights",
        _bt(random_weights(df, seed=random_seed, weight_col=base_weight_col), base_cost),
        seed=random_seed,
    )
    shuffled_res = _result(
        "shuffled_weights",
        _bt(shuffled_weights(df, seed=shuffled_seed, weight_col=base_weight_col), base_cost),
        seed=shuffled_seed,
    )
    shifted_res = _result(
        "shifted_weights",
        _bt(shifted_weights(df, weight_col=base_weight_col), base_cost),
    )
    leak_res = _result(
        "future_leak",
        _bt(future_leak_weights(df, horizon=horizon, weight_col=base_weight_col), base_cost),
    )
    stress_2x = _result("cost_stress_2x", _bt(df, cost_2x))
    stress_5x = _result("cost_stress_5x", _bt(df, cost_5x))

    return NullBatteryReport(
        baseline=baseline,
        random_weights=random_res,
        shuffled_weights=shuffled_res,
        shifted_weights=shifted_res,
        future_leak=leak_res,
        cost_stress_2x=stress_2x,
        cost_stress_5x=stress_5x,
        future_leak_detected=(
            leak_res.sharpe >= leak_min_sharpe and leak_res.sharpe > baseline.sharpe
        ),
        random_near_zero=abs(random_res.sharpe) <= noise_sharpe_threshold,
        shuffled_near_zero=abs(shuffled_res.sharpe) <= noise_sharpe_threshold,
        seed=seed,
    )
