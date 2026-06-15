"""Phase 4C assemble_dataset CLI tests. Temp paths only: no data/runs, network, env, or API."""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "assemble_dataset.py"
LABEL = "label_forward_return_1d"


def _day(n: int) -> datetime:
    return datetime(2024, 1, n, tzinfo=UTC)


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    closes = [100.0, 110.0, 121.0, 130.0, 140.0, 150.0]
    timestamps = [_day(2 + i) for i in range(len(closes))]
    labels = pl.DataFrame(
        {
            "symbol": ["AAPL"] * len(closes),
            "timestamp": timestamps,
            LABEL: [0.1, 0.1, 0.07, 0.08, 0.07, None],
        }
    )
    features = pl.DataFrame(
        {
            "symbol": ["AAPL"] * len(closes),
            "timestamp": timestamps,
            "dollar_volume": [float(i + 1) * 1000.0 for i in range(len(closes))],
        }
    )
    labels_path = tmp_path / "labels.parquet"
    features_path = tmp_path / "features.parquet"
    labels.write_parquet(labels_path)
    features.write_parquet(features_path)

    spec = {
        "id_column": "symbol",
        "label_columns": [LABEL],
        "feature_specs": [{"name": "dollar_volume"}],
        "config": {"synthetic_no_universe": True},
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    return labels_path, features_path, spec_path


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_cli_writes_manifest_to_temp_paths(tmp_path: Path) -> None:
    labels_path, features_path, spec_path = _write_inputs(tmp_path)
    out_json = tmp_path / "manifest.json"
    out_md = tmp_path / "manifest.md"
    out_dataset = tmp_path / "dataset.parquet"

    result = _run(
        [
            "--labels", str(labels_path),
            "--features", str(features_path),
            "--spec", str(spec_path),
            "--output-json", str(out_json),
            "--output-md", str(out_md),
            "--output-dataset", str(out_dataset),
        ]
    )
    assert result.returncode == 0, result.stderr
    assert out_json.is_file()
    assert out_md.is_file()
    assert out_dataset.is_file()

    manifest = json.loads(out_json.read_text())
    assert manifest["schema_version"] == 1
    assert manifest["verdict"] == "SUSPECT"  # synthetic no-universe mode
    assert manifest["target_columns"] == [LABEL]
    assert "# ML Dataset Manifest (Phase 4C)" in out_md.read_text()
    assert "verdict" in result.stdout

    # No artifacts leaked into the repo's data/runs.
    assert not (REPO_ROOT / "data" / "runs" / "manifest.json").exists()


def test_cli_fails_on_missing_label_column(tmp_path: Path) -> None:
    labels_path, features_path, spec_path = _write_inputs(tmp_path)
    bad_spec = json.loads(spec_path.read_text())
    bad_spec["label_columns"] = ["nope"]
    spec_path.write_text(json.dumps(bad_spec))
    result = _run(
        [
            "--labels", str(labels_path),
            "--features", str(features_path),
            "--spec", str(spec_path),
            "--output-json", str(tmp_path / "m.json"),
            "--output-md", str(tmp_path / "m.md"),
        ]
    )
    assert result.returncode == 1
    assert "ERROR" in result.stderr
