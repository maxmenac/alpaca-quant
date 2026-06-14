"""Tests for list_research_datasets CLI. tmp_path synthetic manifests only — no .env, no net."""

import subprocess
import sys
from pathlib import Path

import yaml


def _manifest(dataset_id: str = "rds-aabbccdd", symbols: list[str] | None = None) -> dict:
    return {
        "dataset_id": dataset_id,
        "created_at": "2026-06-14T12:00:00+00:00",
        "symbols": symbols or ["AAPL"],
        "start": "2024-01-02 05:00:00+00:00",
        "end": "2024-01-08 05:00:00+00:00",
        "as_of": None,
        "bars_path": "/local/data/runs/run/historical_bars.parquet",
        "features_paths": ["/local/data/runs/run/features_AAPL.parquet"],
        "row_count": 5,
        "feature_count": 8,
        "known_gaps": [],
        "no_trading": True,
        "no_backtesting": True,
        "no_model_training": True,
    }


def _write_manifest(path: Path, data: dict) -> Path:
    path.write_text(yaml.dump(data))
    return path


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    script = (
        Path(__file__).resolve().parent.parent.parent / "scripts" / "list_research_datasets.py"
    )
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


def test_missing_dir_exits(tmp_path: Path) -> None:
    result = _run_cli(["--dir", str(tmp_path / "nope")])
    assert result.returncode != 0
    assert "directory not found" in result.stderr


def test_no_manifests_exits(tmp_path: Path) -> None:
    d = tmp_path / "empty"
    d.mkdir()
    result = _run_cli(["--dir", str(d)])
    assert result.returncode != 0
    assert "No research datasets found" in result.stderr


def test_one_dataset(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "research_dataset_rds-aabbccdd_manifest.yaml", _manifest())
    result = _run_cli(["--dir", str(tmp_path)])
    assert result.returncode == 0
    assert "rds-aabbccdd" in result.stdout
    assert "AAPL" in result.stdout
    assert "row_count" in result.stdout
    assert "feature_count" in result.stdout


def test_multiple_datasets(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path / "research_dataset_rds-1111_manifest.yaml", _manifest("rds-1111", ["AAPL"])
    )
    _write_manifest(
        tmp_path / "research_dataset_rds-2222_manifest.yaml",
        _manifest("rds-2222", ["MSFT", "TSLA"]),
    )
    result = _run_cli(["--dir", str(tmp_path)])
    assert result.returncode == 0
    assert "rds-1111" in result.stdout
    assert "rds-2222" in result.stdout
    assert "2 found" in result.stdout


def test_malformed_manifest_exits_nonzero(tmp_path: Path) -> None:
    (tmp_path / "research_dataset_bad_manifest.yaml").write_text("not: valid: yaml: [[[")
    result = _run_cli(["--dir", str(tmp_path)])
    assert result.returncode != 0


def test_missing_required_key(tmp_path: Path) -> None:
    bad = {"dataset_id": "rds-x"}  # missing the rest
    _write_manifest(tmp_path / "research_dataset_x_manifest.yaml", bad)
    result = _run_cli(["--dir", str(tmp_path)])
    assert result.returncode != 0
    assert "missing keys" in result.stdout or "missing keys" in result.stderr


def test_no_secret_names_in_output(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "research_dataset_rds-aabbccdd_manifest.yaml", _manifest())
    result = _run_cli(["--dir", str(tmp_path)])
    combined = result.stdout + result.stderr
    assert "APCA_API_KEY" not in combined
    assert "SECRET" not in combined
    assert "password" not in combined.lower()


def test_created_at_shown(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "research_dataset_rds-aabbccdd_manifest.yaml", _manifest())
    result = _run_cli(["--dir", str(tmp_path)])
    assert result.returncode == 0
    assert "2026-06-14" in result.stdout
