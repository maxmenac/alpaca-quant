"""Sprint 4B tests: multi-symbol load, as_of guard, manifest. tmp_path only — no .env."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from alpaca_quant.features.pipeline import FEATURE_NAMES
from alpaca_quant.research.dataset import (
    FORBIDDEN_COLUMNS,
    ResearchDatasetError,
    ResearchDatasetManifest,
    build_research_dataset_manifest,
    load_research_dataset,
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
    base = _bars_df(symbol, n_rows)
    additions = [
        pl.Series(name, [None] + [0.01 * (i + 1) for i in range(n_rows - 1)])
        for name in FEATURE_NAMES
    ]
    additions.append(pl.lit(f"feat-{symbol}-deadbeef").alias("feature_set_id"))
    return base.with_columns(additions)


def _write(df: pl.DataFrame, path: Path) -> Path:
    df.write_parquet(path)
    return path


class TestMultiSymbol:
    def test_combined_features_file_two_symbols(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        feats = _write(
            pl.concat([_features_df("AAPL"), _features_df("MSFT")]),
            tmp_path / "features.parquet",
        )
        df = load_research_dataset(bars, feats)
        assert sorted(df["symbol"].unique().to_list()) == ["AAPL", "MSFT"]
        assert len(df) == 12

    def test_multiple_feature_files(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        f_aapl = _write(_features_df("AAPL"), tmp_path / "features_AAPL.parquet")
        f_msft = _write(_features_df("MSFT"), tmp_path / "features_MSFT.parquet")

        df = load_research_dataset(bars, [f_aapl, f_msft])
        assert sorted(df["symbol"].unique().to_list()) == ["AAPL", "MSFT"]
        assert len(df) == 12

    def test_symbol_list_filter(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT"), _bars_df("TSLA")]),
            tmp_path / "bars.parquet",
        )
        feats = _write(
            pl.concat([_features_df("AAPL"), _features_df("MSFT"), _features_df("TSLA")]),
            tmp_path / "features.parquet",
        )
        df = load_research_dataset(bars, feats, symbol=["AAPL", "MSFT"])
        assert sorted(df["symbol"].unique().to_list()) == ["AAPL", "MSFT"]

    def test_deterministic_sort(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("MSFT"), _bars_df("AAPL")]), tmp_path / "bars.parquet"
        )
        feats = _write(
            pl.concat([_features_df("MSFT"), _features_df("AAPL")]),
            tmp_path / "features.parquet",
        )
        df = load_research_dataset(bars, feats)
        keys = list(zip(df["symbol"].to_list(), df["timestamp"].to_list(), strict=True))
        assert keys == sorted(keys, key=lambda k: (k[0], k[1]))

    def test_mismatched_feature_columns_rejected(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        f_aapl = _write(_features_df("AAPL"), tmp_path / "features_AAPL.parquet")
        # MSFT features missing one feature column
        f_msft = _write(
            _features_df("MSFT").drop("sma_5d"), tmp_path / "features_MSFT.parquet"
        )
        with pytest.raises(ResearchDatasetError, match="mismatched feature columns"):
            load_research_dataset(bars, [f_aapl, f_msft])

    def test_symbol_missing_in_features_rejected(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        feats = _write(_features_df("AAPL"), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="features dataset has no rows for symbol"):
            load_research_dataset(bars, feats, symbol=["AAPL", "MSFT"])


class TestAsOf:
    def test_as_of_excludes_future_rows(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        feats = _write(_features_df(n_rows=6), tmp_path / "features.parquet")
        df = load_research_dataset(bars, feats, as_of="2024-01-04")
        max_date = df["timestamp"].dt.date().max()
        assert max_date == date(2024, 1, 4)
        assert len(df) == 3  # 01-02, 01-03, 01-04

    def test_as_of_inclusive(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        feats = _write(_features_df(n_rows=6), tmp_path / "features.parquet")
        df = load_research_dataset(bars, feats, as_of="2024-01-07")
        assert df["timestamp"].dt.date().max() == date(2024, 1, 7)

    def test_no_rows_after_as_of(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        feats = _write(_features_df(n_rows=6), tmp_path / "features.parquet")
        df = load_research_dataset(bars, feats, as_of="2024-01-05")
        future = df.filter(pl.col("timestamp").dt.date() > date(2024, 1, 5))
        assert future.is_empty()

    def test_as_of_composes_with_end(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        feats = _write(_features_df(n_rows=6), tmp_path / "features.parquet")
        # end is later, as_of is the tighter bound
        df = load_research_dataset(bars, feats, end="2024-01-07", as_of="2024-01-03")
        assert df["timestamp"].dt.date().max() == date(2024, 1, 3)

    def test_as_of_before_start_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="as_of date must be on or after start"):
            load_research_dataset(bars, feats, start="2024-01-05", as_of="2024-01-03")

    def test_invalid_end_before_start_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="end date must be on or after start"):
            load_research_dataset(bars, feats, start="2024-01-05", end="2024-01-03")

    def test_bad_as_of_format_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        with pytest.raises(ResearchDatasetError, match="as_of must be an ISO date"):
            load_research_dataset(bars, feats, as_of="not-a-date")


class TestManifest:
    def test_manifest_type(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        df = load_research_dataset(bars, feats)
        manifest = build_research_dataset_manifest(df, bars, feats)
        assert isinstance(manifest, ResearchDatasetManifest)

    def test_manifest_required_fields(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        df = load_research_dataset(bars, feats)
        data = build_research_dataset_manifest(df, bars, feats).to_dict()
        for key in (
            "dataset_id",
            "created_at",
            "symbols",
            "start",
            "end",
            "as_of",
            "bars_path",
            "features_paths",
            "row_count",
            "feature_count",
            "known_gaps",
            "no_trading",
            "no_backtesting",
            "no_model_training",
        ):
            assert key in data, f"missing manifest key: {key}"

    def test_manifest_safety_flags(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        df = load_research_dataset(bars, feats)
        data = build_research_dataset_manifest(df, bars, feats).to_dict()
        assert data["no_trading"] is True
        assert data["no_backtesting"] is True
        assert data["no_model_training"] is True

    def test_manifest_counts_and_symbols(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        feats = _write(
            pl.concat([_features_df("AAPL"), _features_df("MSFT")]),
            tmp_path / "features.parquet",
        )
        df = load_research_dataset(bars, feats)
        manifest = build_research_dataset_manifest(df, bars, feats)
        assert manifest.row_count == 12
        assert manifest.symbols == ["AAPL", "MSFT"]
        assert manifest.feature_count == len(FEATURE_NAMES)

    def test_manifest_records_as_of(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(n_rows=6), tmp_path / "bars.parquet")
        feats = _write(_features_df(n_rows=6), tmp_path / "features.parquet")
        df = load_research_dataset(bars, feats, as_of="2024-01-05")
        manifest = build_research_dataset_manifest(df, bars, feats, as_of="2024-01-05")
        assert manifest.as_of == "2024-01-05"

    def test_manifest_dataset_id_deterministic(self, tmp_path: Path) -> None:
        bars = _write(_bars_df(), tmp_path / "bars.parquet")
        feats = _write(_features_df(), tmp_path / "features.parquet")
        df = load_research_dataset(bars, feats)
        m1 = build_research_dataset_manifest(df, bars, feats)
        m2 = build_research_dataset_manifest(df, bars, feats)
        assert m1.dataset_id == m2.dataset_id
        assert m1.dataset_id.startswith("rds-")

    def test_manifest_multiple_features_paths(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        f_aapl = _write(_features_df("AAPL"), tmp_path / "features_AAPL.parquet")
        f_msft = _write(_features_df("MSFT"), tmp_path / "features_MSFT.parquet")
        df = load_research_dataset(bars, [f_aapl, f_msft])
        manifest = build_research_dataset_manifest(df, bars, [f_aapl, f_msft])
        assert len(manifest.features_paths) == 2


class TestNoForbiddenConcepts:
    def test_no_forbidden_columns_multi_symbol(self, tmp_path: Path) -> None:
        bars = _write(
            pl.concat([_bars_df("AAPL"), _bars_df("MSFT")]), tmp_path / "bars.parquet"
        )
        feats = _write(
            pl.concat([_features_df("AAPL"), _features_df("MSFT")]),
            tmp_path / "features.parquet",
        )
        df = load_research_dataset(bars, feats)
        for col in df.columns:
            assert col not in FORBIDDEN_COLUMNS

    def test_duplicate_keys_across_feature_files_rejected(self, tmp_path: Path) -> None:
        bars = _write(_bars_df("AAPL"), tmp_path / "bars.parquet")
        # two files both containing AAPL → duplicate symbol/timestamp after concat
        f1 = _write(_features_df("AAPL"), tmp_path / "features_1.parquet")
        f2 = _write(_features_df("AAPL"), tmp_path / "features_2.parquet")
        with pytest.raises(ResearchDatasetError, match="features contains duplicate"):
            load_research_dataset(bars, [f1, f2])
