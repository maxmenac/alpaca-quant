"""Local-only QA reports for Phase 4A forward-return labels.

This module audits label coverage, distributions, provenance, and manifest consistency. It does
not generate labels, alpha, signals, strategies, models, weights, portfolios, trades, or orders.
"""

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from statistics import fmean, stdev
from typing import Any

import polars as pl

from alpaca_quant.research.targets import (
    NULL_REASON_COL,
    SYMBOL_COL,
    TIMESTAMP_COL,
    TargetLabelError,
    TargetManifest,
    fingerprint_target_labels,
)

TARGET_REPORT_SCHEMA_VERSION = 1
SUPPORTED_MANIFEST_SCHEMA_VERSIONS = frozenset({1})
BOUNDARY_NOTE = (
    "This report audits labels only. It is not an alpha, signal, strategy, model, "
    "trading recommendation, or execution component."
)
UPSTREAM_DATA_WARNING = (
    "Adjusted close handling, point-in-time universe membership, and survivorship bias are "
    "upstream data-layer responsibilities; this label QA report does not repair or infer them."
)


class TargetReportError(RuntimeError):
    """Raised when a target QA report cannot be built safely."""


@dataclass(frozen=True, order=True)
class TargetDefinition:
    """One declared target column and its forward horizon."""

    horizon: int
    column: str


@dataclass(frozen=True)
class TargetReportConfig:
    """Deterministic thresholds and optional explicit target definitions."""

    targets: tuple[TargetDefinition, ...] | None = None
    max_null_pct: float = 20.0
    extreme_return_threshold: float = 1.0
    include_period_summary: bool = True
    max_symbols_with_distribution: int = 100


