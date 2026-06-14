"""Tests for the list_experiments CLI. tmp_path only — no network, no real .env."""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from alpaca_quant.research.experiment_registry import ExperimentRecord


def _record_line(run_id: str = "exp-test-001", **overrides) -> str:
    values = {
        "run_id": run_id,
        "created_at": datetime(2026, 6, 14, 12, tzinfo=UTC),
        "git_sha": "abc1234def",
        "dataset_id": "rds-85eb9a7b",
        "feature_set_id": "feat-AAPL-27d52941",
        "seed": 42,
        "decided_by": "max",
    }
    values.update(overrides)
    rec = ExperimentRecord(**values)
    return json.dumps(rec.model_dump(mode="json"), sort_keys=True)


def _write_registry(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    return path


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    script = Path(__file__).resolve().parents[2] / "scripts" / "list_experiments.py"
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


def test_missing_registry_exits_nonzero(tmp_path: Path) -> None:
    result = _run_cli(["--registry", str(tmp_path / "nope.jsonl")])
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_one_experiment_listed(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "reg.jsonl", [_record_line("exp-test-001")])
    result = _run_cli(["--registry", str(registry)])
    assert result.returncode == 0
    assert "exp-test-001" in result.stdout
    assert "rds-85eb9a7b" in result.stdout
    assert "keep_researching" in result.stdout
    assert "1 experiment(s) total." in result.stdout


def test_multiple_experiments_listed(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path / "reg.jsonl",
        [_record_line("exp-test-001"), _record_line("exp-test-002")],
    )
    result = _run_cli(["--registry", str(registry)])
    assert result.returncode == 0
    assert "exp-test-001" in result.stdout
    assert "exp-test-002" in result.stdout
    assert "2 experiment(s) total." in result.stdout


def test_malformed_registry_exits_nonzero(tmp_path: Path) -> None:
    registry = tmp_path / "reg.jsonl"
    registry.write_text("not-json\n", encoding="utf-8")
    result = _run_cli(["--registry", str(registry)])
    assert result.returncode == 1
    assert "Error reading registry" in result.stderr


def test_no_secret_names_in_output(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path / "reg.jsonl", [_record_line("exp-test-001")])
    result = _run_cli(["--registry", str(registry)])
    combined = result.stdout + result.stderr
    assert "ALPACA_API_KEY_ID" not in combined
    assert "ALPACA_API_SECRET_KEY" not in combined
    assert "SECRET" not in combined
