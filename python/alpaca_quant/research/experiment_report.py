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

# Engine-sanity checks (RESEARCH_PROTOCOL.md §2): these decide whether the BACKTESTER is
# trustworthy. cost_stress / shifted are informational robustness diagnostics, displayed but not
# gating report health.
CORE_BATTERY_CHECKS = ("random_signal", "shuffled_labels", "future_leak_trap")

# Fail-closed: a report missing any of these cannot be rendered or written. These are the fields
# that make a report auditable and registry-linked (RESEARCH_PROTOCOL.md §1). Missing OPTIONAL
# fields degrade to UNKNOWN; missing CRITICAL fields raise loudly.
CRITICAL_REPORT_FIELDS = (
    "run_id",
    "config_hash",
    "report_health",
    "headline_metrics",
    "reproducibility",
)
# Within the reproducibility block, the minimum needed to identify/replay a run.
CRITICAL_REPRODUCIBILITY_FIELDS = ("run_id", "created_at", "config_hash")
UNKNOWN = "UNKNOWN"


class ExperimentReportError(RuntimeError):
    """Raised when a report cannot be assembled, validated, or written safely (fail-closed)."""


@dataclass(frozen=True)
class ReportPaths:
    json_path: Path
    markdown_path: Path


def summarize_null_battery(null_battery: Mapping[str, Any] | None) -> dict[str, Any]:
    """Summarize the null-model battery into PASS/FAIL/UNKNOWN verdicts (report layer only).

    Pure summarization of EXISTING diagnostics — no engine change, no strategy logic. The
    future-leak trap is special: it tests the backtester itself. If it did not explode, the
    engine (or the trap) is suspect and `engine_suspect` is True.
    """
    unknown_verdicts = dict.fromkeys(
        (
            "random_signal",
            "shifted_signal",
            "future_leak_trap",
            "shuffled_labels",
            "cost_stress_2x",
            "cost_stress_5x",
        ),
        "UNKNOWN",
    )
    if not null_battery:
        return {
            "available": False,
            "verdicts": unknown_verdicts,
            "future_leak_exploded": None,
            "engine_suspect": False,
        }

    def _flag_verdict(flag: object) -> str:
        return "PASS" if bool(flag) else "FAIL"

    baseline_sharpe = null_battery.get("baseline", {}).get("sharpe")
    shifted_sharpe = null_battery.get("shifted_weights", {}).get("sharpe")

    def _shifted_verdict() -> str:
        # Shifting weights into the past must not IMPROVE the edge (RESEARCH_PROTOCOL §2).
        if baseline_sharpe is None or shifted_sharpe is None:
            return "UNKNOWN"
        return "PASS" if shifted_sharpe <= baseline_sharpe else "FAIL"

    def _cost_verdict(variant: str) -> str:
        total_return = null_battery.get(variant, {}).get("total_return")
        if total_return is None:
            return "UNKNOWN"
        return "PASS" if total_return > 0 else "FAIL"

    leak_exploded = bool(null_battery.get("future_leak_detected", False))
    verdicts = {
        "random_signal": _flag_verdict(null_battery.get("random_near_zero", False)),
        "shifted_signal": _shifted_verdict(),
        "future_leak_trap": _flag_verdict(leak_exploded),
        "shuffled_labels": _flag_verdict(null_battery.get("shuffled_near_zero", False)),
        "cost_stress_2x": _cost_verdict("cost_stress_2x"),
        "cost_stress_5x": _cost_verdict("cost_stress_5x"),
    }
    return {
        "available": True,
        "verdicts": verdicts,
        "future_leak_exploded": leak_exploded,
        "engine_suspect": not leak_exploded,
    }


def compute_report_health(
    declaration_status: str,
    battery_summary: Mapping[str, Any],
) -> str:
    """Resolve overall report health: OK | SUSPECT | ENGINE_SUSPECT.

    Precedence: a suspect engine invalidates everything, so ENGINE_SUSPECT wins. Otherwise an
    incomplete declaration or an incomplete/failing core battery is SUSPECT. Only a complete
    declaration plus a passing core battery yields OK.
    """
    if battery_summary.get("available") and battery_summary.get("engine_suspect"):
        return "ENGINE_SUSPECT"
    if not battery_summary.get("available"):
        return "SUSPECT"
    verdicts = battery_summary.get("verdicts", {})
    if any(verdicts.get(check) != "PASS" for check in CORE_BATTERY_CHECKS):
        return "SUSPECT"
    if declaration_status != "COMPLETE":
        return "SUSPECT"
    return "OK"


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


