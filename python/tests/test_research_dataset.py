"""Tests for the research dataset loader. All fixtures use tmp_path — no data/runs/, no .env."""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from alpaca_quant.features.pipeline import FEATURE_NAMES
from alpaca_quant.research.dataset import (
    FORBIDDEN_COLUMNS,
    ResearchDatasetError,
    ResearchDatasetSummary,
    load_research_dataset,
    summarize_research_dataset,
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


def _features_df(symbol: str = "AAPL", n_rows: int = 6) -> pl.DataFrame:
    """Mirror what build_feature_set emits: bar columns + features + feature_set_id."""
    base = _bars_df(symbol, n_rows)
    feature_cols = {
        name: [None] + [0.01 * (i + 1) for i in range(n_rows - 1)] for name in FEATURE_NAMES
    }
    additions = [pl.Series(name, vals) for name, vals in feature_cols.items()]
    additions.append(pl.lit(f"feat-{symbol}-deadbeef").alias("feature_set_id"))
    return base.with_columns(additions)


def _write(df: pl.DataFrame, path: Path) -> Path:
    df.write_parquet(path)
    return path


class TestLoadValid:
    def test_load_valid_bars_and_features(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")

        df = load_research_dataset(bars, feats)
        assert isinstance(df, pl.DataFrame)
        assert len(df) == 6
        # join keys present
        assert "symbol" in df.columns
        assert "timestamp" in df.columns
        # bar columns present
        assert "close" in df.columns
        # feature provenance + feature columns present
        assert "feature_set_id" in df.columns
        for name in FEATURE_NAMES:
            assert name in df.columns

    def test_no_duplicated_ohlcv_columns(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")

        df = load_research_dataset(bars, feats)
        # join must not produce close_right / open_right duplicates
        assert not any(c.endswith("_right") for c in df.columns)

    def test_result_sorted_by_keys(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")

        df = load_research_dataset(bars, feats)
        ts = df["timestamp"].to_list()
        assert ts == sorted(ts)


class TestFilters:
    def test_date_range_filter(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        feats = _write(_features_df(n_rows=6), tmp_path / "features.parquet")

        df = load_research_dataset(bars, feats, start="2024-01-03", end="2024-01-05")
        dates = df["timestamp"].dt.date().unique().sort().to_list()
        assert str(dates[0]) == "2024-01-03"
        assert str(dates[-1]) == "2024-01-05"
        assert len(df) == 3

    def test_symbol_filter(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        feats = _write(
            pl.concat([_features_df("AAPL"), _features_df("MSFT")]),
            tmp_path / "features.parquet",
        )

        df = load_research_dataset(bars, feats, symbol="AAPL")
        assert df["symbol"].unique().to_list() == ["AAPL"]

    def test_symbol_filter_case_insensitive(self, tmp_path: Path) -> None:
        bars = _write(_bars_df("AAPL"), tmp_path / "bars.parquet")
        feats = _write(_features_df("AAPL"), tmp_path / "features.parquet")

        df = load_research_dataset(bars, feats, symbol="aapl")
        assert df["symbol"].unique().to_list() == ["AAPL"]

    def test_end_before_start_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")

        with pytest.raises(ResearchDatasetError, match="end date must be on or after"):
            load_research_dataset(bars, feats, start="2024-01-05", end="2024-01-03")


class TestValidation:
    def test_missing_bars_file(self, tmp_path: Path) -> None:
        feats = _write(_features_df(), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="bars Parquet file not found"):
            load_research_dataset(tmp_path / "nope.parquet", feats)

    def test_missing_features_file(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        with pytest.raises(ResearchDatasetError, match="features Parquet file not found"):
            load_research_dataset(bars, tmp_path / "nope.parquet")

    def test_empty_bars_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df().head(0), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="bars dataset is empty"):
            load_research_dataset(bars, feats)

    def test_empty_features_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df().head(0), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="features dataset is empty"):
            load_research_dataset(bars, feats)

    def test_missing_required_bars_column(self, tmp_path: Path) -> None:
        bars = _write(_bars_df().drop("vwap"), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="bars is missing required columns"):
            load_research_dataset(bars, feats)

    def test_missing_required_feature_column(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df().drop("feature_set_id"), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="features is missing required columns"):
            load_research_dataset(bars, feats)

    def test_duplicate_bars_keys_rejected(self, tmp_path: Path) -> None:
        dup = pl.concat([_bars_df(n_rows=3), _bars_df(n_rows=3)])
        bars = _write(dup, tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="bars contains duplicate"):
            load_research_dataset(bars, feats)

    def test_duplicate_feature_keys_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        dup = pl.concat([_features_df(n_rows=3), _features_df(n_rows=3)])
        feats = _write(dup, tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="features contains duplicate"):
            load_research_dataset(bars, feats)

    def test_mismatched_symbols_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df("AAPL"), tmp_path / "bars.parquet")
        feats = _write(_features_df("MSFT"), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="no overlapping symbols"):
            load_research_dataset(bars, feats)

    def test_symbol_filter_absent_in_bars_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df("AAPL"), tmp_path / "bars.parquet")
        feats = _write(_features_df("AAPL"), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match=r"bars dataset has no rows for symbol"):
            load_research_dataset(bars, feats, symbol="TSLA")


class TestNoForbiddenConcepts:
    def test_no_target_signal_order_trade_columns(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")

        df = load_research_dataset(bars, feats)
        for col in df.columns:
            assert col not in FORBIDDEN_COLUMNS, f"forbidden column created: {col}"

    def test_forbidden_column_in_input_is_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        # inject a forbidden 'signal' column into the features frame
        feats_df = _features_df().with_columns(pl.lit(1.0).alias("signal"))
        feats = _write(feats_df, tmp_path / "features.parquet")

        # 'signal' is not in FEATURE_NAMES so it is dropped by the slim select;
        # the dataset must remain clean.
        df = load_research_dataset(bars, feats)
        assert "signal" not in df.columns

    def test_trade_count_is_allowed(self, tmp_path: Path) -> None:
        # 'trade_count' contains 'trade' but is a legitimate bar column
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")

        df = load_research_dataset(bars, feats)
        assert "trade_count" in df.columns


class TestSummary:
    def test_summary_type(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        summary = summarize_research_dataset(load_research_dataset(bars, feats))
        assert isinstance(summary, ResearchDatasetSummary)

    def test_summary_row_count_and_symbols(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        feats = _write(
            pl.concat([_features_df("AAPL"), _features_df("MSFT")]),
            tmp_path / "features.parquet",
        )
        summary = summarize_research_dataset(load_research_dataset(bars, feats))
        assert summary.row_count == 12
        assert summary.symbols == ["AAPL", "MSFT"]

    def test_summary_date_range(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        feats = _write(_features_df(n_rows=6), tmp_path / "features.parquet")
        summary = summarize_research_dataset(load_research_dataset(bars, feats))
        assert "2024-01-02" in summary.start
        assert "2024-01-07" in summary.end

    def test_summary_feature_columns(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        summary = summarize_research_dataset(load_research_dataset(bars, feats))
        assert summary.feature_column_count == len(FEATURE_NAMES)
        assert set(summary.feature_columns) == set(FEATURE_NAMES)

    def test_summary_null_counts(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        summary = summarize_research_dataset(load_research_dataset(bars, feats))
        # each feature column has exactly one null (first row) in the fixture
        for name in FEATURE_NAMES:
            assert summary.null_counts[name] == 1

    def test_summary_empty_rejected(self) -> None:
        with pytest.raises(ResearchDatasetError, match="empty research dataset"):
            summarize_research_dataset(_bars_df().head(0))
