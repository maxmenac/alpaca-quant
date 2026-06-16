"""Phase 4C dataset manifest: lineage, null accounting, eligibility, fingerprint, verdict.

Non-secret, deterministic, local-only. Records what was assembled and how safe it is. It does
not train, score, optimize, or trade. SUSPECT (not OK) is reported whenever the anti-leakage
contract is only partially provable; ambiguous data is never silently coerced into safe data.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import polars as pl

from alpaca_quant.research.data_contract import FeatureSpec
from alpaca_quant.research.pit_joins import (
    UNIVERSE_STATUS_COL,
)
from alpaca_quant.research.targets import TIMESTAMP_COL, TargetManifest

DATASET_MANIFEST_SCHEMA_VERSION = 1

# Column names produced by ml_dataset (kept as literals to avoid a circular import).
_FEATURE_CUTOFF_COL = "feature_cutoff_time"
_ELIGIBLE_COL = "eligible"
_ELIGIBILITY_REASON_COL = "eligibility_reason"

BOUNDARY_STATEMENT = (
    "Phase 4C assembles a point-in-time-safe (X, y) dataset only. It performs NO model training, "
    "no fit/transform, no cross-validation, no alpha/signal/weight generation, no portfolio "
    "construction, no optimization, no backtest, and no trading. Split definitions are index "
    "sets prepared for a future phase and train nothing here."
)
ADJUSTED_CLOSE_CAVEAT = (
    "Return labels are back-adjustment invariant when computed consistently, but price-level "
    "features are unsafe if they use back-adjusted prices after future splits/dividends. Such "
    "features must be declared pit_safe or are rejected/marked SUSPECT — never silently trusted."
)


# Declared corporate-action / adjustment statuses that count as unambiguous and safe. Anything
# else — including partial / best_effort / unknown / an absent declaration — is treated as
# ambiguous. We carry the DECLARED value through verbatim and never infer or assign one.
CLEAN_ADJUSTMENT_STATUSES: frozenset[str] = frozenset(
    {"full", "complete", "none_needed", "not_applicable", "not_required"}
)


class DatasetManifestError(RuntimeError):
    """Raised when a dataset manifest cannot be built or rendered safely."""


def read_declared_adjustment_status(
    declaration: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Return the verbatim declared (corporate_actions_status, adjustment_status), no inference."""
    if declaration is None:
        return None, None
    if not isinstance(declaration, Mapping):
        raise DatasetManifestError("data_declaration must be a mapping or None")
    # The declaration may be wrapped under a top-level 'data_declaration' key (repo convention).
    inner = declaration.get("data_declaration", declaration)
    if not isinstance(inner, Mapping):
        inner = declaration
    corporate = inner.get("corporate_actions_status")
    adjustment = inner.get("adjustment_status", inner.get("price_adjustment"))
    corporate = str(corporate) if corporate is not None else None
    adjustment = str(adjustment) if adjustment is not None else None
    return corporate, adjustment


def adjustment_declaration_is_ambiguous(
    corporate_status: str | None,
    adjustment_status: str | None,
) -> bool:
    """An absent or non-clean declared status is ambiguous (conservative; never silently OK)."""
    statuses = [s for s in (corporate_status, adjustment_status) if s is not None]
    if not statuses:
        return True
    return any(str(s).strip().lower() not in CLEAN_ADJUSTMENT_STATUSES for s in statuses)