def build_reproducibility(
    *,
    run_id: str,
    config_hash: str,
    seed: int,
    weight_source: str,
    created_at: str | None,
    git_sha: str | None,
    dataset_id: str | None,
    feature_set_id: str | None,
    data_declaration_id: str | None,
    weights_path: str | None,
    cost_config_path: str | None,
) -> dict[str, Any]:
    """Assemble the reproducibility fingerprint. Optional fields degrade to UNKNOWN, never faked.

    A run is reproducible from git_sha + dataset/data_version + config_hash + seed + the weights
    input (RESEARCH_PROTOCOL.md §1). Critical identity fields (run_id, created_at, config_hash)
    are left as-is here and enforced by validate_report_payload — this builder never invents them.
    """

    def _opt(value: object) -> object:
        return value if value not in (None, "") else UNKNOWN

    return {
        "run_id": run_id,
        "created_at": created_at,
        "config_hash": config_hash,
        "seed": seed,
        "git_sha": _opt(git_sha),
        "dataset_id": _opt(dataset_id),
        "data_declaration_id": _opt(data_declaration_id),
        "feature_set_id": _opt(feature_set_id),
        "weight_source": _opt(weight_source),
        "weights_path": _opt(weights_path),
        "cost_config_path": _opt(cost_config_path),
    }


