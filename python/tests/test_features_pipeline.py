"""Tests for the feature pipeline. All synthetic tmp_path fixtures — no Alpaca API, no .env."""

import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from alpaca_quant.features.pipeline import (
    FEATURE_NAMES,
    build_feature_manifest,
    build_feature_set,
)


def _write_synthetic_parquet(path: Path, n_rows: int = 30, symbol: str = "AAPL") -> Path:
    closes = [100.0 * (1 + 0.005 * i) for i in range(n_rows)]
    df = pl.DataFrame(
        {
            "symbol": [symbol] * n_rows,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n_rows)],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000 + i * 1000 for i in range(n_rows)],
            "trade_count": [500] * n_rows,
            "vwap": closes,
        }
    )
    df.write_parquet(path)
    return path


class TestBuildFeatureSet:
    def test_returns_polars_dataframe(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet")
        result = build_feature_set(parquet, "AAPL")
        assert isinstance(result, pl.DataFrame)

    def test_feature_set_id_column_present(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet")
        result = build_feature_set(parquet, "AAPL")
        assert "feature_set_id" in result.columns

    def test_feature_set_id_format(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet")
        result = build_feature_set(parquet, "AAPL")
        fid = result["feature_set_id"][0]
        assert re.match(r"^feat-AAPL-[0-9a-f]{8}$", fid), f"unexpected id: {fid}"

    def test_feature_set_id_is_deterministic(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet")
        r1 = build_feature_set(parquet, "AAPL")
        r2 = build_feature_set(parquet, "AAPL")
        assert r1["feature_set_id"][0] == r2["feature_set_id"][0]

    def test_all_feature_columns_present(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet")
        result = build_feature_set(parquet, "AAPL")
        for col in FEATURE_NAMES:
            assert col in result.columns, f"missing column: {col}"

    def test_non_early_rows_non_null(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet", n_rows=30)
        result = build_feature_set(parquet, "AAPL").sort("timestamp")
        # row 29 (last) must have all features non-null (window=20, 30 rows is enough)
        last = result[-1]
        for col in FEATURE_NAMES:
            assert last[col][0] is not None, f"expected non-null at last row for {col}"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            build_feature_set(tmp_path / "does_not_exist.parquet", "AAPL")

    def test_missing_symbol_raises(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet", symbol="AAPL")
        with pytest.raises(ValueError, match="MSFT"):
            build_feature_set(parquet, "MSFT")

    def test_symbol_case_insensitive(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet", symbol="AAPL")
        result = build_feature_set(parquet, "aapl")
        assert result["symbol"][0] == "AAPL"

    def test_row_count_preserved(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet", n_rows=30)
        result = build_feature_set(parquet, "AAPL")
        assert len(result) == 30

    def test_no_alpaca_import_in_pipeline(self) -> None:
        import alpaca_quant.features.pipeline as mod

        src = Path(mod.__file__).read_text()
        assert "AlpacaConfig" not in src
        assert "alpaca_bars" not in src
        assert "load_dotenv" not in src
        assert "os.getenv" not in src


class TestBuildFeatureManifest:
    def test_manifest_keys(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet")
        df = build_feature_set(parquet, "AAPL")
        manifest = build_feature_manifest(parquet, "AAPL", df)

        required = {
            "feature_set_id",
            "input_parquet",
            "symbol",
            "date_range",
            "feature_names",
            "lookback_windows",
            "row_count",
            "generated_at",
            "no_trading",
        }
        assert required.issubset(manifest.keys())

    def test_no_trading_is_true(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet")
        df = build_feature_set(parquet, "AAPL")
        manifest = build_feature_manifest(parquet, "AAPL", df)
        assert manifest["no_trading"] is True

    def test_row_count_matches(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet", n_rows=30)
        df = build_feature_set(parquet, "AAPL")
        manifest = build_feature_manifest(parquet, "AAPL", df)
        assert manifest["row_count"] == 30

    def test_feature_names_match_constants(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet")
        df = build_feature_set(parquet, "AAPL")
        manifest = build_feature_manifest(parquet, "AAPL", df)
        assert manifest["feature_names"] == FEATURE_NAMES

    def test_symbol_uppercased(self, tmp_path: Path) -> None:
        parquet = _write_synthetic_parquet(tmp_path / "bars.parquet", symbol="AAPL")
        df = build_feature_set(parquet, "aapl")
        manifest = build_feature_manifest(parquet, "aapl", df)
        assert manifest["symbol"] == "AAPL"
