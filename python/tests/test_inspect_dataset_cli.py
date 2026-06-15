"""Phase 4D inspect_dataset CLI tests. Temp paths only: no data/runs, network, env, or API."""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from alpaca_quant.research.data_contract import FeatureSpec
from alpaca_quant.research.ml_dataset import DatasetConfig, assemble_ml_dataset
from alpaca_quant.research.targets import build_forward_return_labels

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "inspect_dataset.py"
LABEL = "label_forward_return_1d"
FEATURE = "bar_volume_raw"


def _day(n: int) -> datetime:
    return datetime(2024, 1, n, tzinfo=UTC)


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    closes = [100.0, 110.0, 121.0, 130.0, 140.0, 150.0]
    bars = pl.DataFrame(
        {
            "symbol": ["AAPL"] * len(closes),
            "timestamp": [_day(2 + i) for i in range(len(closes))],
            "close": closes,
        }
    )
    labels = build_forward_return_labels(bars)
    features = bars.select(["symbol", "timestamp"]).with_columns(
        pl.Series(FEATURE, [float(i + 1) * 1000.0 for i in range(len(closes))])
    )
    result = assemble_ml_dataset(
        labels=labels,
        features=features,
        feature_specs=[FeatureSpec(FEATURE)],
        label_columns=[LABEL],
        config=DatasetConfig(synthetic_no_universe=True),
    )
    dataset_path = tmp_path / "dataset.parquet"
    manifest_path = tmp_path / "manifest.json"
    registry_path = tmp_path / "registry.json"
    result.frame.write_parquet(dataset_path)
    manifest_path.write_text(json.dumps(result.manifest.to_dict(), default=str))
    registry_path.write_text(
        json.dumps(
            {
                "features": [
                    {
                        "name": FEATURE,
                        "family": "mechanical",
                        "description": "neutral pass-through",
                        "dtype": "float64",
                        "source": "caller_provided",
                        "pit_safe": True,
                        "allowed_in_phase": ["4C", "4D"],
                    }
                ]
            }
        )
    )
    return dataset_path, manifest_path, registry_path


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_cli_writes_report_to_temp_paths(tmp_path: Path) -> None:
    dataset_path, manifest_path, registry_path = _write_inputs(tmp_path)
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    result = _run(
        [
            "--dataset", str(dataset_path),
            "--manifest", str(manifest_path),
            "--feature-registry", str(registry_path),
            "--output-json", str(out_json),
            "--output-md", str(out_md),
        ]
    )
    assert result.returncode == 0, result.stderr
    assert out_json.is_file()
    assert out_md.is_file()

    report = json.loads(out_json.read_text())
    assert report["schema_version"] == 1
    assert report["verdict"] in {"OK", "SUSPECT", "REJECTED"}
    assert report["feature_set_id"].startswith("fs-")
    md = out_md.read_text()
    assert "This report inspects dataset and feature metadata only." in md

    # No artifacts leaked into data/runs.
    assert not (REPO_ROOT / "data" / "runs" / "report.json").exists()


def test_cli_fails_on_missing_dataset(tmp_path: Path) -> None:
    _, manifest_path, registry_path = _write_inputs(tmp_path)
    result = _run(
        [
            "--dataset", str(tmp_path / "nope.parquet"),
            "--manifest", str(manifest_path),
            "--feature-registry", str(registry_path),
            "--output-json", str(tmp_path / "r.json"),
            "--output-md", str(tmp_path / "r.md"),
        ]
    )
    assert result.returncode == 1
    assert "ERROR" in result.stderr
