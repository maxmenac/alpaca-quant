"""Realized volatility features. Grouped by symbol, sorted by timestamp, no lookahead."""

import math

import polars as pl

ANNUALIZATION_FACTOR = math.sqrt(252)


def rolling_volatility(df: pl.DataFrame, window: int = 20) -> pl.DataFrame:
    """Add `rolling_vol_{window}d` column: annualized realized vol of log returns, per symbol.

    Requires log_return column. Early rows (< window) will contain null.
    """
    if window < 2:
        raise ValueError("window must be at least 2")
    if "log_return" not in df.columns:
        raise ValueError("rolling_volatility requires log_return column; call log_returns first")

    col_name = f"rolling_vol_{window}d"
    return (
        df.sort(["symbol", "timestamp"])
        .with_columns(
            (
                pl.col("log_return")
                .rolling_std(window_size=window, min_samples=window)
                .over("symbol")
                * ANNUALIZATION_FACTOR
            ).alias(col_name)
        )
    )