def validate_report_payload(payload: Mapping[str, Any]) -> None:
    """Fail-closed report validation. Raises ExperimentReportError if a critical field is missing.

    Critical fields make the report auditable and registry-linked. Never silently substitutes
    defaults — a report that cannot identify or replay its run must not be produced.
    """
    missing = [
        field
        for field in CRITICAL_REPORT_FIELDS
        if payload.get(field) in (None, "", {}, [])
    ]
    if missing:
        raise ExperimentReportError(
            f"report is missing critical field(s): {', '.join(missing)}"
        )
    reproducibility = payload.get("reproducibility", {})
    repro_missing = [
        field
        for field in CRITICAL_REPRODUCIBILITY_FIELDS
        if reproducibility.get(field) in (None, "", UNKNOWN)
    ]
    if repro_missing:
        raise ExperimentReportError(
            f"reproducibility block is missing critical field(s): {', '.join(repro_missing)}"
        )


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
    created_at: str | None = None,
    git_sha: str | None = None,
    dataset_id: str | None = None,
    feature_set_id: str | None = None,
    cost_config_path: str | None = None,
) -> dict[str, Any]:
    """Assemble the canonical, JSON-serializable report payload."""
    m = backtest_result.metrics
    declaration = dict(data_declaration) if data_declaration is not None else None
    declaration_summary = summarize_data_declaration(declaration)
    battery_dict = battery_report.as_dict()
    battery_summary = summarize_null_battery(battery_dict)
    report_health = compute_report_health(declaration_summary["status"], battery_summary)
    reproducibility = build_reproducibility(
        run_id=run_id,
        config_hash=config_hash,
        seed=seed,
        weight_source=weight_source,
        created_at=created_at,
        git_sha=git_sha,
        dataset_id=dataset_id,
        feature_set_id=feature_set_id,
        data_declaration_id=(declaration or {}).get("data_declaration_id"),
        weights_path=config.get("weights_path"),
        cost_config_path=cost_config_path,
    )
    return {
        "run_id": run_id,
        "as_of": as_of,
        "seed": seed,
        "config": config,
        "config_hash": config_hash,
        "weight_source": weight_source,
        "report_health": report_health,
        "reproducibility": reproducibility,
        "data_declaration": declaration,
        "data_declaration_status": declaration_summary["status"],
        "data_declaration_missing_fields": declaration_summary["missing_fields"],
        "null_battery_summary": battery_summary,
        "headline_metrics": {
            "sharpe": m.sharpe,
            "sortino": m.sortino,
            "max_drawdown": m.max_drawdown,
            "annual_turnover": m.annual_turnover,
            "total_return": m.total_return,
            "cagr": m.cagr,
            "n_periods": m.n_periods,
        },
        "null_battery": battery_dict,
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


def _render_report_health(payload: dict[str, Any]) -> list[str]:
    """Render the top-of-report health banner (shown before everything else)."""
    health = payload.get("report_health", "SUSPECT")
    if health == "OK":
        return ["> ✅ **Report health: OK**", ""]
    if health == "ENGINE_SUSPECT":
        return [
            "> 🛑 **Report health: ENGINE_SUSPECT — the future-leak trap did NOT explode. The "
            "backtester itself is suspect; do not trust any result until the engine is fixed.**",
            "",
        ]
    return [
        "> ⚠️ **Report health: SUSPECT — data declaration and/or null battery is "
        "missing or incomplete. Treat results with caution.**",
        "",
    ]


def _render_null_battery_verdict(payload: dict[str, Any]) -> list[str]:
    """Render the Null Battery Verdict section (engine sanity, near the top)."""
    summary = payload.get("null_battery_summary") or {}
    verdicts = summary.get("verdicts", {})
    lines = ["## Null Battery Verdict", ""]
    if not summary.get("available", False):
        lines += [
            "> ⚠️ **Null-battery diagnostics unavailable — verdict UNKNOWN. Treat as SUSPECT.**",
            "",
        ]
        return lines
    if summary.get("engine_suspect", False):
        lines += [
            "> 🛑 **ENGINE_SUSPECT — the future-leak trap did not explode as expected.**",
            "",
        ]
    lines += [
        "| check | verdict |",
        "|---|---|",
        f"| random signal | {verdicts.get('random_signal', 'UNKNOWN')} |",
        f"| shifted signal | {verdicts.get('shifted_signal', 'UNKNOWN')} |",
        f"| future-leak trap | {verdicts.get('future_leak_trap', 'UNKNOWN')} |",
        f"| shuffled labels | {verdicts.get('shuffled_labels', 'UNKNOWN')} |",
        f"| cost stress ×2 | {verdicts.get('cost_stress_2x', 'UNKNOWN')} |",
        f"| cost stress ×5 | {verdicts.get('cost_stress_5x', 'UNKNOWN')} |",
        "",
    ]
    return lines


def _render_reproducibility(payload: dict[str, Any]) -> list[str]:
    """Render the Reproducibility section (audit + replay fingerprint, near the top)."""
    repro = payload.get("reproducibility") or {}
    lines = [
        "## Reproducibility",
        "",
        "| field | value |",
        "|---|---|",
        f"| run_id | {repro.get('run_id', UNKNOWN)} |",
        f"| created_at | {repro.get('created_at', UNKNOWN)} |",
        f"| as_of | {payload.get('as_of', UNKNOWN)} |",
        f"| git_sha | {repro.get('git_sha', UNKNOWN)} |",
        f"| dataset_id | {repro.get('dataset_id', UNKNOWN)} |",
        f"| data_declaration_id | {repro.get('data_declaration_id', UNKNOWN)} |",
        f"| feature_set_id | {repro.get('feature_set_id', UNKNOWN)} |",
        f"| config_hash | {repro.get('config_hash', UNKNOWN)} |",
        f"| seed | {repro.get('seed', UNKNOWN)} |",
        f"| weight_source | {repro.get('weight_source', UNKNOWN)} |",
        f"| weights_path | {repro.get('weights_path', UNKNOWN)} |",
        f"| cost_config_path | {repro.get('cost_config_path', UNKNOWN)} |",
        "",
    ]
    # Replay hint only when the replay-essential fields are all present (no faked command).
    essentials = (
        repro.get("git_sha"),
        repro.get("dataset_id"),
        repro.get("config_hash"),
        repro.get("seed"),
        repro.get("weights_path"),
    )
    if all(value not in (None, "", UNKNOWN) for value in essentials):
        lines += [
            "_Replay requires: git_sha + dataset/data_version + config_hash + seed + "
            "weights input._",
            "",
        ]
    return lines


def _render_regime_pnl() -> list[str]:
    """Render the explicit regime-analysis availability statement."""
    return [
        "## Regime PnL",
        "",
        "Regime PnL: not available in this report.",
        "",
    ]


def _render_plot_references() -> list[str]:
    """Render the explicit plot availability statement."""
    return [
        "## Plot References",
        "",
        "Plots: not generated for this report.",
        "",
    ]


def render_markdown(payload: dict[str, Any]) -> str:
    """Render a human-readable Markdown summary from the report payload (fail-closed)."""
    validate_report_payload(payload)
    h = payload["headline_metrics"]
    nb = payload["null_battery"]
    lines = [
        f"# Backtest experiment {payload['run_id']}",
        "",
        *_render_report_health(payload),
        *_render_reproducibility(payload),
        *_render_data_declaration(payload),
        *_render_null_battery_verdict(payload),
        "## Headline Metrics",
        "",
        "_Performance metrics are calculated from net returns after costs._",
        "",
        "| metric | value |",
        "|---|---|",
        f"| Sharpe net | {h['sharpe']:.4f} |",
        f"| Sortino net | {h['sortino']:.4f} |",
        f"| Max drawdown | {h['max_drawdown']:.4f} |",
        f"| Annual turnover | {h['annual_turnover']:.4f} |",
        f"| Total return net | {h['total_return']:.4f} |",
        f"| CAGR net | {h['cagr']:.4f} |",
        f"| Periods | {h['n_periods']} |",
        "",
        *_render_regime_pnl(),
        *_render_plot_references(),
        "## Null-model Battery Diagnostics",
        "",
        "_Advisory diagnostics; the human decides._",
        "",
        "| variant | Sharpe net | Total return net |",
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
        "## Safety Boundary",
        "",
        "_No trading, no model training, no live execution, no order submission._",
        "",
    ]
    return "\n".join(lines)


def write_report(payload: dict[str, Any], report_dir: str | Path) -> ReportPaths:
    """Write JSON (canonical) and Markdown (human) reports under report_dir (fail-closed)."""
    validate_report_payload(payload)
    out_dir = Path(report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = payload["run_id"]
    json_path = out_dir / f"experiment_{run_id}.json"
    markdown_path = out_dir / f"experiment_{run_id}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    markdown_path.write_text(render_markdown(payload))
    return ReportPaths(json_path=json_path, markdown_path=markdown_path)
