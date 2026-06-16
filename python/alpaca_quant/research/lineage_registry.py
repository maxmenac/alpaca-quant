"""Phase 4E dataset/run lineage registry: descriptive provenance only.

This module records which dataset, feature set, label lineage, split definition, and inspection
verdict produced a dataset realization. It does not evaluate predictive quality, train models,
generate alpha/signals/weights, run backtests, place orders, read .env, or touch any network/API.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

LINEAGE_REGISTRY_SCHEMA_VERSION = 1
LINEAGE_RECORD_TYPE = "lineage"


class LineageRegistryError(RuntimeError):
    """Raised when lineage records cannot be safely created, stored, or read."""


class LineageRecord(BaseModel):
    """Immutable dataset/run lineage entry.

    Verdicts and reason lists are copied from existing inspection outputs; they are never
    recomputed here.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = LINEAGE_REGISTRY_SCHEMA_VERSION
    record_type: Literal["lineage"] = LINEAGE_RECORD_TYPE
    entry_id: str = Field(min_length=1)
    created_at_utc: datetime
    dataset_id: str = Field(min_length=1)
    dataset_fingerprint: str = Field(min_length=1)
    feature_set_id: str | None = None
    source_label_fingerprint: str | None = None
    split_ref: list[dict[str, Any]] = Field(default_factory=list)
    verdict: Literal["OK", "SUSPECT", "REJECTED"]
    reason_list: list[dict[str, Any]] = Field(default_factory=list)
    declared_corporate_actions_status: str | None = None
    declared_adjustment_status: str | None = None
    entry_fingerprint: str = Field(min_length=1)

    @field_validator("created_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at_utc must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_matching_fingerprint(self) -> "LineageRecord":
        expected = fingerprint_lineage_entry(self)
        if self.entry_fingerprint != expected:
            raise ValueError("entry_fingerprint does not match lineage payload")
        expected_id = entry_id_from_fingerprint(expected)
        if self.entry_id != expected_id:
            raise ValueError("entry_id does not match entry_fingerprint")
        return self


def _json_default(value: object) -> str:
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _canonical_payload(value: LineageRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, LineageRecord):
        payload = value.model_dump(mode="json")
    else:
        payload = dict(value)
    payload.pop("entry_id", None)
    payload.pop("entry_fingerprint", None)
    return payload


def fingerprint_lineage_entry(value: LineageRecord | dict[str, Any]) -> str:
    """Return the deterministic fingerprint for a lineage payload.

    The fingerprint is canonical JSON over the lineage fields, excluding the derived ``entry_id``
    and ``entry_fingerprint`` fields themselves.
    """
    canonical = json.dumps(
        _canonical_payload(value),
        allow_nan=False,
        default=_json_default,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def entry_id_from_fingerprint(fingerprint: str) -> str:
    """Derive a stable lineage entry id from its fingerprint."""
    return f"lin-{fingerprint.removeprefix('sha256:')[:12]}"


def build_lineage_record(
    *,
    created_at_utc: datetime,
    dataset_id: str,
    dataset_fingerprint: str,
    verdict: Literal["OK", "SUSPECT", "REJECTED"],
    feature_set_id: str | None = None,
    source_label_fingerprint: str | None = None,
    split_ref: list[dict[str, Any]] | None = None,
    reason_list: list[dict[str, Any]] | None = None,
    declared_corporate_actions_status: str | None = None,
    declared_adjustment_status: str | None = None,
) -> LineageRecord:
    """Build a validated lineage record and fill derived identifiers deterministically."""
    payload: dict[str, Any] = {
        "schema_version": LINEAGE_REGISTRY_SCHEMA_VERSION,
        "record_type": LINEAGE_RECORD_TYPE,
        "created_at_utc": created_at_utc,
        "dataset_id": dataset_id,
        "dataset_fingerprint": dataset_fingerprint,
        "feature_set_id": feature_set_id,
        "source_label_fingerprint": source_label_fingerprint,
        "split_ref": list(split_ref or []),
        "verdict": verdict,
        "reason_list": list(reason_list or []),
        "declared_corporate_actions_status": declared_corporate_actions_status,
        "declared_adjustment_status": declared_adjustment_status,
    }
    fingerprint = fingerprint_lineage_entry(payload)
    payload["entry_fingerprint"] = fingerprint
    payload["entry_id"] = entry_id_from_fingerprint(fingerprint)
    return LineageRecord.model_validate(payload)


def _as_mapping(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        data = value.to_dict()
        if isinstance(data, Mapping):
            return dict(data)
    if isinstance(value, Mapping):
        return dict(value)
    raise LineageRegistryError(f"{label} must be a mapping or expose to_dict()")


def _generated_at(clock: Any | None) -> datetime:
    value = (clock or (lambda: datetime.now(UTC)))()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise LineageRegistryError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def lineage_record_from_manifest_report(
    *,
    manifest: object,
    inspection_report: Mapping[str, Any],
    clock: Any | None = None,
) -> LineageRecord:
    """Create a lineage entry from existing 4C manifest and 4D inspection outputs.

    The inspection verdict and warnings are copied verbatim. This function does not inspect the
    dataset frame and does not recompute any verdict.
    """
    manifest_data = _as_mapping(manifest, label="manifest")
    report_data = dict(inspection_report)
    dataset_id = manifest_data.get("dataset_id") or report_data.get("dataset_id")
    dataset_fingerprint = (
        manifest_data.get("fingerprint") or report_data.get("dataset_fingerprint")
    )
    verdict = report_data.get("verdict")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise LineageRegistryError("manifest/report must provide dataset_id")
    if not isinstance(dataset_fingerprint, str) or not dataset_fingerprint:
        raise LineageRegistryError("manifest/report must provide dataset fingerprint")
    if verdict not in {"OK", "SUSPECT", "REJECTED"}:
        raise LineageRegistryError("inspection_report must provide an OK/SUSPECT/REJECTED verdict")

    return build_lineage_record(
        created_at_utc=_generated_at(clock),
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
        feature_set_id=report_data.get("feature_set_id"),
        source_label_fingerprint=manifest_data.get("source_label_fingerprint"),
        split_ref=list(manifest_data.get("split_definitions", [])),
        verdict=verdict,
        reason_list=list(report_data.get("warnings", [])),
        declared_corporate_actions_status=manifest_data.get(
            "declared_corporate_actions_status"
        ),
        declared_adjustment_status=manifest_data.get("declared_adjustment_status"),
    )


def append_lineage_record(registry_path: str | Path, record: LineageRecord) -> Path:
    """Append one immutable lineage record to a local JSONL registry."""
    path = Path(registry_path)
    if path.is_file():
        existing_ids = {existing.entry_id for existing in read_lineage_records(path)}
        if record.entry_id in existing_ids:
            raise LineageRegistryError(
                f"entry_id already exists and is immutable: {record.entry_id}"
            )
    serialized = json.dumps(record.model_dump(mode="json"), allow_nan=False, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as registry:
            registry.write(serialized + "\n")
    except OSError as exc:
        raise LineageRegistryError(f"failed to append lineage registry: {path}") from exc
    return path


def read_lineage_records(registry_path: str | Path) -> list[LineageRecord]:
    """Read every validated lineage record from a local JSONL registry."""
    path = Path(registry_path)
    if not path.is_file():
        raise LineageRegistryError(f"lineage registry does not exist: {path}")

    records: list[LineageRecord] = []
    seen_ids: set[str] = set()
    try:
        with path.open(encoding="utf-8") as registry:
            for line_number, line in enumerate(registry, start=1):
                if not line.strip():
                    raise LineageRegistryError(
                        f"invalid lineage registry entry at line {line_number}"
                    )
                try:
                    payload = json.loads(line)
                    record = LineageRecord.model_validate(payload)
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise LineageRegistryError(
                        f"invalid lineage registry entry at line {line_number}"
                    ) from exc
                if record.entry_id in seen_ids:
                    raise LineageRegistryError(
                        f"duplicate entry_id in registry at line {line_number}: "
                        f"{record.entry_id}"
                    )
                seen_ids.add(record.entry_id)
                records.append(record)
    except OSError as exc:
        raise LineageRegistryError(f"failed to read lineage registry: {path}") from exc
    return records


def query_lineage_records(
    records: Sequence[LineageRecord],
    *,
    dataset_id: str | None = None,
    feature_set_id: str | None = None,
    verdict: str | None = None,
) -> list[LineageRecord]:
    """Return lineage records matching the provided descriptive filters."""
    matched = list(records)
    if dataset_id is not None:
        matched = [record for record in matched if record.dataset_id == dataset_id]
    if feature_set_id is not None:
        matched = [record for record in matched if record.feature_set_id == feature_set_id]
    if verdict is not None:
        matched = [record for record in matched if record.verdict == verdict]
    return matched


def export_lineage_records(records: Sequence[LineageRecord], output_path: str | Path) -> Path:
    """Write lineage records as canonical JSON to an explicit local path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [record.model_dump(mode="json") for record in records]
    try:
        path.write_text(
            json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise LineageRegistryError(f"failed to export lineage registry: {path}") from exc
    return path


__all__ = [
    "LINEAGE_RECORD_TYPE",
    "LINEAGE_REGISTRY_SCHEMA_VERSION",
    "LineageRecord",
    "LineageRegistryError",
    "append_lineage_record",
    "build_lineage_record",
    "entry_id_from_fingerprint",
    "export_lineage_records",
    "fingerprint_lineage_entry",
    "lineage_record_from_manifest_report",
    "query_lineage_records",
    "read_lineage_records",
]
