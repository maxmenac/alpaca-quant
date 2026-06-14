"""Subprocess test for the local mocked ingestion CLI."""

import os
import subprocess
import sys
from pathlib import Path


def test_mock_ingestion_cli_runs_without_credentials(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "run_mock_ingestion_dry_run.py"
    output_dir = tmp_path / "cli-output"
    env = os.environ.copy()
    env.pop("ALPACA_API_KEY_ID", None)
    env.pop("ALPACA_API_SECRET_KEY", None)

    completed = subprocess.run(
        [sys.executable, str(script_path), "--output", str(output_dir)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Mock ingestion dry run passed" in completed.stdout
    assert "rows_written: 4" in completed.stdout
    assert "symbols: AAPL, MSFT" in completed.stdout
    assert "verification_passed: True" in completed.stdout
    assert (output_dir / "mock_bars.parquet").is_file()
    assert (output_dir / "data_declaration.yaml").is_file()

    repeated = subprocess.run(
        [sys.executable, str(script_path), "--output", str(output_dir)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert repeated.returncode == 1
    assert "Mock ingestion dry run failed" in repeated.stderr
    assert "already exists" in repeated.stderr
