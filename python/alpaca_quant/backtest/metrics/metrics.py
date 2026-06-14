"""Honest backtest metrics: Sharpe, Sortino, max drawdown, turnover, return, CAGR.

Deterministic, dependency-light (Polars + stdlib math). Daily annualization (252). Sharpe and
Sortino return 0.0 when variance / downside variance is zero (avoids division by zero).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt

import polars as pl

DEFAULT_PERIODS_PER_YEAR = 252


@dataclass(frozen=True)
class BacktestMetrics:
    """Non-secret summary statistics for one backtest run."""

    sharpe: float
    sortino: float
    max_drawdown: float
    annual_turnover: float
    total_return: float
    cagr: float
    n_periods: int


def equity_curve(net_returns: Sequence[float]) -> list[float]:
    """Cumulative wealth relative to a starting capital of 1.0."""
    equity: list[float] = []
    acc = 1.0
    for r in net_returns:
        acc *= 1.0 + r
        equity.append(acc)
    return equity


def _max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough decline as a non-positive fraction (e.g. -0.14)."""
    peak = float("-inf")
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def compute_metrics(
    net_returns: Sequence[float],
    turnover: Sequence[float],
    *,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> BacktestMetrics:
    """Compute deterministic metrics from per-period net returns and turnover."""
    n = len(net_returns)
    if n == 0:
        raise ValueError("cannot compute metrics on an empty return series")

    returns = pl.Series("net", net_returns, dtype=pl.Float64)
    mean = float(returns.mean() or 0.0)
    std = returns.std()  # sample std (ddof=1); None when n < 2
    annual = sqrt(periods_per_year)

    sharpe = float(mean / std * annual) if std not in (None, 0.0) and std and std > 0 else 0.0

    negatives = returns.filter(returns < 0)
    if negatives.len() > 0:
        downside_dev = sqrt(float((negatives**2).sum()) / n)
    else:
        downside_dev = 0.0
    sortino = float(mean / downside_dev * annual) if downside_dev > 0 else 0.0

    equity = equity_curve(net_returns)
    max_dd = _max_drawdown(equity)
    total_return = equity[-1] - 1.0
    growth = 1.0 + total_return
    cagr = growth ** (periods_per_year / n) - 1.0 if growth > 0 else -1.0

    turnover_series = pl.Series("turnover", turnover, dtype=pl.Float64)
    annual_turnover = float(turnover_series.mean() or 0.0) * periods_per_year

    return BacktestMetrics(
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        annual_turnover=annual_turnover,
        total_return=total_return,
        cagr=cagr,
        n_periods=n,
    )
