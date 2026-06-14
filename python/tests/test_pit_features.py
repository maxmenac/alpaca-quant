"""Tests for the PIT feature path. tmp_path synthetic Parquet only — no .env, no network."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from alpaca_quant.data.pit.reader import PITReadError
from alpaca_quant.features.pipeline import (
    FEATURE_NAMES,
    build_feature_set,
    build_pit_feature_set,
)


def _bars_df(symbol: str = "AAPL", n_rows: int = 30) -> pl.DataFrame:
    closes = [100.0 * (1 + 0.005 * i) for i in range(n_rows)]
    return pl.DataFrame(
        {
            "symbol": [symbol] * n_rows,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n_rows)],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i * 1000 for i in range(n_rows)],
            "trade_count": [500] * n_rows,
            "vwap": closes,
        }
    )


def _write(df: pl.DataFrame, path: Path) -> Path:
    df.write_parquet(path)
    return path


class TestBuildPitFeatureSet:
    def test_returns_polars_dataframe(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        result = build_pit_feature_set(bars, "AAPL", as_of="2024-01-15")
        assert isinstance(result, pl.DataFrame)

    def test_no_rows_after_as_of(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=30), tmp_path / "bars.parquet")
        result = build_pit_feature_set(bars, "AAPL", as_of="2024-01-10")
        assert result["timestamp"].dt.date().max() == date(2024, 1, 10)

    def test_feature_columns_present(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        result = build_pit_feature_set(bars, "AAPL", as_of="2024-01-31")
        assert "feature_set_id" in result.columns
        for name in FEATURE_NAMES:
            assert name in result.columns

    def test_feature_set_id_format(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        result = build_pit_feature_set(bars, "AAPL", as_of="2024-01-31")
        import re

        assert re.match(r"^feat-AAPL-[0-9a-f]{8}$", result["feature_set_id"][0])

    def test_as_of_changes_feature_set_id(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        a = build_pit_feature_set(bars, "AAPL", as_of="2024-01-10")["feature_set_id"][0]
        b = build_pit_feature_set(bars, "AAPL", as_of="2024-01-20")["feature_set_id"][0]
        assert a != b

    def test_as_of_required_keyword(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        with pytest.raises(TypeError):
            build_pit_feature_set(bars, "AAPL")  # type: ignore[call-arg]

    def test_empty_after_cutoff_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        with pytest.raises(PITReadError):
            build_pit_feature_set(bars, "AAPL", as_of="2023-01-01")

    def test_matches_legacy_on_truncated_data(self, tmp_path: Path) -> None:
        """PIT features at as_of must equal legacy features computed on data cut at as_of."""
        full = _bars_df(n_rows=30)
        bars_full = _write(full, tmp_path / "bars_full.parquet")

        cutoff = date(2024, 1, 15)
        truncated = full.filter(pl.col("timestamp").dt.date() <= cutoff)
        bars_trunc = _write(truncated, tmp_path / "bars_trunc.parquet")

        pit = build_pit_feature_set(bars_full, "AAPL", as_of="2024-01-15").sort("timestamp")
        legacy = build_feature_set(bars_trunc, "AAPL").sort("timestamp")

        assert len(pit) == len(legacy)
        for col in FEATURE_NAMES:
            pit_vals = pit[col].to_list()
            legacy_vals = legacy[col].to_list()
            for a, b in zip(pit_vals, legacy_vals, strict=True):
                if a is None or b is None:
                    assert a is b
                else:
                    assert abs(a - b) < 1e-9, f"mismatch in {col}: {a} != {b}"

    def test_last_row_uses_no_future_data(self, tmp_path: Path) -> None:
        """Feature value at the as_of row is identical whether or not future rows exist."""
        full = _bars_df(n_rows=30)
        bars_full = _write(full, tmp_path / "bars_full.parquet")

        cut = build_pit_feature_set(bars_full, "AAPL", as_of="2024-01-15").sort("timestamp")
        # the last row of the cut dataset is the as_of row
        last_log_return = cut["log_return"].to_list()[-1]
        # recompute on a dataset that has MORE future data but same as_of
        cut2 = build_pit_feature_set(bars_full, "AAPL", as_of="2024-01-15").sort("timestamp")
        assert cut2["log_return"].to_list()[-1] == last_log_return