@dataclass(frozen=True)
class DatasetManifest:
    """Non-secret lineage + quality manifest for an assembled ML dataset."""

    schema_version: int
    generated_at_utc: str
    dataset_id: str
    fingerprint: str
    verdict: str
    id_column: str
    source_label_fingerprint: str | None
    target_columns: list[str]
    label_horizons: dict[str, int]
    feature_columns: list[str]
    feature_availability: list[dict[str, Any]]
    suspect_features: list[str]
    reference_value_columns: list[str]
    row_count: int
    eligible_row_count: int
    excluded_by_reason: dict[str, int]
    null_matrix: dict[str, dict[str, Any]]
    universe_coverage: dict[str, int]
    asof_join_summary: dict[str, Any]
    split_definitions: list[dict[str, Any]]
    config_hash: str
    warnings: list[dict[str, Any]]
    declared_corporate_actions_status: str | None = None
    declared_adjustment_status: str | None = None
    timezone_alignment: dict[str, Any] = field(default_factory=dict)
    boundary_statement: str = BOUNDARY_STATEMENT
    adjusted_close_caveat: str = ADJUSTED_CLOSE_CAVEAT
    no_model_training: bool = True
    no_cross_validation: bool = True
    no_alpha: bool = True
    no_signal: bool = True
    no_weights: bool = True
    no_optimizer: bool = True
    no_backtest: bool = True
    no_trading: bool = True
    split_definitions_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def fingerprint_dataset(
    frame: pl.DataFrame,
    *,
    id_column: str,
    feature_columns: Sequence[str],
    label_columns: Sequence[str],
) -> str:
    """Deterministic sha256 over the dataset content, stable under row reordering."""
    columns = [id_column, TIMESTAMP_COL, *feature_columns, *label_columns]
    present = [c for c in columns if c in frame.columns]
    ordered = frame.sort([id_column, TIMESTAMP_COL], maintain_order=True).select(present)
    rows = []
    for row in ordered.iter_rows(named=True):
        encoded = {}
        for column in present:
            value = row[column]
            if column == TIMESTAMP_COL:
                encoded[column] = _canonical_timestamp(value)
            else:
                encoded[column] = value
        rows.append(encoded)
    canonical = json.dumps(
        {
            "schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
            "id_column": id_column,
            "feature_columns": list(feature_columns),
            "label_columns": list(label_columns),
            "rows": rows,
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _config_hash(payload: Mapping[str, Any] | None) -> str:
    canonical = json.dumps(
        payload or {}, allow_nan=False, separators=(",", ":"), sort_keys=True, default=str
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _null_matrix(
    frame: pl.DataFrame,
    columns: Sequence[str],
    *,
    eligible_mask: pl.Series,
) -> dict[str, dict[str, Any]]:
    total = frame.height
    eligible_total = int(eligible_mask.sum())
    matrix: dict[str, dict[str, Any]] = {}
    eligible_frame = frame.filter(eligible_mask)
    for column in columns:
        if column not in frame.columns:
            continue
        null_count = frame[column].null_count()
        eligible_null = (
            eligible_frame[column].null_count() if eligible_total else 0
        )
        matrix[column] = {
            "null_count": int(null_count),
            "null_fraction": (null_count / total) if total else 0.0,
            "eligible_null_count": int(eligible_null),
            "eligible_null_fraction": (
                (eligible_null / eligible_total) if eligible_total else 0.0
            ),
        }
    return matrix


def _warning(code: str, message: str, *, severity: str = "WARNING") -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message}


def build_dataset_manifest(
    frame: pl.DataFrame,
    *,
    id_column: str,
    feature_specs: Sequence[FeatureSpec],
    feature_columns: Sequence[str],
    label_columns: Sequence[str],
    label_horizons: Mapping[str, int],
    reference_value_columns: Sequence[str],
    target_manifest: TargetManifest | Mapping[str, Any] | None,
    universe_provided: bool,
    identity_provided: bool,
    suspect_features: Sequence[str],
    synthetic_no_universe: bool,
    max_feature_null_fraction: float,
    max_label_null_fraction: float,
    availability_summary: Sequence[dict[str, Any]],
    asof_summary: Mapping[str, Any],
    split_definitions: Sequence[Mapping[str, Any]] | None = None,
    config_payload: Mapping[str, Any] | None = None,
    data_declaration: Mapping[str, Any] | None = None,
    timezone_alignment: Mapping[str, Any] | None = None,
    clock: Any | None = None,
) -> DatasetManifest:
    """Build a non-secret dataset manifest with null accounting, lineage, and a SUSPECT verdict."""
    for column in (_ELIGIBLE_COL, _ELIGIBILITY_REASON_COL):
        if column not in frame.columns:
            raise DatasetManifestError(f"assembled frame is missing {column!r}")

    eligible_mask = frame[_ELIGIBLE_COL]
    row_count = frame.height
    eligible_count = int(eligible_mask.sum())

    excluded = (
        frame.filter(~eligible_mask)
        .group_by(_ELIGIBILITY_REASON_COL)
        .len()
        .sort(_ELIGIBILITY_REASON_COL)
    )
    excluded_by_reason = {
        str(row[_ELIGIBILITY_REASON_COL]): int(row["len"]) for row in excluded.to_dicts()
    }

    universe_coverage = {
        str(row[UNIVERSE_STATUS_COL]): int(row["len"])
        for row in frame.group_by(UNIVERSE_STATUS_COL).len().sort(UNIVERSE_STATUS_COL).to_dicts()
    }

    null_matrix = _null_matrix(
        frame, [*feature_columns, *label_columns, *reference_value_columns],
        eligible_mask=eligible_mask,
    )

    # Lineage to Phase 4A.
    if isinstance(target_manifest, TargetManifest):
        source_fingerprint = target_manifest.fingerprint
    elif isinstance(target_manifest, Mapping):
        source_fingerprint = target_manifest.get("fingerprint")
    else:
        source_fingerprint = None

    fingerprint = fingerprint_dataset(
        frame,
        id_column=id_column,
        feature_columns=feature_columns,
        label_columns=label_columns,
    )
    digest = fingerprint.removeprefix("sha256:")

    # Carry the DECLARED corporate-action / adjustment status through verbatim (no inference).
    declared_corporate_status, declared_adjustment_status = read_declared_adjustment_status(
        data_declaration
    )

    warnings: list[dict[str, Any]] = []
    if adjustment_declaration_is_ambiguous(declared_corporate_status, declared_adjustment_status):
        warnings.append(
            _warning(
                "ambiguous_adjustment_declaration",
                "Declared corporate-action/adjustment status is absent or not unambiguously "
                f"clean (corporate_actions_status={declared_corporate_status!r}, "
                f"adjustment_status={declared_adjustment_status!r}); adjustment safety cannot be "
                "assumed. Declared value carried through verbatim; nothing inferred.",
            )
        )

    tz_alignment = dict(timezone_alignment or {})
    if tz_alignment.get("mismatch"):
        warnings.append(
            _warning(
                "feature_timezone_mismatch",
                "Feature source timezone "
                f"{tz_alignment.get('feature_timezone')!r} differs from bar timezone "
                f"{tz_alignment.get('bar_timezone')!r}; features were NOT joined and NO timezone "
                "conversion was performed. Re-stamping belongs to a future ingestion sprint.",
            )
        )

    if not universe_provided:
        if synthetic_no_universe:
            warnings.append(
                _warning(
                    "no_universe_synthetic_mode",
                    "No PIT universe supplied (synthetic/no-universe mode); survivorship and "
                    "anti-leakage universe checks are NOT enforced.",
                )
            )
        else:
            warnings.append(
                _warning(
                    "missing_universe",
                    "No PIT universe supplied and synthetic mode is off; all rows are "
                    "no_universe_data and ineligible.",
                )
            )
    if not identity_provided:
        warnings.append(
            _warning(
                "missing_symbol_identity",
                "No symbol identity table supplied; permanent_id falls back to the raw id and "
                "ticker changes / M&A cannot be tracked.",
            )
        )
    if suspect_features:
        warnings.append(
            _warning(
                "ambiguous_price_adjustment",
                "Price-level features with unknown adjustment provenance: "
                f"{list(suspect_features)}. Treated as SUSPECT, not safe.",
            )
        )

    # Null-coverage gates.
    for column in label_columns:
        stats = null_matrix.get(column)
        if stats and stats["null_fraction"] > max_label_null_fraction:
            warnings.append(
                _warning(
                    "excessive_label_nulls",
                    f"label {column!r} is {stats['null_fraction']:.1%} null "
                    f"(> {max_label_null_fraction:.0%}).",
                )
            )
    for column in feature_columns:
        stats = null_matrix.get(column)
        if stats and stats["null_fraction"] > max_feature_null_fraction:
            warnings.append(
                _warning(
                    "excessive_feature_nulls",
                    f"feature {column!r} is {stats['null_fraction']:.1%} null "
                    f"(> {max_feature_null_fraction:.0%}).",
                )
            )

    # Incomplete reference coverage.
    for column, info in asof_summary.get("columns", {}).items():
        if info.get("present") and info.get("unmatched", 0) > 0:
            warnings.append(
                _warning(
                    "incomplete_reference_coverage",
                    f"reference value {column!r} unmatched for {info['unmatched']} rows "
                    "(no available_at <= timestamp).",
                    severity="INFO",
                )
            )

    warnings.append(
        _warning("adjusted_close_caveat", ADJUSTED_CLOSE_CAVEAT, severity="INFO")
    )

    verdict = (
        "SUSPECT"
        if any(item["severity"] == "WARNING" for item in warnings)
        else "OK"
    )

    generated = (clock or (lambda: datetime.now(UTC)))()
    generated_iso = generated.isoformat() if hasattr(generated, "isoformat") else str(generated)

    return DatasetManifest(
        schema_version=DATASET_MANIFEST_SCHEMA_VERSION,
        generated_at_utc=generated_iso,
        dataset_id=f"ds-{digest[:12]}",
        fingerprint=fingerprint,
        verdict=verdict,
        id_column=id_column,
        source_label_fingerprint=source_fingerprint,
        target_columns=list(label_columns),
        label_horizons=dict(label_horizons),
        feature_columns=list(feature_columns),
        feature_availability=list(availability_summary),
        suspect_features=list(suspect_features),
        reference_value_columns=list(reference_value_columns),
        row_count=row_count,
        eligible_row_count=eligible_count,
        excluded_by_reason=excluded_by_reason,
        null_matrix=null_matrix,
        universe_coverage=universe_coverage,
        asof_join_summary=dict(asof_summary),
        split_definitions=[dict(item) for item in (split_definitions or [])],
        config_hash=_config_hash(config_payload),
        warnings=warnings,
        declared_corporate_actions_status=declared_corporate_status,
        declared_adjustment_status=declared_adjustment_status,
        timezone_alignment=tz_alignment,
    )


def render_dataset_manifest_markdown(manifest: DatasetManifest | Mapping[str, Any]) -> str:
    """Render a compact human-readable dataset manifest report."""
    data = manifest.to_dict() if isinstance(manifest, DatasetManifest) else dict(manifest)
    if data.get("schema_version") != DATASET_MANIFEST_SCHEMA_VERSION:
        raise DatasetManifestError("unsupported or missing dataset manifest schema_version")

    lines = [
        "# ML Dataset Manifest (Phase 4C)",
        "",
        f"> **Verdict: {data['verdict']}**",
        "",
        "## Lineage",
        "",
        "| field | value |",
        "|---|---|",
        f"| generated_at_utc | {data['generated_at_utc']} |",
        f"| dataset_id | {data['dataset_id']} |",
        f"| fingerprint | {data['fingerprint']} |",
        f"| source_label_fingerprint | {data.get('source_label_fingerprint') or '—'} |",
        f"| id_column | {data['id_column']} |",
        f"| config_hash | {data['config_hash']} |",
        f"| target_columns | {', '.join(data['target_columns'])} |",
        f"| feature_columns | {', '.join(data['feature_columns']) or '—'} |",
        "",
        "## Row Accounting",
        "",
        f"- rows: {data['row_count']}",
        f"- eligible: {data['eligible_row_count']}",
    ]
    for reason, count in sorted(data["excluded_by_reason"].items()):
        lines.append(f"- excluded · {reason}: {count}")

    lines += ["", "## Universe Coverage", ""]
    for status, count in sorted(data["universe_coverage"].items()):
        lines.append(f"- {status}: {count}")

    lines += [
        "",
        "## Null Matrix",
        "",
        "| column | null | null_pct | eligible_null | eligible_null_pct |",
        "|---|---:|---:|---:|---:|",
    ]
    for column, stats in data["null_matrix"].items():
        lines.append(
            f"| {column} | {stats['null_count']} | {stats['null_fraction']:.3f} | "
            f"{stats['eligible_null_count']} | {stats['eligible_null_fraction']:.3f} |"
        )

    lines += ["", "## Feature Availability Contract", ""]
    lines.append("| feature | price_level | adjustment | availability | lag | class |")
    lines.append("|---|:--:|---|---|---:|---|")
    for spec in data["feature_availability"]:
        lines.append(
            f"| {spec['name']} | {spec['price_level']} | {spec['adjustment']} | "
            f"{spec['availability']} | {spec['lag_bars']} | {spec['safety_class']} |"
        )

    lines += [
        "",
        "## Declared Provenance (carried verbatim — never inferred)",
        "",
        f"- corporate_actions_status: {data.get('declared_corporate_actions_status') or '—'}",
        f"- adjustment_status: {data.get('declared_adjustment_status') or '—'}",
    ]

    if data["split_definitions"]:
        lines += ["", "## Split Definitions (index sets only — no CV, no training)", ""]
        for split in data["split_definitions"]:
            lines.append(
                f"- horizon={split.get('max_horizon')} embargo={split.get('embargo')} "
                f"train={split.get('n_train')} val={split.get('n_validation')} "
                f"test={split.get('n_test')} purged={split.get('purged_count')} "
                f"embargoed={split.get('embargoed_count')}"
            )

    lines += ["", "## Warnings", ""]
    if data["warnings"]:
        for item in data["warnings"]:
            lines.append(f"- **{item['severity']} · {item['code']}**: {item['message']}")
    else:
        lines.append("- None.")

    lines += [
        "",
        "## Safety Boundary",
        "",
        data["boundary_statement"],
        "",
        data["adjusted_close_caveat"],
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "BOUNDARY_STATEMENT",
    "ADJUSTED_CLOSE_CAVEAT",
    "DATASET_MANIFEST_SCHEMA_VERSION",
    "DatasetManifest",
    "DatasetManifestError",
    "build_dataset_manifest",
    "fingerprint_dataset",
    "render_dataset_manifest_markdown",
]
