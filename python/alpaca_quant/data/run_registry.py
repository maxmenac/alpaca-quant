"""Append-only JSONL registry for controlled historical fetch runs."""

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

SECRET_ENV_NAMES = ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")


class RunRegistryError(RuntimeError):
    """Raised when fetch run metadata cannot be safely stored or read."""


class FetchRunRecord(BaseModel):
    """Validated provenance metadata for one controlled historical fetch."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: datetime
    symbols: list[str]
    start: str
    end: str
    feed: str
    rows_written: int = Field(ge=0)
    output_dir: str
    parquet_path: str
    manifest_path: str
    data_declaration_id: str | None = None
    verification_passed: StrictBool
    mode: Literal["controlled_historical_fetch"] = "controlled_historical_fetch"
    known_gaps: list[str] | None = None
    request_id: str | None = None
    status: Literal["success", "failed"]

    @field_validator("symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value: Iterable[str]) -> list[str]:
        symbols = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        return symbols

    @field_validator("created_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)


def create_fetch_run_id(created_at: datetime | None = None) -> str:
    """Create a locally unique, time-sortable controlled fetch run identifier."""
    timestamp = (created_at or datetime.now(UTC)).astimezone(UTC)
    return f"fetch-{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def append_fetch_run_record(
    registry_path: str | Path,
    record: FetchRunRecord,
    *,
    sensitive_values: Iterable[str] = (),
) -> Path:
    """Append one validated, secret-free record to a JSONL registry."""
    path = Path(registry_path)
    serialized = json.dumps(record.model_dump(mode="json"), sort_keys=True)
    _reject_secrets(serialized, sensitive_values)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with path.open("a", encoding="utf-8") as registry:
            registry.write(serialized + "\n")
    except OSError as exc:
        raise RunRegistryError(f"failed to append fetch run registry: {path}") from exc
    return path


def read_fetch_run_records(registry_path: str | Path) -> list[FetchRunRecord]:
    """Read and validate every record in an append-only JSONL registry."""
    path = Path(registry_path)
    if not path.is_file():
        raise RunRegistryError(f"fetch run registry does not exist: {path}")

    records: list[FetchRunRecord] = []
    try:
        with path.open(encoding="utf-8") as registry:
            for line_number, line in enumerate(registry, start=1):
                if not line.strip():
                    raise RunRegistryError(
                        f"invalid fetch run registry entry at line {line_number}"
                    )
                try:
                    payload = json.loads(line)
                    records.append(FetchRunRecord.model_validate(payload))
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise RunRegistryError(
                        f"invalid fetch run registry entry at line {line_number}"
                    ) from exc
    except OSError as exc:
        raise RunRegistryError(f"failed to read fetch run registry: {path}") from exc
    return records


def _reject_secrets(serialized: str, sensitive_values: Iterable[str]) -> None:
    values = [
        os.environ.get(name, "")
        for name in SECRET_ENV_NAMES
    ]
    values.extend(sensitive_values)

    if any(name in serialized for name in SECRET_ENV_NAMES):
        raise RunRegistryError("fetch run record contains prohibited secret metadata")
    if any(value and value in serialized for value in values):
        raise RunRegistryError("fetch run record contains a configured secret value")
