"""Phase 4D dataset inspection report: audit a Phase 4C dataset + feature registry metadata.

This report INSPECTS metadata and quality only. It computes no feature, trains no model, runs no
cross-validation, and produces no alpha, signal, strategy, weight, portfolio, optimizer,
backtest, or order. Its job is to surface — before any future ML work — whether a 4C dataset and
its requested feature set are safe to use, with a deterministic OK / SUSPECT / REJECTED verdict.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import polars as pl

from alpaca_quant.research.dataset_manifest import (
    DatasetManifest,
    adjustment_declaration_is_ambiguous,
)
from alpaca_quant.research.feature_registry import (
    VERDICT_OK,
    VERDICT_REJECTED,
    VERDICT_SUSPECT,
    FeatureRegistry,
    RegistryValidationConfig,
    validate_definition,
)
from alpaca_quant.research.ml_dataset import (
    ELIGIBILITY_REASON_COL,
    ELIGIBLE_COL,
)
from alpaca_quant.research.pit_joins import PERMANENT_ID_COL, UNIVERSE_STATUS_COL
from alpaca_quant.research.splits import (
    SplitDefinitionError,
    TemporalSplit,
    assert_split_disjoint_and_purged,
    split_summary,
)

DATASET_REPORT_SCHEMA_VERSION = 1
_VERDICT_RANK = {VERDICT_OK: 0, VERDICT_SUSPECT: 1, VERDICT_REJECTED: 2}

BOUNDARY_NOTE = (
    "This report inspects dataset and feature metadata only. It is not an alpha, signal, "
    "strategy, model, trading recommendation, or execution component."
)


class DatasetReportError(RuntimeError):
    """Raised when a dataset inspection report cannot be built or rendered safely."""


@dataclass(frozen=True)
class DatasetReportConfig:
    """Deterministic thresholds for the inspection report."""

    max_null_fraction: float = 0.5
    registry_config: RegistryValidationConfig | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.max_null_fraction) <= 1.0:
            raise DatasetReportError("max_null_fraction must be between 0 and 1")


def _reason(code: str, severity: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message}


def _as_manifest_dict(manifest: DatasetManifest | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(manifest, DatasetManifest):
        return manifest.to_dict()
    if isinstance(manifest, Mapping):
        return dict(manifest)
    raise DatasetReportError("manifest must be a DatasetManifest or mapping")


def _generated_at(clock: Any | None) -> str:
    value = (clock or (lambda: datetime.now(UTC)))()
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def build_dataset_inspection_report(
    frame: pl.DataFrame,
    *,
    manifest: DatasetManifest | Mapping[str, Any],
    registry: FeatureRegistry,
    requested_features: Sequence[str],
    splits: Sequence[TemporalSplit] = (),
    config: DatasetReportConfig | None = None,
    clock: Any | None = None,
) -> dict[str, Any]:
    """Build a deterministic inspection report with full reasons and a verdict."""
    resolved = config or DatasetReportConfig()
    manifest_data = _as_manifest_dict(manifest)
    id_column = manifest_data.get("id_column", "symbol")
    feature_columns = list(manifest_data.get("feature_columns", []))
    label_columns = list(manifest_data.get("target_columns", []))
    null_matrix = dict(manifest_data.get("null_matrix", {}))

    for column in (ELIGIBLE_COL, ELIGIBILITY_REASON_COL):
        if column not in frame.columns:
            raise DatasetReportError(f"dataset frame is missing {column!r}")

    reasons: list[dict[str, Any]] = []

    # --- feature safety table (registry verdicts) ---
    feature_safety: list[dict[str, Any]] = []
    requested = list(dict.fromkeys(requested_features))
    for name in requested:
        if not registry.has(name):
            reasons.append(
                _reason(
                    "missing_feature_metadata",
                    VERDICT_SUSPECT,
                    f"requested feature {name!r} has no registry definition.",
                )
            )
            feature_safety.append({"name": name, "verdict": VERDICT_SUSPECT, "in_registry": False})
            continue
        verdict = validate_definition(registry.get(name), config=resolved.registry_config)
        feature_safety.append(
            {
                "name": name,
                "verdict": verdict.verdict,
                "in_registry": True,
                "reasons": list(verdict.reasons),
            }
        )
        for item in verdict.reasons:
            reasons.append(
                _reason(
                    f"feature::{item['code']}",
                    item["severity"],
                    f"{name}: {item['message']}",
                )
            )

    # --- feature coverage table (registry vs dataset) ---
    feature_coverage: list[dict[str, Any]] = []
    total = frame.height
    for name in requested:
        in_dataset = name in frame.columns
        null_count = frame[name].null_count() if in_dataset else None
        feature_coverage.append(
            {
                "name": name,
                "in_registry": registry.has(name),
                "in_dataset": in_dataset,
                "null_count": int(null_count) if null_count is not None else None,
                "null_fraction": (null_count / total) if (in_dataset and total) else None,
            }
        )
        if not in_dataset:
            reasons.append(
                _reason(
                    "feature_missing_from_dataset",
                    VERDICT_SUSPECT,
                    f"requested feature {name!r} is absent from the dataset.",
                )
            )

    # dataset feature columns not declared in the requested registry set
    undeclared = sorted(set(feature_columns) - set(requested))
    for name in undeclared:
        reasons.append(
            _reason(
                "undeclared_dataset_column",
                VERDICT_SUSPECT,
                f"dataset feature column {name!r} is not in the requested registry feature set.",
            )
        )

    # --- null ratio gate (features + labels), no fill is ever applied ---
    for name in [*feature_columns, *label_columns]:
        stats = null_matrix.get(name)
        fraction = stats["null_fraction"] if stats else (
            (frame[name].null_count() / total) if (name in frame.columns and total) else 0.0
        )
        if fraction > resolved.max_null_fraction:
            reasons.append(
                _reason(
                    "null_ratio_above_threshold",
                    VERDICT_SUSPECT,
                    f"{name!r} null fraction {fraction:.1%} exceeds "
                    f"{resolved.max_null_fraction:.0%}.",
                )
            )

    # --- eligibility, universe, identity coverage (computed from the frame) ---
    eligible_count = int(frame[ELIGIBLE_COL].sum())
    ineligibility_reasons = {
        str(row[ELIGIBILITY_REASON_COL]): int(row["len"])
        for row in frame.filter(~pl.col(ELIGIBLE_COL))
        .group_by(ELIGIBILITY_REASON_COL)
        .len()
        .sort(ELIGIBILITY_REASON_COL)
        .to_dicts()
    }
    universe_coverage = {
        str(row[UNIVERSE_STATUS_COL]): int(row["len"])
        for row in frame.group_by(UNIVERSE_STATUS_COL).len().sort(UNIVERSE_STATUS_COL).to_dicts()
    } if UNIVERSE_STATUS_COL in frame.columns else {}
    if universe_coverage.get("no_universe_data", 0) > 0:
        reasons.append(
            _reason(
                "missing_pit_universe",
                VERDICT_SUSPECT,
                f"{universe_coverage['no_universe_data']} rows have no PIT universe coverage.",
            )
        )

    identity_used = False
    distinct_permanent_ids = None
    if PERMANENT_ID_COL in frame.columns and id_column in frame.columns:
        distinct_permanent_ids = int(frame[PERMANENT_ID_COL].n_unique())
        identity_used = bool((frame[PERMANENT_ID_COL] != frame[id_column]).any())
    if not identity_used:
        reasons.append(
            _reason(
                "missing_symbol_identity",
                VERDICT_SUSPECT,
                "no permanent_id mapping distinct from the raw id; identity coverage is absent.",
            )
        )

    # --- as-of join coverage (from manifest) + missing available_at semantics ---
    asof_summary = dict(manifest_data.get("asof_join_summary", {}))
    for column, info in asof_summary.get("columns", {}).items():
        if not info.get("present"):
            reasons.append(
                _reason(
                    "missing_available_at_semantics",
                    VERDICT_SUSPECT,
                    f"reference column {column!r} lacks available_at semantics.",
                )
            )

    # Standalone provenance flag: the source itself carries no availability time. We do NOT
    # synthesize or infer an available_at — absence is detected and reported only.
    has_available_at_column = "available_at" in frame.columns
    has_reference_availability = any(
        info.get("present") for info in asof_summary.get("columns", {}).values()
    )
    if not has_available_at_column and not has_reference_availability:
        reasons.append(
            _reason(
                "missing_available_at_semantics",
                VERDICT_SUSPECT,
                "source carries no availability time; as-of provenance cannot be proven.",
            )
        )

    # --- split summaries (validate definitions only; NO CV is run) ---
    split_summaries: list[dict[str, Any]] = []
    for split in splits:
        try:
            assert_split_disjoint_and_purged(frame, split)
            split_summaries.append({**split_summary(split), "valid": True})
        except SplitDefinitionError as exc:
            split_summaries.append({**split_summary(split), "valid": False, "error": str(exc)})
            reasons.append(
                _reason(
                    "invalid_split_definition",
                    VERDICT_REJECTED,
                    f"split definition violates purge/embargo: {exc}",
                )
            )

    # Surface the manifest's DECLARED corporate-action / adjustment status (carried verbatim).
    # Ambiguous or absent provenance is SUSPECT regardless of whether a price-level feature exists.
    if adjustment_declaration_is_ambiguous(
        manifest_data.get("declared_corporate_actions_status"),
        manifest_data.get("declared_adjustment_status"),
    ):
        reasons.append(
            _reason(
                "ambiguous_adjustment_declaration",
                VERDICT_SUSPECT,
                "declared corporate-action/adjustment status is absent or not unambiguously "
                f"clean (corporate_actions_status="
                f"{manifest_data.get('declared_corporate_actions_status')!r}); "
                "adjustment safety cannot be assumed.",
            )
        )

    # Feature/bar timezone mismatch (detected at assembly; carried verbatim, never converted).
    tz_alignment = dict(manifest_data.get("timezone_alignment", {}))
    if tz_alignment.get("mismatch"):
        reasons.append(
            _reason(
                "feature_timezone_mismatch",
                VERDICT_SUSPECT,
                f"feature timezone {tz_alignment.get('feature_timezone')!r} differs from bar "
                f"timezone {tz_alignment.get('bar_timezone')!r}; join refused, no conversion done.",
            )
        )

    # Surface ambiguous-adjustment suspects already recorded by the 4C manifest.
    for name in manifest_data.get("suspect_features", []):
        reasons.append(
            _reason(
                "ambiguous_adjustment_safety",
                VERDICT_SUSPECT,
                f"manifest flagged feature {name!r} as ambiguously adjusted.",
            )
        )

    # Deterministic, stable warning order so the report is reproducible across row/column orders.
    reasons.sort(key=lambda item: (item["code"], item["message"]))

    verdict = VERDICT_OK
    for item in reasons:
        if _VERDICT_RANK.get(item["severity"], 0) > _VERDICT_RANK[verdict]:
            verdict = item["severity"]

    return {
        "schema_version": DATASET_REPORT_SCHEMA_VERSION,
        "generated_at_utc": _generated_at(clock),
        "verdict": verdict,
        "dataset_id": manifest_data.get("dataset_id"),
        "dataset_fingerprint": manifest_data.get("fingerprint"),
        "source_label_fingerprint": manifest_data.get("source_label_fingerprint"),
        "feature_set_id": None,
        "id_column": id_column,
        "row_count": total,
        "eligible_row_count": eligible_count,
        "ineligible_row_count": total - eligible_count,
        "ineligibility_reasons": ineligibility_reasons,
        "feature_coverage": feature_coverage,
        "feature_safety": feature_safety,
        "null_matrix": null_matrix,
        "universe_coverage": universe_coverage,
        "asof_join_summary": asof_summary,
        "symbol_identity_coverage": {
            "identity_used": identity_used,
            "distinct_permanent_ids": distinct_permanent_ids,
        },
        "split_summaries": split_summaries,
        "warnings": reasons,
        "boundary_note": BOUNDARY_NOTE,
    }


def attach_feature_set_id(report: dict[str, Any], feature_set_id: str) -> dict[str, Any]:
    """Return a copy of the report with the registry feature_set_id recorded."""
    updated = dict(report)
    updated["feature_set_id"] = feature_set_id
    return updated


def _display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_dataset_inspection_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact human-readable inspection report with the verbatim boundary note."""
    if report.get("schema_version") != DATASET_REPORT_SCHEMA_VERSION:
        raise DatasetReportError("unsupported or missing dataset report schema_version")
    required = ("verdict", "feature_coverage", "feature_safety", "warnings", "boundary_note")
    for field_name in required:
        if field_name not in report:
            raise DatasetReportError(f"report is missing required field: {field_name}")

    lines = [
        "# Dataset Inspection Report (Phase 4D)",
        "",
        f"> **Verdict: {report['verdict']}**",
        "",
        "## Lineage",
        "",
        "| field | value |",
        "|---|---|",
        f"| generated_at_utc | {report['generated_at_utc']} |",
        f"| dataset_id | {_display(report.get('dataset_id'))} |",
        f"| dataset_fingerprint | {_display(report.get('dataset_fingerprint'))} |",
        f"| source_label_fingerprint | {_display(report.get('source_label_fingerprint'))} |",
        f"| feature_set_id | {_display(report.get('feature_set_id'))} |",
        "",
        "## Row Eligibility",
        "",
        f"- rows: {report.get('row_count')}",
        f"- eligible: {report.get('eligible_row_count')}",
        f"- ineligible: {report.get('ineligible_row_count')}",
    ]
    for reason, count in sorted(report.get("ineligibility_reasons", {}).items()):
        lines.append(f"- ineligible · {reason}: {count}")

    lines += [
        "",
        "## Feature Coverage",
        "",
        "| feature | in_registry | in_dataset | null | null_pct |",
        "|---|:--:|:--:|---:|---:|",
    ]
    for row in report["feature_coverage"]:
        lines.append(
            f"| {row['name']} | {row['in_registry']} | {row['in_dataset']} | "
            f"{_display(row['null_count'])} | {_display(row['null_fraction'])} |"
        )

    lines += [
        "",
        "## Feature Safety",
        "",
        "| feature | in_registry | verdict |",
        "|---|:--:|---|",
    ]
    for row in report["feature_safety"]:
        lines.append(f"| {row['name']} | {row.get('in_registry')} | {row['verdict']} |")

    lines += ["", "## PIT Universe Coverage", ""]
    for status, count in sorted(report.get("universe_coverage", {}).items()):
        lines.append(f"- {status}: {count}")

    lines += ["", "## As-of Join Coverage", ""]
    columns = report.get("asof_join_summary", {}).get("columns", {})
    if columns:
        for column, info in sorted(columns.items()):
            lines.append(f"- {column}: {_display(info)}")
    else:
        lines.append("- none")

    identity = report.get("symbol_identity_coverage", {})
    lines += [
        "",
        "## Symbol Identity Coverage",
        "",
        f"- identity_used: {identity.get('identity_used')}",
        f"- distinct_permanent_ids: {_display(identity.get('distinct_permanent_ids'))}",
    ]

    lines += ["", "## Split Summaries (definitions only — no CV, no training)", ""]
    if report.get("split_summaries"):
        for split in report["split_summaries"]:
            lines.append(
                f"- horizon={split.get('max_horizon')} embargo={split.get('embargo')} "
                f"train={split.get('n_train')} val={split.get('n_validation')} "
                f"test={split.get('n_test')} valid={split.get('valid')}"
            )
    else:
        lines.append("- none")

    lines += ["", "## Warnings", ""]
    if report["warnings"]:
        for item in report["warnings"]:
            lines.append(f"- **{item['severity']} · {item['code']}**: {item['message']}")
    else:
        lines.append("- None.")

    lines += ["", "## Safety Boundary", "", report["boundary_note"], ""]
    return "\n".join(lines)


__all__ = [
    "BOUNDARY_NOTE",
    "DATASET_REPORT_SCHEMA_VERSION",
    "DatasetReportConfig",
    "DatasetReportError",
    "attach_feature_set_id",
    "build_dataset_inspection_report",
    "render_dataset_inspection_markdown",
]
