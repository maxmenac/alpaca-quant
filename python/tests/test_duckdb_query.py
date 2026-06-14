"""Tests for read-only DuckDB queries over local bar Parquet files."""

from datetime import UTC, date, datetime

import pytest

from alpaca_quant.data.alpaca_bars import Bar
from alpaca_quant.data.duckdb_query import (
    DuckDBQueryError,
    available_symbols,
    count_bars,
    query_bars,
)
from alpaca_quant.data.parquet_writer import BAR_COLUMNS, write_bars_parquet


def make_bar(symbol: str, day: int, close: float) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2024, 1, day, 5, tzinfo=UTC),
        open=close - 0.5,
        high=close + 0.5,
        low=close - 1.0,
        close=close,
        volume=1000 * day,
        trade_count=10 * day,
        vwap=close - 0.1,
    )


@pytest.fixture
def parquet_path(tmp_path):
    path = tmp_path / "bars.parquet"
    write_bars_parquet(
        [
            make_bar("AAPL", 2, 10.0),
            make_bar("MSFT", 2, 20.0),
            make_bar("AAPL", 3, 11.0),
            make_bar("NVDA", 4, 30.0),
        ],
        path,
    )
    return path


def test_count_bars(parquet_path):
    assert count_bars(parquet_path) == 4


def test_available_symbols(parquet_path):
    assert available_symbols(parquet_path) == ["AAPL", "MSFT", "NVDA"]


def test_query_all_rows(parquet_path):
    dataframe = query_bars(parquet_path)

    assert dataframe.shape == (4, 9)
    assert dataframe.columns == BAR_COLUMNS


def test_query_by_one_symbol(parquet_path):
    dataframe = query_bars(parquet_path, symbols=["aapl"])

    assert dataframe.shape[0] == 2
    assert dataframe["symbol"].unique().to_list() == ["AAPL"]


def test_query_by_multiple_symbols(parquet_path):
    dataframe = query_bars(parquet_path, symbols=["msft", "NVDA"])

    assert dataframe["symbol"].to_list() == ["MSFT", "NVDA"]


def test_query_by_inclusive_date_range(parquet_path):
    dataframe = query_bars(
        parquet_path,
        start=date(2024, 1, 2),
        end="2024-01-03",
    )

    assert dataframe.shape[0] == 3
    assert dataframe["timestamp"].dt.date().to_list() == [
        date(2024, 1, 2),
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]


def test_query_selected_columns(parquet_path):
    dataframe = query_bars(parquet_path, columns=["symbol", "close"])

    assert dataframe.columns == ["symbol", "close"]
    assert dataframe.shape == (4, 2)


def test_unknown_column_rejected(parquet_path):
    with pytest.raises(DuckDBQueryError, match="unknown bar columns: secret"):
        query_bars(parquet_path, columns=["symbol", "secret"])


def test_missing_parquet_file_rejected(tmp_path):
    with pytest.raises(DuckDBQueryError, match="does not exist"):
        query_bars(tmp_path / "missing.parquet")


def test_invalid_date_range_rejected(parquet_path):
    with pytest.raises(DuckDBQueryError, match="end date"):
        query_bars(parquet_path, start="2024-01-04", end="2024-01-02")
