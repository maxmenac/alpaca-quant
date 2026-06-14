"""Tests for local Parquet output of parsed bars."""

from datetime import UTC, datetime

import polars as pl
import pytest

from alpaca_quant.data.alpaca_bars import Bar
from alpaca_quant.data.parquet_writer import (
    BAR_COLUMNS,
    ParquetWriteError,
    bars_to_dataframe,
    write_bars_parquet,
)


def make_bar(
    symbol: str,
    timestamp: datetime,
    *,
    close: float = 1.5,
) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=1.0,
        high=2.0,
        low=0.5,
        close=close,
        volume=1000,
        trade_count=10,
        vwap=1.2,
    )


@pytest.fixture
def bars() -> list[Bar]:
    return [
        make_bar("aapl", datetime(2024, 1, 2, 5, tzinfo=UTC)),
        make_bar("MSFT", datetime(2024, 1, 3, 5, tzinfo=UTC), close=2.5),
    ]


def test_converts_two_bars_to_dataframe(bars):
    dataframe = bars_to_dataframe(bars)

    assert dataframe.shape == (2, 9)
    assert dataframe.columns == BAR_COLUMNS
    assert dataframe["symbol"].to_list() == ["AAPL", "MSFT"]
    assert dataframe["timestamp"].to_list() == [bar.timestamp for bar in bars]


def test_writes_and_reads_parquet(tmp_path, bars):
    output_path = tmp_path / "bars.parquet"

    written_path = write_bars_parquet(bars, output_path)
    restored = pl.read_parquet(written_path)

    assert written_path == output_path
    assert restored.shape == (2, 9)
    assert restored.columns == BAR_COLUMNS
    assert restored["symbol"].to_list() == ["AAPL", "MSFT"]
    assert restored["timestamp"].to_list() == [bar.timestamp for bar in bars]


def test_empty_bars_rejected(tmp_path):
    with pytest.raises(ParquetWriteError, match="empty bars"):
        write_bars_parquet([], tmp_path / "bars.parquet")


def test_parent_directory_created_automatically(tmp_path, bars):
    output_path = tmp_path / "nested" / "daily" / "bars.parquet"

    write_bars_parquet(bars, output_path)

    assert output_path.is_file()


def test_overwrite_false_rejects_existing_file(tmp_path, bars):
    output_path = tmp_path / "bars.parquet"
    write_bars_parquet(bars, output_path)

    with pytest.raises(ParquetWriteError, match="already exists"):
        write_bars_parquet(bars, output_path)


def test_overwrite_true_replaces_existing_file(tmp_path, bars):
    output_path = tmp_path / "bars.parquet"
    write_bars_parquet(bars, output_path)

    replacement = [make_bar("NVDA", datetime(2024, 1, 4, 5, tzinfo=UTC))]
    write_bars_parquet(replacement, output_path, overwrite=True)

    restored = pl.read_parquet(output_path)
    assert restored.shape == (1, 9)
    assert restored["symbol"].to_list() == ["NVDA"]
