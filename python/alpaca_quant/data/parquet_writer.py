"""Local Parquet output for already-parsed historical bars."""

from collections.abc import Iterable
from pathlib import Path

import polars as pl

from alpaca_quant.data.alpaca_bars import Bar

BAR_COLUMNS = [
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trade_count",
    "vwap",
]


class ParquetWriteError(RuntimeError):
    """Raised when parsed bars cannot be safely written to Parquet."""


def bars_to_dataframe(bars: Iterable[Bar]) -> pl.DataFrame:
    """Convert parsed bars to a Polars DataFrame with a stable column order."""
    materialized = list(bars)
    if not materialized:
        raise ParquetWriteError("cannot create Parquet data from an empty bars collection")

    rows = [
        {
            "symbol": bar.symbol.upper(),
            "timestamp": bar.timestamp,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "trade_count": bar.trade_count,
            "vwap": bar.vwap,
        }
        for bar in materialized
    ]
    return pl.DataFrame(rows).select(BAR_COLUMNS)


def write_bars_parquet(
    bars: Iterable[Bar],
    output_path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write parsed bars to Parquet, refusing replacement unless explicitly allowed."""
    path = Path(output_path)
    if path.exists() and not overwrite:
        raise ParquetWriteError(f"output file already exists: {path}")

    dataframe = bars_to_dataframe(bars)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        dataframe.write_parquet(path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise ParquetWriteError(f"failed to write Parquet file: {path}") from exc

    return path
