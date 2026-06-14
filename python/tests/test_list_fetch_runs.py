"""Tests for the list_fetch_runs CLI script.

All tests use local JSONL files only — no network, no Alpaca credentials.
"""

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from list_fetch_runs import main  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _valid_record(run_id: str = "fetch-20260614T120000Z-aabbccdd", **overrides) -> dict:
    base = {
        "run_id": run_id,
        "created_at": "2026-06-14T12:00:00+00:00",
        "symbols": ["AAPL", "MSFT"],
        "start": "2024-01-02",
        "end": "2024-01-08",
        "feed": "iex",
        "rows_written": 10,
        "output_dir": "data/runs/alpaca_controlled_001",
        "parquet_path": "data/runs/alpaca_controlled_001/historical_bars.parquet",
        "manifest_path": "data/runs/alpaca_controlled_001/data_declaration.yaml",
        "data_declaration_id": "dq-tier0-alpaca-iex-2024-01-02-2024-01-08",
        "verification_passed": True,
        "known_gaps": ["IEX covers only a subset of US market volume"],
        "mode": "controlled_historical_fetch",
        "request_id": None,
        "status": "success",
    }
    base.update(overrides)
    return base


def test_missing_registry_exits_nonzero(tmp_path, capsys):
    missing = tmp_path / "no_registry.jsonl"
    rc = main(["--registry", str(missing)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "Error reading registry" in captured.err
    assert captured.out == ""


def test_empty_registry_prints_no_runs(tmp_path, capsys):
    registry = tmp_path / "fetch_registry.jsonl"
    registry.write_text("", encoding="utf-8")

    rc = main(["--registry", str(registry)])

    assert rc == 0
    captured = capsys.readouterr()
    assert "No fetch runs found" in captured.out


def test_single_run_appears_in_output(tmp_path, capsys):
    registry = tmp_path / "fetch_registry.jsonl"
    _write_jsonl(registry, [_valid_record()])

    rc = main(["--registry", str(registry)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "fetch-20260614T120000Z-aabbccdd" in out
    assert "AAPL,MSFT" in out
    assert "2024-01-02 to 2024-01-08" in out
    assert "iex" in out
    assert "10" in out
    assert "yes" in out
    assert "success" in out
    assert "1 run(s) total" in out


def test_multiple_runs_all_appear_in_order(tmp_path, capsys):
    registry = tmp_path / "fetch_registry.jsonl"
    _write_jsonl(
        registry,
        [
            _valid_record("fetch-20260614T120000Z-aaaaaaaa"),
            _valid_record("fetch-20260614T130000Z-bbbbbbbb"),
        ],
    )

    rc = main(["--registry", str(registry)])

    assert rc == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    ids = [row for row in lines if row.startswith("fetch-")]
    assert ids[0].startswith("fetch-20260614T120000Z-aaaaaaaa")
    assert ids[1].startswith("fetch-20260614T130000Z-bbbbbbbb")
    assert "2 run(s) total" in out


def test_malformed_jsonl_exits_nonzero(tmp_path, capsys):
    registry = tmp_path / "fetch_registry.jsonl"
    registry.write_text("not-valid-json\n", encoding="utf-8")

    rc = main(["--registry", str(registry)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "Error reading registry" in captured.err


def test_output_never_contains_api_key_env_names(tmp_path, capsys):
    registry = tmp_path / "fetch_registry.jsonl"
    _write_jsonl(registry, [_valid_record()])

    main(["--registry", str(registry)])

    out = capsys.readouterr().out
    assert "ALPACA_API_KEY_ID" not in out
    assert "ALPACA_API_SECRET_KEY" not in out


def test_default_registry_path_used_when_no_flag(tmp_path, monkeypatch, capsys):
    """Confirm the CLI uses the default path when --registry is omitted."""
    registry = tmp_path / "fetch_registry.jsonl"
    _write_jsonl(registry, [_valid_record()])

    # Monkeypatch the module-level default so the test is hermetic.
    import list_fetch_runs as mod
    monkeypatch.setattr(mod, "DEFAULT_REGISTRY", registry)

    rc = main([])  # no --registry flag

    assert rc == 0
    assert "1 run(s) total" in capsys.readouterr().out
