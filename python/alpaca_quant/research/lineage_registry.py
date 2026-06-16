"""Phase 4E dataset/run lineage registry: descriptive provenance only.

This module records which dataset, feature set, label lineage, split definition, and inspection
verdict produced a dataset realization. It does not evaluate predictive quality, train models,
generate alpha/signals/weights, run backtests, place orders, read .env, or touch any network/API.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


__all__ = [
    "LINEAGE_RECORD_TYPE",
    "LINEAGE_REGISTRY_SCHEMA_VERSION",
    "LineageRecord",
    "LineageRegistryError",
    "build_lineage_record",
    "entry_id_from_fingerprint",
    "fingerprint_lineage_entry",
]
