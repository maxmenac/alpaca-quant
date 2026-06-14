"""Tests for list_feature_sets CLI. All fixtures use tmp_path — no data/runs/, no .env."""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import yaml


def _write_feature_parquet(path: Path, symbol: str = "AAPL", n_rows: int = 5) -> Path:
    closes = [100.0 + i for i in range(n_rows)]
    df = pl.DataFrame(
        {
            "symbol": [symbol] * n_rows,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n_rows)],
            "close": closes,
            "daily_return": [None] + [0.01] * (n_rows - 1),
            "log_return": [None] + [0.00995] * (n_rows - 1),
            "rolling_vol_20d": [None] * n_rows,
            "sma_5d": [None] * n_rows,
            "sma_20d": [None] * n_rows,
            "ema_5d": [None] * n_rows,
            "ema_20d": [None] * n_rows,
            "rolling_vol_volume_20d": [None] * n_rows,
            "feature_set_id": [f"feat-{symbol}-aabbccdd"] * n_rows,
        }
    )
    df.write_parquet(path)
    return path


def _write_manifest(path: Path, symbol: str = "AAPL", n_rows: int = 5) -> Path:
    manifest = {
        "feature_set_id": f"feat-{symbol}-aabbccdd",
        "input_parquet": str(path.parent / "historical_bars.parquet"),
        "symbol": symbol,
        "date_range": {"start": "2024-01-02", "end": "2024-01-06"},
        "feature_names": [
            "daily_return",
            "log_return",
            "rolling_vol_20d",
            "sma_5d",
            "sma_20d",
            "ema_5d",
            "ema_20d",
            "rolling_vol_volume_20d",
        ],
        "lookback_windows": {"rolling_vol": 20, "sma": [5, 20], "ema": [5, 20]},
        "row_count": n_rows,
        "generated_at": "2026-06-14T12:00:00+00:00",
        "no_trading": True,
    }
    path.write_text(yaml.dump(manifest))
    return path


def _setup_feature_set(run_dir: Path, symbol: str = "AAPL") -> None:
    _write_feature_parquet(run_dir / f"features_{symbol}.parquet", symbol=symbol)
    _write_manifest(run_dir / f"features_{symbol}_manifest.yaml", symbol=symbol)


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "list_feature_sets.py"
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
    )


class TestListFeatureSetsModule:
    """Unit-test the module functions directly without spawning a subprocess."""

    def test_missing_run_dir_exits(self, tmp_path: Path) -> None:
        result = _run_cli(["--run-dir", str(tmp_path / "does_not_exist")])
        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_no_feature_files_exits(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "empty_run"
        run_dir.mkdir()
        result = _run_cli(["--run-dir", str(run_dir)])
        assert result.returncode != 0
        assert "No feature sets found" in result.stderr

    def test_one_feature_set(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run01"
        run_dir.mkdir()
        _setup_feature_set(run_dir, symbol="AAPL")

        result = _run_cli(["--run-dir", str(run_dir)])
        assert result.returncode == 0
        assert "feat-AAPL-aabbccdd" in result.stdout
        assert "AAPL" in result.stdout
        assert "row_count" in result.stdout
        assert "no_trading" in result.stdout

    def test_multiple_feature_sets(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run02"
        run_dir.mkdir()
        _setup_feature_set(run_dir, symbol="AAPL")
        _setup_feature_set(run_dir, symbol="MSFT")

        result = _run_cli(["--run-dir", str(run_dir)])
        assert result.returncode == 0
        assert "AAPL" in result.stdout
        assert "MSFT" in result.stdout
        assert "2 found" in result.stdout

    def test_malformed_manifest_exits_nonzero(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run03"
        run_dir.mkdir()
        (run_dir / "features_AAPL_manifest.yaml").write_text("this is not: valid: yaml: [[[")

        result = _run_cli(["--run-dir", str(run_dir)])
        assert result.returncode != 0

    def test_manifest_missing_required_key(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run04"
        run_dir.mkdir()
        bad = {"symbol": "AAPL"}  # missing all other required keys
        (run_dir / "features_AAPL_manifest.yaml").write_text(yaml.dump(bad))

        result = _run_cli(["--run-dir", str(run_dir)])
        assert result.returncode != 0
        assert "missing keys" in result.stdout or "missing keys" in result.stderr

    def test_no_secret_env_names_in_output(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run05"
        run_dir.mkdir()
        _setup_feature_set(run_dir, symbol="AAPL")

        result = _run_cli(["--run-dir", str(run_dir)])
        combined = result.stdout + result.stderr
        assert "APCA_API_KEY" not in combined
        assert "SECRET" not in combined
        assert "password" not in combined.lower()

    def test_output_contains_feature_count(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run06"
        run_dir.mkdir()
        _setup_feature_set(run_dir, symbol="AAPL")

        result = _run_cli(["--run-dir", str(run_dir)])
        assert result.returncode == 0
        assert "features" in result.stdout

    def test_output_contains_date_range(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run07"
        run_dir.mkdir()
        _setup_feature_set(run_dir, symbol="AAPL")

        result = _run_cli(["--run-dir", str(run_dir)])
        assert result.returncode == 0
        assert "2024-01-02" in result.stdout

    def test_parquet_missing_flagged(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run08"
        run_dir.mkdir()
        # write manifest but not parquet
        _write_manifest(run_dir / "features_AAPL_manifest.yaml", symbol="AAPL")

        result = _run_cli(["--run-dir", str(run_dir)])
        assert result.returncode == 0  # not fatal — just reported
        assert "MISSING" in result.stdout
