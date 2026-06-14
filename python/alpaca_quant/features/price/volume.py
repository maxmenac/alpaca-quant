"""Volume features. Grouped by symbol, sorted by timestamp, no lookahead."""

import polars as pl


def rolling_volume(df: pl.DataFrame, window: int = 20) -> pl.DataFrame:
    """Add `rolling_vol_volume_{window}d` column: rolling mean of volume, per symbol.

    Early rows (< window) will contain null.
    """
    if window < 1:
        raise ValueError("window must be at least 1")
    col_name = f"rolling_vol_volume_{window}d"
    return (
        df.sort(["symbol", "timestamp"])
        .with_columns(
            pl.col("volume")
            .cast(pl.Float64)
            .rolling_mean(window_size=window, min_samples=window)
            .over("symbol")
            .alias(col_name)
        )
    )