def _warning(
    code: str,
    message: str,
    *,
    severity: str = "WARNING",
    target_column: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if target_column is not None:
        item["target_column"] = target_column
    return item


def _normalize_config(
    config: TargetReportConfig | Mapping[str, Any] | None,
) -> TargetReportConfig:
    if config is None:
        resolved = TargetReportConfig()
    elif isinstance(config, TargetReportConfig):
        resolved = config
    elif isinstance(config, Mapping):
        raw_targets = config.get("targets")
        targets = None
        if raw_targets is not None:
            targets = tuple(_target_definition(item) for item in raw_targets)
        resolved = TargetReportConfig(
            targets=targets,
            max_null_pct=float(config.get("max_null_pct", 20.0)),
            extreme_return_threshold=float(config.get("extreme_return_threshold", 1.0)),
            include_period_summary=bool(config.get("include_period_summary", True)),
            max_symbols_with_distribution=int(
                config.get("max_symbols_with_distribution", 100)
            ),
        )
    else:
        raise TargetReportError("config must be TargetReportConfig, a mapping, or None")

    if not 0.0 <= resolved.max_null_pct <= 100.0:
        raise TargetReportError("max_null_pct must be between 0 and 100")
    if not math.isfinite(resolved.extreme_return_threshold):
        raise TargetReportError("extreme_return_threshold must be finite")
    if resolved.extreme_return_threshold <= 0:
        raise TargetReportError("extreme_return_threshold must be greater than zero")
    if resolved.max_symbols_with_distribution < 1:
        raise TargetReportError("max_symbols_with_distribution must be at least 1")
    if resolved.targets is not None:
        _validate_definitions(resolved.targets)
    return resolved


def _target_definition(value: object) -> TargetDefinition:
    if isinstance(value, TargetDefinition):
        return value
    if not isinstance(value, Mapping):
        raise TargetReportError("each target definition must be a mapping")
    horizon = value.get("horizon")
    column = value.get("column", value.get("label_column"))
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise TargetReportError("target horizon must be an integer of at least 1")
    if not isinstance(column, str) or not column.strip():
        raise TargetReportError("target column must be a non-empty string")
    return TargetDefinition(horizon=horizon, column=column.strip())


def _validate_definitions(definitions: Sequence[TargetDefinition]) -> None:
    if not definitions:
        raise TargetReportError("at least one target definition is required")
    columns = [definition.column for definition in definitions]
    horizons = [definition.horizon for definition in definitions]
    if len(columns) != len(set(columns)):
        raise TargetReportError("target definitions contain duplicate columns")
    if len(horizons) != len(set(horizons)):
        raise TargetReportError("target definitions contain duplicate horizons")


def _manifest_mapping(
    manifest: TargetManifest | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if manifest is None:
        return None
    if isinstance(manifest, TargetManifest):
        payload = manifest.to_dict()
        payload["schema_version"] = 1
        return payload
    if isinstance(manifest, Mapping):
        return dict(manifest)
    raise TargetReportError("manifest must be TargetManifest, a mapping, or None")


def _manifest_definitions(payload: Mapping[str, Any]) -> tuple[TargetDefinition, ...]:
    raw_version = payload.get("schema_version", 1)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        raise TargetReportError("manifest schema_version must be an integer")
    if raw_version not in SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        raise TargetReportError(f"unsupported target manifest schema_version: {raw_version}")

    if "targets" in payload:
        raw_targets = payload["targets"]
        if not isinstance(raw_targets, Sequence) or isinstance(raw_targets, (str, bytes)):
            raise TargetReportError("manifest targets must be a list")
        definitions = tuple(_target_definition(item) for item in raw_targets)
    else:
        if "horizon" not in payload or "label_column" not in payload:
            raise TargetReportError(
                "manifest must declare horizon and label_column, or a targets list"
            )
        definitions = (
            _target_definition(
                {
                    "horizon": payload["horizon"],
                    "label_column": payload["label_column"],
                }
            ),
        )
    _validate_definitions(definitions)
    return tuple(sorted(definitions))


def _inferred_definitions(df: pl.DataFrame) -> tuple[TargetDefinition, ...]:
    prefix = "label_forward_return_"
    definitions: list[TargetDefinition] = []
    for column in df.columns:
        if not column.startswith(prefix) or not column.endswith("d"):
            continue
        raw_horizon = column[len(prefix) : -1]
        if raw_horizon.isdigit() and int(raw_horizon) >= 1:
            definitions.append(TargetDefinition(horizon=int(raw_horizon), column=column))
    if not definitions:
        raise TargetReportError(
            "no target columns declared and no Phase 4A target columns could be inferred"
        )
    _validate_definitions(definitions)
    return tuple(sorted(definitions))


def _resolve_definitions(
    df: pl.DataFrame,
    manifest: Mapping[str, Any] | None,
    config: TargetReportConfig,
) -> tuple[TargetDefinition, ...]:
    manifest_targets = _manifest_definitions(manifest) if manifest is not None else None
    config_targets = tuple(sorted(config.targets)) if config.targets is not None else None
    if manifest_targets is not None and config_targets is not None:
        if manifest_targets != config_targets:
            raise TargetReportError("manifest and report config target definitions disagree")
        definitions = manifest_targets
    elif manifest_targets is not None:
        definitions = manifest_targets
    elif config_targets is not None:
        definitions = config_targets
    else:
        definitions = _inferred_definitions(df)

    missing = [definition.column for definition in definitions if definition.column not in df]
    if missing:
        raise TargetReportError(
            f"labelled data is missing required target column(s): {', '.join(missing)}"
        )
    return definitions


def _validate_frame(df: pl.DataFrame, definitions: Sequence[TargetDefinition]) -> None:
    if df.is_empty():
        raise TargetReportError("labelled data is empty")
    missing = [column for column in (SYMBOL_COL, TIMESTAMP_COL) if column not in df]
    if missing:
        raise TargetReportError(
            f"labelled data is missing required column(s): {', '.join(missing)}"
        )
    if df[SYMBOL_COL].null_count() > 0 or df[TIMESTAMP_COL].null_count() > 0:
        raise TargetReportError("symbol and timestamp columns must not contain nulls")
    if df.select([SYMBOL_COL, TIMESTAMP_COL]).is_duplicated().any():
        raise TargetReportError("labelled data contains duplicate symbol/timestamp rows")
    if not df.schema[TIMESTAMP_COL].is_temporal():
        raise TargetReportError("timestamp column must use a date or datetime type")
    for definition in definitions:
        if not df.schema[definition.column].is_numeric():
            raise TargetReportError(
                f"target column {definition.column!r} must use a numeric dtype"
            )


def _finite_and_non_finite(values: Sequence[object]) -> tuple[list[float], int, int]:
    finite: list[float] = []
    n_null = 0
    n_non_finite = 0
    for value in values:
        if value is None:
            n_null += 1
            continue
        number = float(value)
        if math.isfinite(number):
            finite.append(number)
        else:
            n_non_finite += 1
    return finite, n_null, n_non_finite


def _quantile(sorted_values: Sequence[float], probability: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _distribution(values: Sequence[object]) -> dict[str, Any]:
    finite, n_null, n_non_finite = _finite_and_non_finite(values)
    ordered = sorted(finite)
    n_total = len(values)
    return {
        "n_total": n_total,
        "n_valid": len(finite),
        "n_null": n_null,
        "n_non_finite": n_non_finite,
        "null_pct": (n_null / n_total * 100.0) if n_total else 0.0,
        "mean": fmean(finite) if finite else None,
        "std": stdev(finite) if len(finite) >= 2 else None,
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "p01": _quantile(ordered, 0.01),
        "p05": _quantile(ordered, 0.05),
        "p50": _quantile(ordered, 0.50),
        "p95": _quantile(ordered, 0.95),
        "p99": _quantile(ordered, 0.99),
    }


def _period_key(value: date | datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _per_symbol_summary(
    df: pl.DataFrame,
    definitions: Sequence[TargetDefinition],
    *,
    include_distribution: bool,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for symbol in sorted(df[SYMBOL_COL].unique().to_list()):
        frame = df.filter(pl.col(SYMBOL_COL) == symbol)
        targets: dict[str, Any] = {}
        for definition in definitions:
            stats = _distribution(frame[definition.column].to_list())
            if not include_distribution:
                stats = {
                    key: stats[key]
                    for key in ("n_total", "n_valid", "n_null", "n_non_finite", "null_pct")
                }
            targets[definition.column] = stats
        summaries.append(
            {
                "symbol": symbol,
                "n_rows": len(frame),
                "distribution_included": include_distribution,
                "targets": targets,
            }
        )
    return summaries


def _per_period_summary(
    df: pl.DataFrame,
    definitions: Sequence[TargetDefinition],
) -> list[dict[str, Any]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in df.select(
        [TIMESTAMP_COL, *[definition.column for definition in definitions]]
    ).iter_rows(named=True):
        rows[_period_key(row[TIMESTAMP_COL])].append(row)

    result: list[dict[str, Any]] = []
    for period in sorted(rows):
        period_rows = rows[period]
        result.append(
            {
                "period": period,
                "n_rows": len(period_rows),
                "targets": {
                    definition.column: _distribution(
                        [row[definition.column] for row in period_rows]
                    )
                    for definition in definitions
                },
            }
        )
    return result


def _actual_null_breakdown(
    df: pl.DataFrame,
    definitions: Sequence[TargetDefinition],
) -> dict[str, dict[str, int]]:
    if NULL_REASON_COL not in df or len(definitions) != 1:
        return {}
    result: dict[str, dict[str, int]] = {}
    for definition in definitions:
        null_rows = df.filter(pl.col(definition.column).is_null())
        if null_rows.is_empty():
            result[definition.column] = {}
            continue
        grouped = (
            null_rows.group_by(NULL_REASON_COL)
            .len()
            .sort(NULL_REASON_COL, nulls_last=True)
            .to_dicts()
        )
        result[definition.column] = {
            str(row[NULL_REASON_COL] if row[NULL_REASON_COL] is not None else "UNSPECIFIED"): int(
                row["len"]
            )
            for row in grouped
        }
    return result


def _metadata(
    manifest: Mapping[str, Any] | None,
    definitions: Sequence[TargetDefinition],
) -> dict[str, Any]:
    if manifest is None:
        return {
            "manifest_available": False,
            "manifest_schema_version": None,
            "target_set_id": None,
            "fingerprint": None,
            "source": None,
            "horizons": [definition.horizon for definition in definitions],
            "target_columns": [definition.column for definition in definitions],
        }
    return {
        "manifest_available": True,
        "manifest_schema_version": int(manifest.get("schema_version", 1)),
        "target_set_id": manifest.get("target_set_id", manifest.get("target_id")),
        "fingerprint": manifest.get("fingerprint"),
        "source": manifest.get("source", manifest.get("source_dataset_id")),
        "horizons": [definition.horizon for definition in definitions],
        "target_columns": [definition.column for definition in definitions],
    }


def _manifest_mismatches(
    df: pl.DataFrame,
    manifest: Mapping[str, Any],
    definitions: Sequence[TargetDefinition],
    per_horizon: Sequence[Mapping[str, Any]],
    actual_null_breakdown: Mapping[str, Mapping[str, int]],
) -> list[str]:
    mismatches: list[str] = []

    expected_row_count = manifest.get("row_count")
    if expected_row_count is not None and expected_row_count != len(df):
        mismatches.append(f"row_count manifest={expected_row_count} data={len(df)}")

    expected_symbols = manifest.get("symbols")
    actual_symbols = sorted(df[SYMBOL_COL].unique().to_list())
    if expected_symbols is not None and sorted(expected_symbols) != actual_symbols:
        mismatches.append(
            f"symbols manifest={sorted(expected_symbols)} data={actual_symbols}"
        )

    if len(definitions) == 1:
        stats = per_horizon[0]
        for manifest_key, report_key in (
            ("valid_label_count", "n_valid"),
            ("null_label_count", "n_null"),
        ):
            expected = manifest.get(manifest_key)
            if expected is not None and expected != stats[report_key]:
                mismatches.append(
                    f"{manifest_key} manifest={expected} data={stats[report_key]}"
                )

        expected_breakdown = manifest.get("null_breakdown")
        actual_breakdown = actual_null_breakdown.get(definitions[0].column)
        if (
            expected_breakdown is not None
            and actual_breakdown is not None
            and dict(expected_breakdown) != dict(actual_breakdown)
        ):
            mismatches.append(
                f"null_breakdown manifest={dict(expected_breakdown)} "
                f"data={dict(actual_breakdown)}"
            )

        fingerprint = manifest.get("fingerprint")
        price_column = manifest.get("price_column")
        if fingerprint and isinstance(price_column, str) and price_column in df:
            try:
                actual_fingerprint = fingerprint_target_labels(
                    df,
                    horizon=definitions[0].horizon,
                    price_col=price_column,
                    label_col=definitions[0].column,
                )
            except TargetLabelError:
                actual_fingerprint = None
            if actual_fingerprint is not None and fingerprint != actual_fingerprint:
                mismatches.append(
                    f"fingerprint manifest={fingerprint} data={actual_fingerprint}"
                )
    return mismatches


def _generated_at(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TargetReportError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat()


def build_target_qa_report(
    df: pl.DataFrame,
    *,
    manifest: TargetManifest | Mapping[str, Any] | None = None,
    config: TargetReportConfig | Mapping[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Build a JSON-compatible, fail-closed QA report for forward-return labels."""
    resolved_manifest = _manifest_mapping(manifest)
    resolved_config = _normalize_config(config)
    definitions = _resolve_definitions(df, resolved_manifest, resolved_config)
    _validate_frame(df, definitions)
    ordered = df.sort([SYMBOL_COL, TIMESTAMP_COL], maintain_order=True)

    warnings: list[dict[str, Any]] = []
    if resolved_manifest is None:
        warnings.append(
            _warning(
                "missing_manifest",
                "No target manifest was provided; provenance and manifest consistency "
                "checks are incomplete.",
            )
        )

    per_horizon: list[dict[str, Any]] = []
    for definition in definitions:
        stats = _distribution(ordered[definition.column].to_list())
        item = {
            "horizon": definition.horizon,
            "target_column": definition.column,
            **stats,
        }
        per_horizon.append(item)
        if stats["null_pct"] > resolved_config.max_null_pct:
            warnings.append(
                _warning(
                    "high_null_fraction",
                    f"{definition.column} null_pct={stats['null_pct']:.4f}% exceeds "
                    f"configured maximum {resolved_config.max_null_pct:.4f}%.",
                    target_column=definition.column,
                )
            )
        if stats["n_non_finite"] > 0:
            warnings.append(
                _warning(
                    "non_finite_values",
                    f"{definition.column} contains {stats['n_non_finite']} non-finite value(s).",
                    target_column=definition.column,
                )
            )
        finite, _, _ = _finite_and_non_finite(ordered[definition.column].to_list())
        extreme_count = sum(
            abs(value) > resolved_config.extreme_return_threshold for value in finite
        )
        if extreme_count:
            warnings.append(
                _warning(
                    "extreme_return",
                    f"{definition.column} contains {extreme_count} finite return(s) beyond "
                    f"absolute threshold {resolved_config.extreme_return_threshold:.6f}.",
                    target_column=definition.column,
                )
            )

    symbols = sorted(ordered[SYMBOL_COL].unique().to_list())
    include_symbol_distribution = (
        len(symbols) <= resolved_config.max_symbols_with_distribution
    )
    if not include_symbol_distribution:
        warnings.append(
            _warning(
                "per_symbol_distribution_omitted",
                f"Per-symbol distribution statistics were omitted because {len(symbols)} "
                f"symbols exceed the configured bound "
                f"{resolved_config.max_symbols_with_distribution}.",
                severity="INFO",
            )
        )

    actual_null_breakdown = _actual_null_breakdown(ordered, definitions)
    if NULL_REASON_COL not in ordered:
        warnings.append(
            _warning(
                "missing_null_reason_ledger",
                f"{NULL_REASON_COL} is absent; data-level null reasons cannot be audited.",
            )
        )
    elif len(definitions) > 1:
        warnings.append(
            _warning(
                "ambiguous_null_reason_ledger",
                f"{NULL_REASON_COL} is a single ledger and cannot be attributed safely across "
                "multiple target horizons; use manifest null breakdowns for this report.",
                severity="INFO",
            )
        )

    if resolved_manifest is not None:
        mismatches = _manifest_mismatches(
            ordered,
            resolved_manifest,
            definitions,
            per_horizon,
            actual_null_breakdown,
        )
        if mismatches:
            warnings.append(
                _warning(
                    "manifest_data_mismatch",
                    "Manifest/data mismatch: " + "; ".join(mismatches),
                )
            )

    warnings.append(
        _warning(
            "upstream_data_responsibilities",
            UPSTREAM_DATA_WARNING,
            severity="INFO",
        )
    )
    verdict = (
        "SUSPECT"
        if any(item["severity"] == "WARNING" for item in warnings)
        else "OK"
    )

    generated = _generated_at(clock or (lambda: datetime.now(UTC)))
    return {
        "schema_version": TARGET_REPORT_SCHEMA_VERSION,
        "generated_at_utc": generated,
        "verdict": verdict,
        "target_set": _metadata(resolved_manifest, definitions),
        "config": {
            **asdict(resolved_config),
            "targets": [
                asdict(definition) for definition in resolved_config.targets or definitions
            ],
        },
        "per_horizon": per_horizon,
        "per_symbol": _per_symbol_summary(
            ordered,
            definitions,
            include_distribution=include_symbol_distribution,
        ),
        "per_period": (
            _per_period_summary(ordered, definitions)
            if resolved_config.include_period_summary
            else []
        ),
        "null_breakdown": {
            "manifest": (
                dict(resolved_manifest.get("null_breakdown", {}))
                if resolved_manifest is not None
                else {}
            ),
            "data": actual_null_breakdown,
        },
        "warnings": warnings,
        "boundary_note": BOUNDARY_NOTE,
    }


def _display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def render_target_qa_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact human-readable Target QA Report."""
    if report.get("schema_version") != TARGET_REPORT_SCHEMA_VERSION:
        raise TargetReportError("unsupported or missing target report schema_version")
    for field in (
        "generated_at_utc",
        "verdict",
        "target_set",
        "per_horizon",
        "per_symbol",
        "null_breakdown",
        "warnings",
        "boundary_note",
    ):
        if field not in report:
            raise TargetReportError(f"target report is missing required field: {field}")

    metadata = report["target_set"]
    lines = [
        "# Target QA Report",
        "",
        f"> **Summary verdict: {report['verdict']}**",
        "",
        "## Target Set",
        "",
        "| field | value |",
        "|---|---|",
        f"| generated_at_utc | {report['generated_at_utc']} |",
        f"| target_set_id | {_display(metadata.get('target_set_id'))} |",
        f"| source | {_display(metadata.get('source'))} |",
        f"| fingerprint | {_display(metadata.get('fingerprint'))} |",
        f"| horizons | {', '.join(str(v) for v in metadata.get('horizons', []))} |",
        f"| target columns | {', '.join(metadata.get('target_columns', []))} |",
        "",
        "## Per-Horizon Statistics",
        "",
        "| horizon | target | n_total | n_valid | n_null | null_pct | mean | std | min | max | "
        "p01 | p05 | p50 | p95 | p99 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for stats in report["per_horizon"]:
        lines.append(
            f"| {stats['horizon']} | {stats['target_column']} | {stats['n_total']} | "
            f"{stats['n_valid']} | {stats['n_null']} | {_display(stats['null_pct'])} | "
            f"{_display(stats['mean'])} | {_display(stats['std'])} | "
            f"{_display(stats['min'])} | {_display(stats['max'])} | "
            f"{_display(stats['p01'])} | {_display(stats['p05'])} | "
            f"{_display(stats['p50'])} | {_display(stats['p95'])} | "
            f"{_display(stats['p99'])} |"
        )

    lines += ["", "## Null Breakdown", ""]
    manifest_breakdown = report["null_breakdown"].get("manifest", {})
    lines.append(f"- manifest: {_display(manifest_breakdown or 'not available')}")
    data_breakdown = report["null_breakdown"].get("data", {})
    if data_breakdown:
        for column, breakdown in data_breakdown.items():
            lines.append(f"- {column}: {_display(breakdown or 'no nulls')}")
    else:
        lines.append("- data: not available")

    lines += [
        "",
        "## Per-Symbol Summary",
        "",
        "| symbol | target | n_rows | n_valid | n_null | non_finite | mean | std | min | max |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for symbol_summary in report["per_symbol"]:
        for column, stats in symbol_summary["targets"].items():
            lines.append(
                f"| {symbol_summary['symbol']} | {column} | {symbol_summary['n_rows']} | "
                f"{stats['n_valid']} | {stats['n_null']} | {stats['n_non_finite']} | "
                f"{_display(stats.get('mean'))} | {_display(stats.get('std'))} | "
                f"{_display(stats.get('min'))} | {_display(stats.get('max'))} |"
            )

    lines += ["", "## Warnings", ""]
    if report["warnings"]:
        for item in report["warnings"]:
            lines.append(f"- **{item['severity']} · {item['code']}**: {item['message']}")
    else:
        lines.append("- None.")

    lines += [
        "",
        "## Safety Boundary",
        "",
        report["boundary_note"],
        "",
    ]
    return "\n".join(lines)
