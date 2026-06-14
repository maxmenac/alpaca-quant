"""Build experiment reports (JSON canonical + Markdown human-readable).

Local-only, non-secret. The JSON is the machine-readable record of a backtest experiment; the
Markdown is a human summary. Diagnostics are advisory — the human reads and decides.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alpaca_quant.backtest.engine.engine import BacktestResult
from alpaca_quant.backtest.null_models import NullBatteryReport


@dataclass(frozen=True)
class ReportPaths:
    json_path: Path
    markdown_path: Path


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
) -> dict[str, Any]:
    """Assemble the canonical, JSON-serializable report payload."""
    m = backtest_result.metrics
    return {
        "run_id": run_id,
        "as_of": as_of,
        "seed": seed,
        "config": config,
        "config_hash": config_hash,
        "weight_source": weight_source,
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
