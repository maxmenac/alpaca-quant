"""Daily and log return features. Grouped by symbol, sorted by timestamp, no lookahead."""

import polars as pl


def daily_returns(df: pl.DataFrame) -> pl.DataFrame:
    """Add `daily_return` column: simple pct change of close, per symbol."""
    return (
        df.sort(["symbol", "timestamp"])
        .with_columns(
            pl.col("close")
            .pct_change()
            .over("symbol")
            .alias("daily_return")
        )
    )


def log_returns(df: pl.DataFrame) -> pl.DataFrame:
    """Add `log_return` column: log(close / close_prev), per symbol."""
    return (
        df.sort(["symbol", "timestamp"])
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("symbol"))
            .log(base=2.718281828459045)
            .alias("log_return")
        )
    )
