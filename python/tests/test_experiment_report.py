"""Tests for experiment report building. Synthetic + tmp_path only — no .env, no network."""

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
import yaml

from alpaca_quant.backtest.engine.engine import run_backtest
from alpaca_quant.backtest.null_models import run_null_battery
from alpaca_quant.research.experiment_report import (
    ExperimentReportError,
    build_report_payload,
    compute_report_health,
    render_markdown,
    summarize_data_declaration,
    summarize_null_battery,
    validate_report_payload,
    write_report,
)

_FACTORS = [1.03, 0.98, 1.05, 0.97, 1.04, 0.96]

_TIER1_DECLARATION = {
    "data_declaration_id": "dq-tier1-us-largecap-2026-06-14",
    "tier": 1,
    "universe_source": "alpaca-us-active-2026",
    "universe_id": "us-largecap-v001",
    "survivorship_bias_status": "partial",
    "corporate_actions_status": "partial",
    "pit_status": "best_effort",
    "data_feed": "sip-historical",
}


def _frame(n: int = 20) -> pl.DataFrame:
    closes = [100.0]
    for i in range(n - 1):
        closes.append(closes[-1] * _FACTORS[i % len(_FACTORS)])
    return pl.DataFrame(
        {
            "symbol": ["AAPL"] * n,
            "timestamp": [datetime(2024, 1, 2 + i, tzinfo=UTC) for i in range(n)],
            "close": closes,
            "weight": [1.0] * n,
        }
    )


def _costs(tmp_path: Path) -> str:
    path = tmp_path / "costs.yaml"
    path.write_text(
        yaml.dump(
            {
                "commission_bps": 0,
                "slippage_bps_daily": 5,
                "slippage_bps_stress_2x": 10,
                "slippage_bps_stress_5x": 25,
            }
        )
    )
    return str(path)


def _payload(tmp_path: Path, data_declaration: dict | None = None) -> dict:
    frame = _frame()
    bt = run_backtest(frame)
    battery = run_null_battery(frame, costs_path=_costs(tmp_path))
    return build_report_payload(
        run_id="exp-test-001",
        as_of="2024-01-21",
        seed=12345,
        config={"horizon": 1, "seed": 12345, "weights_path": "/tmp/weights.parquet"},
        config_hash="sha256:abc",
        weight_source="caller:test",
        backtest_result=bt,
        battery_report=battery,
        data_declaration=data_declaration,
        created_at="2024-01-21T00:00:00+00:00",
        git_sha="abc1234",
        dataset_id="rds-test",
        feature_set_id="features-test",
        cost_config_path="configs/costs.yaml",
    )


