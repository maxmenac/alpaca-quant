"""Point-in-time (as-of) read layer for local bars.

ARCHITECTURE.md P2 / §3.1: this module materializes the point-in-time guarantee. Features must
read bars *through here*, never from raw Parquet directly, so no row dated after the declared
`as_of` knowledge cutoff can ever enter a feature computation.

Local Parquet only. No network. No Alpaca API calls. No .env reads. No labels, targets,
signals, alpha, model training, backtesting, or trading.
"""

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import polars as pl

from alpaca_quant.data.duckdb_query import DuckDBQueryError, query_bars
from alpaca_quant.data.parquet_writer import BAR_COLUMNS

REQUIRED_BARS_COLUMNS: tuple[str, ...] = tuple(BAR_COLUMNS)
JOIN_KEYS: tuple[str, ...] = ("symbol", "timestamp")


class PITReadError(RuntimeError):
    """Raised when a point-in-time bar read is invalid or violates the as-of cutoff."""


def _normalize_as_of(value: str | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise PITReadError("as_of must be an ISO date string or date object") from exc


def assert_no_lookahead(df: pl.DataFrame, as_of: str | date) -> None:
    """Raise PITReadError if any row in `df` is dated after `as_of`.

    Reusable hard gate for any consumer (PIT reader now, backtester later): a frame that passes
    this check contains no information from after the declared knowledge cutoff.
    """
    if "timestamp" not in df.columns:
        raise PITReadError("cannot check lookahead: frame has no 'timestamp' column")
    as_of_date = _normalize_as_of(as_of)
    future = df.filter(pl.col("timestamp").dt.date() > as_of_date)
    if not future.is_empty():
        raise PITReadError(
            f"lookahead violation: {len(future)} row(s) dated after as_of={as_of_date.isoformat()}"
        )


def load_pit_bars(
    bars_path: str | Path,
    *,
    as_of: str | date,
    symbols: Sequence[str] | None = None,
    start: str | date | None = None,
) -> pl.DataFrame:
    """Read local bars as known at `as_of`, guaranteeing zero lookahead.

    - `as_of` is required (keyword-only): the inclusive knowledge cutoff. No row dated after it
      is ever returned.
    - Reads local Parquet only (via the DuckDB query layer). No network, no Alpaca API.
    - Optional `symbols` filter and `start` lower bound compose with the cutoff.
    - Returns a Polars DataFrame sorted by (symbol, timestamp).
    """
    as_of_date = _normalize_as_of(as_of)
    start_date: date | None = None
    if start is not None:
        start_date = _normalize_as_of(start)
        if start_date > as_of_date:
            raise PITReadError("start date must be on or before as_of")

    try:
        bars = query_bars(
            bars_path,
            symbols=symbols,
            start=start_date,
            end=as_of_date,
            columns=REQUIRED_BARS_COLUMNS,
        )
    except DuckDBQueryError as exc:
        raise PITReadError(f"failed to read PIT bars: {exc}") from exc

    if bars.is_empty():
        raise PITReadError(
            f"no bars found for PIT query (as_of={as_of_date.isoformat()}, symbols={symbols})"
        )

    missing = [c for c in REQUIRED_BARS_COLUMNS if c not in bars.columns]
    if missing:
        raise PITReadError(f"PIT bars missing required columns: {', '.join(missing)}")

    if bars.select(JOIN_KEYS).is_duplicated().any():
        raise PITReadError("PIT bars contain duplicate symbol/timestamp rows")

    bars = bars.sort(list(JOIN_KEYS))
    assert_no_lookahead(bars, as_of_date)
    return bars
