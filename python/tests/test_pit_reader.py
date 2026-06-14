"""Tests for the point-in-time bar read layer. tmp_path synthetic Parquet only — no .env, no net."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from alpaca_quant.data.pit.reader import (
    PITReadError,
    assert_no_lookahead,
    load_pit_bars,
)


def _bars_df(symbol: str = "AAPL", n_rows: int = 6) -> pl.DataFrame:
    closes = [100.0 + i for i in range(n_rows)]
    return pl.DataFrame(
        {
            "symbol": [symbol] * n_rows,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n_rows)],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i for i in range(n_rows)],
            "trade_count": [500 + i for i in range(n_rows)],
            "vwap": closes,
        }
    )


def _write(df: pl.DataFrame, path: Path) -> Path:
    df.write_parquet(path)
    return path


class TestLoadPitBars:
    def test_no_rows_after_as_of(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        df = load_pit_bars(bars, as_of="2024-01-04")
        assert df["timestamp"].dt.date().max() == date(2024, 1, 4)
        assert df.filter(pl.col("timestamp").dt.date() > date(2024, 1, 4)).is_empty()
        assert len(df) == 3

    def test_as_of_inclusive(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        df = load_pit_bars(bars, as_of="2024-01-07")
        assert df["timestamp"].dt.date().max() == date(2024, 1, 7)
        assert len(df) == 6

    def test_as_of_accepts_date_object(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        df = load_pit_bars(bars, as_of=date(2024, 1, 3))
        assert df["timestamp"].dt.date().max() == date(2024, 1, 3)

    def test_as_of_is_keyword_only(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        with pytest.raises(TypeError):
            load_pit_bars(bars, "2024-01-04")  # type: ignore[misc]

    def test_as_of_required(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        with pytest.raises(TypeError):
            load_pit_bars(bars)  # type: ignore[call-arg]

    def test_symbol_filter(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        df = load_pit_bars(bars, as_of="2024-01-07", symbols=["AAPL"])
        assert df["symbol"].unique().to_list() == ["AAPL"]

    def test_multi_symbol(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        df = load_pit_bars(bars, as_of="2024-01-07")
        assert sorted(df["symbol"].unique().to_list()) == ["AAPL", "MSFT"]

    def test_start_composes_with_as_of(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        df = load_pit_bars(bars, as_of="2024-01-06", start="2024-01-04")
        dates = df["timestamp"].dt.date().unique().sort().to_list()
        assert str(dates[0]) == "2024-01-04"
        assert str(dates[-1]) == "2024-01-06"

    def test_start_after_as_of_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        with pytest.raises(PITReadError, match="start date must be on or before as_of"):
            load_pit_bars(bars, as_of="2024-01-03", start="2024-01-05")

    def test_missing_file_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PITReadError, match="failed to read PIT bars"):
            load_pit_bars(tmp_path / "nope.parquet", as_of="2024-01-04")

    def test_empty_after_cutoff_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        with pytest.raises(PITReadError, match="no bars found for PIT query"):
            load_pit_bars(bars, as_of="2023-12-31")

    def test_duplicate_keys_rejected(self, tmp_path: Path) -> None:
        dup = pl.concat([_bars_df(n_rows=3), _bars_df(n_rows=3)])
        bars = _write(dup, tmp_path / "bars.parquet")
        with pytest.raises(PITReadError, match="duplicate symbol/timestamp"):
            load_pit_bars(bars, as_of="2024-01-07")

    def test_sorted_by_symbol_timestamp(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("MSFT"), _bars_df("AAPL")]), tmp_path / "bars.parquet"
        )
        df = load_pit_bars(bars, as_of="2024-01-07")
        keys = list(zip(df["symbol"].to_list(), df["timestamp"].to_list(), strict=True))
        assert keys == sorted(keys, key=lambda k: (k[0], k[1]))

    def test_bad_as_of_format_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        with pytest.raises(PITReadError, match="as_of must be an ISO date"):
            load_pit_bars(bars, as_of="not-a-date")


class TestAssertNoLookahead:
    def test_passes_on_clean_frame(self) -> None:
        assert_no_lookahead(_bars_df(n_rows=3), "2024-01-10")  # no raise

    def test_raises_on_future_rows(self) -> None:
        with pytest.raises(PITReadError, match="lookahead violation"):
            assert_no_lookahead(_bars_df(n_rows=6), "2024-01-04")

    def test_reports_violation_count(self) -> None:
        with pytest.raises(PITReadError, match="3 row"):
            assert_no_lookahead(_bars_df(n_rows=6), "2024-01-04")

    def test_accepts_date_object(self) -> None:
        assert_no_lookahead(_bars_df(n_rows=3), date(2024, 1, 10))  # no raise

    def test_missing_timestamp_column_rejected(self) -> None:
        df = pl.DataFrame({"symbol": ["AAPL"]})
        with pytest.raises(PITReadError, match="no 'timestamp' column"):
            assert_no_lookahead(df, "2024-01-04")
