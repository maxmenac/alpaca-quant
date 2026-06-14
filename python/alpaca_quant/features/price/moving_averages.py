"""Moving average features. Grouped by symbol, sorted by timestamp, no lookahead."""

import polars as pl


def sma(df: pl.DataFrame, window: int) -> pl.DataFrame:
    """Add `sma_{window}d` column: simple moving average of close, per symbol.

    Early rows (< window) will contain null.
    """
    if window < 1:
        raise ValueError("window must be at least 1")
    col_name = f"sma_{window}d"
    return (
        df.sort(["symbol", "timestamp"])
        .with_columns(
            pl.col("close")
            .rolling_mean(window_size=window, min_samples=window)
            .over("symbol")
            .alias(col_name)
        )
    )


def ema(df: pl.DataFrame, window: int) -> pl.DataFrame:
    """Add `ema_{window}d` column: exponential moving average of close, per symbol.

    Uses Polars ewm_mean with span=window. min_periods=window so early rows are null.
    """
    if window < 1:
        raise ValueError("window must be at least 1")
    col_name = f"ema_{window}d"
    return (
        df.sort(["symbol", "timestamp"])
        .with_columns(
            pl.col("close")
            .ewm_mean(span=window, min_samples=window)
            .over("symbol")
            .alias(col_name)
        )
    )
