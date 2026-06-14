"""Append-only JSONL registry for research experiments.

This is discipline scaffolding (RESEARCH_PROTOCOL.md §1): future backtests will write
immutable run entries here. This sprint records metadata only — no backtest runs yet.

Local only. No network. No Alpaca API calls. No .env file reads. Environment variables are
read solely to redact secrets, never to consume credentials. No labels, targets, signals,
alpha, model training, backtesting, or trading.
"""

import json
import os
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

SECRET_ENV_NAMES = ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")

GIT_SHA_TIMEOUT_SECONDS = 5

DecisionType = Literal["keep_researching", "rejected", "promote_to_paper"]


class ExperimentRegistryError(RuntimeError):
    """Raised when experiment metadata cannot be safely stored or read."""


class ExperimentRecord(BaseModel):
    """Validated, immutable metadata for one research experiment run.

    Carries no backtest results yet: `metrics` ships empty and the safety flags must be True.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    created_at: datetime
    git_sha: str | None = None
    dataset_id: str | None = None
    dataset_manifest_path: str | None = None
    feature_set_id: str | None = None
    feature_version: str | None = None
    config_hash: str | None = None
    seed: int | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    decision: DecisionType = "keep_researching"
    decided_by: str | None = None
    notes: str | None = None
    kind: Literal["experiment"] = "experiment"
    no_trading: StrictBool = True
    no_backtesting: StrictBool = True
    no_model_training: StrictBool = True

    @field_validator("run_id")
    @classmethod
    def require_non_blank_run_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("run_id must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("no_trading", "no_backtesting", "no_model_training")
    @classmethod
    def require_safety_flag_true(cls, value: bool) -> bool:  # noqa: FBT001
        if value is not True:
            raise ValueError("safety flags must be True (fail-closed)")
        return value


def create_experiment_run_id(created_at: datetime | None = None) -> str:
    """Create a locally unique, time-sortable experiment run identifier."""
    timestamp = (created_at or datetime.now(UTC)).astimezone(UTC)
    return f"exp-{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def capture_git_sha(repo_dir: str | Path | None = None) -> str | None:
    """Return the current git commit SHA via subprocess, or None if unavailable.

    Local and read-only (`git rev-parse HEAD`). Never raises, never uses the network.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir) if repo_dir is not None else None,
            capture_output=True,
            text=True,
            timeout=GIT_SHA_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    sha = completed.stdout.strip()
    return sha or None


def new_experiment_record(
    *,
    run_id: str | None = None,
    created_at: datetime | None = None,
    git_sha: str | None = None,
    repo_dir: str | Path | None = None,
    **fields: object,
) -> ExperimentRecord:
    """Build an ExperimentRecord, auto-filling run_id, created_at, and git_sha if omitted."""
    resolved_created_at = created_at or datetime.now(UTC)
    resolved_run_id = run_id or create_experiment_run_id(resolved_created_at)
    resolved_git_sha = git_sha if git_sha is not None else capture_git_sha(repo_dir)
    return ExperimentRecord(
        run_id=resolved_run_id,
        created_at=resolved_created_at,
        git_sha=resolved_git_sha,
        **fields,
    )


def append_experiment_record(
    registry_path: str | Path,
    record: ExperimentRecord,
    *,
    sensitive_values: Iterable[str] = (),
) -> Path:
    """Append one validated, secret-free record to the append-only JSONL registry.

    Enforces run_id immutability: a run_id already present in the registry is rejected and
    nothing is written.
    """
    path = Path(registry_path)

    if path.is_file():
        existing_ids = {existing.run_id for existing in read_experiment_records(path)}
        if record.run_id in existing_ids:
            raise ExperimentRegistryError(
                f"run_id already exists and is immutable: {record.run_id}"
            )

    serialized = json.dumps(record.model_dump(mode="json"), sort_keys=True)
    _reject_secrets(serialized, sensitive_values)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with path.open("a", encoding="utf-8") as registry:
            registry.write(serialized + "\n")
    except OSError as exc:
        raise ExperimentRegistryError(f"failed to append experiment registry: {path}") from exc
    return path


def read_experiment_records(registry_path: str | Path) -> list[ExperimentRecord]:
    """Read and validate every record in the append-only JSONL registry."""
    path = Path(registry_path)
    if not path.is_file():
        raise ExperimentRegistryError(f"experiment registry does not exist: {path}")

    records: list[ExperimentRecord] = []
    seen_ids: set[str] = set()
    try:
        with path.open(encoding="utf-8") as registry:
            for line_number, line in enumerate(registry, start=1):
                if not line.strip():
                    raise ExperimentRegistryError(
                        f"invalid experiment registry entry at line {line_number}"
                    )
                try:
                    payload = json.loads(line)
                    record = ExperimentRecord.model_validate(payload)
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise ExperimentRegistryError(
                        f"invalid experiment registry entry at line {line_number}"
                    ) from exc
                if record.run_id in seen_ids:
                    raise ExperimentRegistryError(
                        f"duplicate run_id in registry at line {line_number}: {record.run_id}"
                    )
                seen_ids.add(record.run_id)
                records.append(record)
    except OSError as exc:
        raise ExperimentRegistryError(f"failed to read experiment registry: {path}") from exc
    return records


def _reject_secrets(serialized: str, sensitive_values: Iterable[str]) -> None:
    values = [os.environ.get(name, "") for name in SECRET_ENV_NAMES]
    values.extend(sensitive_values)

    if any(name in serialized for name in SECRET_ENV_NAMES):
        raise ExperimentRegistryError("experiment record contains prohibited secret metadata")
    if any(value and value in serialized for value in values):
        raise ExperimentRegistryError("experiment record contains a configured secret value")
