"""Build experiment reports (JSON canonical + Markdown human-readable).

Local-only, non-secret. The JSON is the machine-readable record of a backtest experiment; the
Markdown is a human summary. Diagnostics are advisory — the human reads and decides.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alpaca_quant.backtest.engine.engine import BacktestResult
from alpaca_quant.backtest.null_models import NullBatteryReport

# Data-honesty fields that must be present for a report to vouch for data quality
# (DATA_QUALITY.md §2). A declaration missing any of these is marked SUSPECT, never silently
# rendered as clean.
CRITICAL_DECLARATION_FIELDS = (
    "tier",
    "survivorship_bias_status",
    "corporate_actions_status",
    "pit_status",
)
TIER_0_WARNING = "Tier 0 data validates code, not strategy."


@dataclass(frozen=True)
class ReportPaths:
    json_path: Path
    markdown_path: Path


def summarize_data_declaration(
    declaration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Classify a data declaration for report display (fail-loud, never silently clean).

    Returns the resolved status ("MISSING", "INCOMPLETE", or "COMPLETE") and the list of
    critical fields (DATA_QUALITY.md §2) that are absent or blank.
    """
    if declaration is None:
        return {"status": "MISSING", "missing_fields": list(CRITICAL_DECLARATION_FIELDS)}
    missing = [
        field
        for field in CRITICAL_DECLARATION_FIELDS
        if declaration.get(field) is None or declaration.get(field) == ""
    ]
    status = "INCOMPLETE" if missing else "COMPLETE"
    return {"status": status, "missing_fields": missing}


def build_report_payload(
    *,
    run_id: str,
    as_of: str,
    seed: int,
    config: dict[str, Any],
    config_hash: str,
    weight_source: str,
    backtest_result: BacktestResult,
    battery_report: NullBatteryReport,
    data_declaration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the canonical, JSON-serializable report payload."""
    m = backtest_result.metrics
    declaration = dict(data_declaration) if data_declaration is not None else None
    declaration_summary = summarize_data_declaration(declaration)
    return {
        "run_id": run_id,
        "as_of": as_of,
        "seed": seed,
        "config": config,
        "config_hash": config_hash,
        "weight_source": weight_source,
        "data_declaration": declaration,
        "data_declaration_status": declaration_summary["status"],
        "data_declaration_missing_fields": declaration_summary["missing_fields"],
        "headline_metrics": {
            "sharpe": m.sharpe,
            "sortino": m.sortino,
            "max_drawdown": m.max_drawdown,
            "annual_turnover": m.annual_turnover,
            "total_return": m.total_return,
            "cagr": m.cagr,
            "n_periods": m.n_periods,
        },
        "null_battery": battery_report.as_dict(),
        "equity_curve": backtest_result.periods.select(["timestamp", "equity"]).to_dicts(),
        "no_trading": True,
        "no_model_training": True,
        "no_live_execution": True,
        "no_order_submission": True,
    }


def _render_data_declaration(payload: dict[str, Any]) -> list[str]:
    """Render the Data Declaration section (data honesty, near the top of every report)."""
    declaration = payload.get("data_declaration")
    status = payload.get("data_declaration_status", "MISSING")
    missing = payload.get("data_declaration_missing_fields", [])
    lines = ["## Data Declaration", ""]

    if declaration is None:
        lines += [
            "> ⚠️ **DATA DECLARATION MISSING — this report cannot vouch for data quality. "
            "Treat as SUSPECT.**",
            "",
        ]
        return lines

    if status == "INCOMPLETE":
        lines += [
            "> ⚠️ **DATA DECLARATION INCOMPLETE — missing critical fields: "
            f"{', '.join(missing)}. Treat as SUSPECT.**",
            "",
        ]

    if declaration.get("tier") == 0:
        lines += [f"> ⚠️ **{TIER_0_WARNING}**", ""]

    lines += [
        "| field | value |",
        "|---|---|",
        f"| tier | {declaration.get('tier', '—')} |",
        f"| survivorship_bias_status | {declaration.get('survivorship_bias_status', '—')} |",
        f"| corporate_actions_status | {declaration.get('corporate_actions_status', '—')} |",
        f"| pit_status | {declaration.get('pit_status', '—')} |",
        f"| data_declaration_id | {declaration.get('data_declaration_id', '—')} |",
        f"| universe_source | {declaration.get('universe_source', '—')} |",
        f"| data_feed | {declaration.get('data_feed', '—')} |",
        "",
    ]
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    """Render a human-readable Markdown summary from the report payload."""
    h = payload["headline_metrics"]
    nb = payload["null_battery"]
    lines = [
        f"# Backtest experiment {payload['run_id']}",
        "",
        f"- as_of: {payload['as_of']}",
        f"- seed: {payload['seed']}",
        f"- config_hash: {payload['config_hash']}",
        f"- weight_source: {payload['weight_source']}",
        "",
        *_render_data_declaration(payload),
        "## Headline metrics",
        "",
        "| metric | value |",
        "|---|---|",
        f"| sharpe | {h['sharpe']:.4f} |",
        f"| sortino | {h['sortino']:.4f} |",
        f"| max_drawdown | {h['max_drawdown']:.4f} |",
        f"| annual_turnover | {h['annual_turnover']:.4f} |",
        f"| total_return | {h['total_return']:.4f} |",
        f"| cagr | {h['cagr']:.4f} |",
        f"| n_periods | {h['n_periods']} |",
        "",
        "## Null-model battery (advisory diagnostics — the human decides)",
        "",
        "| variant | sharpe | total_return |",
        "|---|---|---|",
        f"| baseline | {nb['baseline']['sharpe']:.4f} | {nb['baseline']['total_return']:.4f} |",
        f"| random | {nb['random_weights']['sharpe']:.4f} | "
        f"{nb['random_weights']['total_return']:.4f} |",
        f"| shuffled | {nb['shuffled_weights']['sharpe']:.4f} | "
        f"{nb['shuffled_weights']['total_return']:.4f} |",
        f"| shifted | {nb['shifted_weights']['sharpe']:.4f} | "
        f"{nb['shifted_weights']['total_return']:.4f} |",
        f"| future_leak | {nb['future_leak']['sharpe']:.4f} | "
        f"{nb['future_leak']['total_return']:.4f} |",
        f"| cost_stress_2x | {nb['cost_stress_2x']['sharpe']:.4f} | "
        f"{nb['cost_stress_2x']['total_return']:.4f} |",
        f"| cost_stress_5x | {nb['cost_stress_5x']['sharpe']:.4f} | "
        f"{nb['cost_stress_5x']['total_return']:.4f} |",
        "",
        "### Verdicts",
        "",
        f"- future_leak_detected: {nb['future_leak_detected']}",
        f"- random_near_zero: {nb['random_near_zero']}",
        f"- shuffled_near_zero: {nb['shuffled_near_zero']}",
        "",
        "_No trading, no model training, no live execution, no order submission._",
        "",
    ]
    return "\n".join(lines)


def write_report(payload: dict[str, Any], report_dir: str | Path) -> ReportPaths:
    """Write JSON (canonical) and Markdown (human) reports under report_dir."""
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = payload["run_id"]
    json_path = out_dir / f"experiment_{run_id}.json"
    markdown_path = out_dir / f"experiment_{run_id}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    markdown_path.write_text(render_markdown(payload))
    return ReportPaths(json_path=json_path, markdown_path=markdown_path)
