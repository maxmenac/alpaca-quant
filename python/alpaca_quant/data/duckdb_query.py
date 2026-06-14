"""Read-only DuckDB helpers for local Parquet bar files."""

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from alpaca_quant.data.parquet_writer import BAR_COLUMNS

ALLOWED_COLUMNS = frozenset(BAR_COLUMNS)


class DuckDBQueryError(RuntimeError):
    """Raised when a local Parquet query is invalid or cannot be completed."""


def query_bars(
    parquet_path: str | Path,
    symbols: Sequence[str] | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Query bars from one local Parquet file into a Polars DataFrame."""
    path = _validated_path(parquet_path)
    selected_columns = _validated_columns(columns)
    normalized_symbols = _normalized_symbols(symbols)
    start_date = _normalized_date(start, "start")
    end_date = _normalized_date(end, "end")
    if start_date is not None and end_date is not None and end_date < start_date:
        raise DuckDBQueryError("end date must be on or after start date")

    predicates: list[str] = []
    parameters: list[object] = [str(path)]

    if normalized_symbols is not None:
        placeholders = ", ".join("?" for _ in normalized_symbols)
        predicates.append(f"symbol IN ({placeholders})")
        parameters.extend(normalized_symbols)
    if start_date is not None:
        predicates.append("CAST(timestamp AS DATE) >= ?")
        parameters.append(start_date)
    if end_date is not None:
        predicates.append("CAST(timestamp AS DATE) <= ?")
        parameters.append(end_date)

    where_clause = f" WHERE {' AND '.join(predicates)}" if predicates else ""
    column_sql = ", ".join(selected_columns)
    sql = (
        f"SELECT {column_sql} FROM read_parquet(?)"
        f"{where_clause} ORDER BY timestamp, symbol"
    )
    return _execute_polars(sql, parameters)


def count_bars(parquet_path: str | Path) -> int:
    """Return the number of bars in one local Parquet file."""
    path = _validated_path(parquet_path)
    dataframe = _execute_polars(
        "SELECT COUNT(*) AS bar_count FROM read_parquet(?)",
        [str(path)],
    )
    return int(dataframe.item(0, "bar_count"))


def available_symbols(parquet_path: str | Path) -> list[str]:
    """Return sorted unique symbols from one local Parquet file."""
    path = _validated_path(parquet_path)
    dataframe = _execute_polars(
        "SELECT DISTINCT symbol FROM read_parquet(?) ORDER BY symbol",
        [str(path)],
    )
    return dataframe["symbol"].to_list()


def _validated_path(parquet_path: str | Path) -> Path:
    path = Path(parquet_path)
    if not path.is_file():
        raise DuckDBQueryError(f"Parquet file does not exist: {path}")
    return path


def _validated_columns(columns: Sequence[str] | None) -> list[str]:
    if columns is None:
        return list(BAR_COLUMNS)
    if not columns:
        raise DuckDBQueryError("columns must contain at least one column")

    unknown = [column for column in columns if column not in ALLOWED_COLUMNS]
    if unknown:
        raise DuckDBQueryError(f"unknown bar columns: {', '.join(unknown)}")
    return list(columns)


def _normalized_symbols(symbols: Sequence[str] | None) -> tuple[str, ...] | None:
    if symbols is None:
        return None
    if isinstance(symbols, str):
        symbols = [symbols]

    normalized = tuple(symbol.strip().upper() for symbol in symbols if symbol.strip())
    if not normalized:
        raise DuckDBQueryError("symbols must contain at least one symbol")
    return normalized


def _normalized_date(value: str | date | None, field_name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise DuckDBQueryError(f"{field_name} must be an ISO date or date object") from exc


def _execute_polars(sql: str, parameters: list[object]) -> pl.DataFrame:
    connection = duckdb.connect(database=":memory:")
    try:
        return connection.execute(sql, parameters).pl()
    except duckdb.Error as exc:
        raise DuckDBQueryError("DuckDB failed to query the Parquet file") from exc
    finally:
        connection.close()