def test_payload_keys(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    for key in (
        "run_id",
        "as_of",
        "seed",
        "config",
        "config_hash",
        "weight_source",
        "headline_metrics",
        "null_battery",
        "equity_curve",
    ):
        assert key in payload


def test_markdown_contains_metrics_and_verdicts(tmp_path: Path) -> None:
    md = render_markdown(_payload(tmp_path))
    assert "# Backtest experiment exp-test-001" in md
    assert "sharpe" in md
    assert "future_leak_detected" in md


def test_write_report_creates_both_files(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    paths = write_report(payload, tmp_path / "reports")
    assert paths.json_path.is_file()
    assert paths.markdown_path.is_file()


def test_json_report_parses(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    paths = write_report(payload, tmp_path / "reports")
    parsed = json.loads(paths.json_path.read_text())
    assert parsed["run_id"] == "exp-test-001"
    assert "null_battery" in parsed


def test_no_secret_names_in_reports(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    paths = write_report(payload, tmp_path / "reports")
    combined = paths.json_path.read_text() + paths.markdown_path.read_text()
    assert "ALPACA_API_KEY_ID" not in combined
    assert "ALPACA_API_SECRET_KEY" not in combined


# --- Phase 3D-1: data declaration + tier banner ---


def test_markdown_includes_data_declaration_section(tmp_path: Path) -> None:
    md = render_markdown(_payload(tmp_path, data_declaration=_TIER1_DECLARATION))
    assert "## Data Declaration" in md
    # The four critical data-honesty fields are surfaced.
    assert "survivorship_bias_status" in md
    assert "corporate_actions_status" in md
    assert "pit_status" in md
    assert "best_effort" in md
    # A complete Tier 1 declaration carries no data-declaration warning banner.
    # (Report-health SUSPECT from the null battery is a separate 3D-2 banner.)
    assert "DATA DECLARATION MISSING" not in md
    assert "DATA DECLARATION INCOMPLETE" not in md
    assert "validates code, not strategy" not in md


def test_json_report_includes_data_declaration_block(tmp_path: Path) -> None:
    payload = _payload(tmp_path, data_declaration=_TIER1_DECLARATION)
    paths = write_report(payload, tmp_path / "reports")
    parsed = json.loads(paths.json_path.read_text())
    assert parsed["data_declaration"] is not None
    assert parsed["data_declaration"]["tier"] == 1
    assert parsed["data_declaration_status"] == "COMPLETE"
    assert parsed["data_declaration_missing_fields"] == []


def test_tier0_warning_banner_present(tmp_path: Path) -> None:
    tier0 = {**_TIER1_DECLARATION, "tier": 0}
    md = render_markdown(_payload(tmp_path, data_declaration=tier0))
    assert "Tier 0 data validates code, not strategy." in md


def test_tier1_has_no_tier0_warning(tmp_path: Path) -> None:
    md = render_markdown(_payload(tmp_path, data_declaration=_TIER1_DECLARATION))
    assert "Tier 0 data validates code, not strategy." not in md


def test_missing_critical_fields_not_silently_ignored(tmp_path: Path) -> None:
    incomplete = {k: v for k, v in _TIER1_DECLARATION.items() if k != "pit_status"}
    payload = _payload(tmp_path, data_declaration=incomplete)
    assert payload["data_declaration_status"] == "INCOMPLETE"
    assert "pit_status" in payload["data_declaration_missing_fields"]
    md = render_markdown(payload)
    assert "INCOMPLETE" in md
    assert "SUSPECT" in md


def test_absent_declaration_marked_suspect(tmp_path: Path) -> None:
    payload = _payload(tmp_path, data_declaration=None)
    assert payload["data_declaration_status"] == "MISSING"
    md = render_markdown(payload)
    assert "DATA DECLARATION MISSING" in md
    assert "SUSPECT" in md


def test_summarize_data_declaration_classifies() -> None:
    assert summarize_data_declaration(None)["status"] == "MISSING"
    assert summarize_data_declaration(_TIER1_DECLARATION)["status"] == "COMPLETE"
    blank = {**_TIER1_DECLARATION, "tier": None}
    summary = summarize_data_declaration(blank)
    assert summary["status"] == "INCOMPLETE"
    assert "tier" in summary["missing_fields"]


# --- Phase 3D-2: null battery verdict + ENGINE_SUSPECT ---


def _battery_dict(*, leak_detected: bool = True) -> dict:
    """Minimal null-battery dict shaped like NullBatteryReport.as_dict()."""
    return {
        "baseline": {"sharpe": 1.0, "total_return": 0.2},
        "shifted_weights": {"sharpe": 0.1, "total_return": 0.01},
        "cost_stress_2x": {"sharpe": 0.5, "total_return": 0.1},
        "cost_stress_5x": {"sharpe": 0.2, "total_return": 0.05},
        "future_leak_detected": leak_detected,
        "random_near_zero": True,
        "shuffled_near_zero": True,
    }


def test_markdown_includes_null_battery_verdict(tmp_path: Path) -> None:
    md = render_markdown(_payload(tmp_path, data_declaration=_TIER1_DECLARATION))
    assert "## Null Battery Verdict" in md
    assert "future-leak trap" in md
    assert "cost stress ×2" in md
    assert "Report health:" in md


def test_json_includes_null_battery_summary(tmp_path: Path) -> None:
    payload = _payload(tmp_path, data_declaration=_TIER1_DECLARATION)
    paths = write_report(payload, tmp_path / "reports")
    parsed = json.loads(paths.json_path.read_text())
    assert "null_battery_summary" in parsed
    assert "verdicts" in parsed["null_battery_summary"]
    assert "report_health" in parsed
    # The synthetic trend frame leaks loudly: the trap explodes -> trap PASS.
    assert parsed["null_battery_summary"]["verdicts"]["future_leak_trap"] == "PASS"


def test_future_leak_failure_is_engine_suspect() -> None:
    summary = summarize_null_battery(_battery_dict(leak_detected=False))
    assert summary["engine_suspect"] is True
    assert summary["verdicts"]["future_leak_trap"] == "FAIL"
    # Engine suspicion wins over an otherwise-complete declaration.
    assert compute_report_health("COMPLETE", summary) == "ENGINE_SUSPECT"


def test_engine_suspect_renders_at_top(tmp_path: Path) -> None:
    payload = _payload(tmp_path, data_declaration=_TIER1_DECLARATION)
    payload["report_health"] = "ENGINE_SUSPECT"
    payload["null_battery_summary"] = summarize_null_battery(_battery_dict(leak_detected=False))
    md = render_markdown(payload)
    # The ENGINE_SUSPECT banner appears before the headline metrics.
    assert "ENGINE_SUSPECT" in md
    assert md.index("ENGINE_SUSPECT") < md.index("## Headline metrics")


def test_missing_null_battery_is_not_clean_ok() -> None:
    summary = summarize_null_battery(None)
    assert summary["available"] is False
    assert all(v == "UNKNOWN" for v in summary["verdicts"].values())
    # Even with a complete declaration, no battery -> SUSPECT, never OK.
    assert compute_report_health("COMPLETE", summary) == "SUSPECT"


def test_health_ok_only_when_declaration_and_core_battery_pass() -> None:
    good = summarize_null_battery(_battery_dict(leak_detected=True))
    assert compute_report_health("COMPLETE", good) == "OK"
    # Incomplete declaration drags health to SUSPECT even if the battery passes.
    assert compute_report_health("INCOMPLETE", good) == "SUSPECT"


def test_data_declaration_behavior_still_works_with_battery(tmp_path: Path) -> None:
    # 3D-1 behavior intact alongside 3D-2: Tier 0 warning still present.
    tier0 = {**_TIER1_DECLARATION, "tier": 0}
    md = render_markdown(_payload(tmp_path, data_declaration=tier0))
    assert "Tier 0 data validates code, not strategy." in md
    assert "## Data Declaration" in md
    assert "## Null Battery Verdict" in md


# --- Phase 3D-3: reproducibility fingerprint + fail-closed schema ---


def test_json_includes_reproducibility_block(tmp_path: Path) -> None:
    payload = _payload(tmp_path, data_declaration=_TIER1_DECLARATION)
    paths = write_report(payload, tmp_path / "reports")
    parsed = json.loads(paths.json_path.read_text())
    repro = parsed["reproducibility"]
    for key in ("run_id", "created_at", "git_sha", "config_hash", "seed", "weights_path"):
        assert key in repro
    assert repro["git_sha"] == "abc1234"
    assert repro["dataset_id"] == "rds-test"
    assert repro["data_declaration_id"] == _TIER1_DECLARATION["data_declaration_id"]


def test_markdown_includes_reproducibility_section_and_replay_hint(tmp_path: Path) -> None:
    md = render_markdown(_payload(tmp_path, data_declaration=_TIER1_DECLARATION))
    assert "## Reproducibility" in md
    assert "git_sha" in md
    assert "Replay requires: git_sha" in md


def test_optional_repro_fields_degrade_to_unknown_without_crashing(tmp_path: Path) -> None:
    # No git_sha / dataset_id / feature_set_id: optional, must not crash, shown as UNKNOWN,
    # and the replay hint is withheld (essentials incomplete).
    frame = _frame()
    bt = run_backtest(frame)
    battery = run_null_battery(frame, costs_path=_costs(tmp_path))
    payload = build_report_payload(
        run_id="exp-test-002",
        as_of="2024-01-21",
        seed=7,
        config={"horizon": 1},
        config_hash="sha256:def",
        weight_source="caller:test",
        backtest_result=bt,
        battery_report=battery,
        created_at="2024-01-21T00:00:00+00:00",
    )
    assert payload["reproducibility"]["git_sha"] == "UNKNOWN"
    assert payload["reproducibility"]["dataset_id"] == "UNKNOWN"
    md = render_markdown(payload)
    assert "## Reproducibility" in md
    assert "Replay requires: git_sha" not in md


def test_missing_critical_field_raises_report_error(tmp_path: Path) -> None:
    payload = _payload(tmp_path, data_declaration=_TIER1_DECLARATION)
    del payload["config_hash"]
    with pytest.raises(ExperimentReportError, match="config_hash"):
        render_markdown(payload)
    with pytest.raises(ExperimentReportError, match="config_hash"):
        write_report(payload, tmp_path / "reports")


def test_missing_critical_reproducibility_field_raises(tmp_path: Path) -> None:
    payload = _payload(tmp_path, data_declaration=_TIER1_DECLARATION)
    payload["reproducibility"]["created_at"] = None
    with pytest.raises(ExperimentReportError, match="created_at"):
        validate_report_payload(payload)


def test_validate_passes_on_complete_payload(tmp_path: Path) -> None:
    payload = _payload(tmp_path, data_declaration=_TIER1_DECLARATION)
    # Should not raise.
    validate_report_payload(payload)
