"""Tests for the append-only experiment registry. tmp_path only — no network, no real .env."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from alpaca_quant.research.experiment_registry import (
    ExperimentRecord,
    ExperimentRegistryError,
    append_experiment_record,
    capture_git_sha,
    create_experiment_run_id,
    new_experiment_record,
    read_experiment_records,
)


def record(run_id: str = "exp-test-001", **overrides) -> ExperimentRecord:
    values = {
        "run_id": run_id,
        "created_at": datetime(2026, 6, 14, 12, tzinfo=UTC),
        "git_sha": "abc1234",
        "dataset_id": "rds-85eb9a7b",
        "dataset_manifest_path": "data/runs/run/research_dataset_rds-85eb9a7b_manifest.yaml",
        "feature_set_id": "feat-AAPL-27d52941",
        "config_hash": "sha256:deadbeef",
        "seed": 42,
        "decided_by": "max",
        "notes": "first scaffolding run",
    }
    values.update(overrides)
    return ExperimentRecord(**values)


class TestRecordModel:
    def test_defaults(self) -> None:
        rec = record()
        assert rec.kind == "experiment"
        assert rec.decision == "keep_researching"
        assert rec.metrics == {}
        assert rec.no_trading is True
        assert rec.no_backtesting is True
        assert rec.no_model_training is True

    def test_naive_created_at_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must include a timezone"):
            record(created_at=datetime(2026, 6, 14, 12))

    def test_created_at_coerced_to_utc(self) -> None:
        from datetime import timedelta, timezone

        plus_two = timezone(timedelta(hours=2))
        rec = record(created_at=datetime(2026, 6, 14, 14, tzinfo=plus_two))
        assert rec.created_at.utcoffset() == timedelta(0)
        assert rec.created_at.hour == 12

    def test_blank_run_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            record(run_id="   ")

    @pytest.mark.parametrize(
        "flag",
        ["no_trading", "no_model_training", "no_live_execution", "no_order_submission"],
    )
    def test_capital_safety_flag_false_rejected(self, flag: str) -> None:
        with pytest.raises(ValidationError, match="fail-closed"):
            record(**{flag: False})

    def test_no_backtesting_false_is_allowed(self) -> None:
        # backtesting is a legitimate research activity; the flag is informational, not enforced
        rec = record(no_backtesting=False)
        assert rec.no_backtesting is False

    def test_new_provenance_fields(self) -> None:
        rec = record(as_of="2024-01-31", report_path="data/runs/x.json", weight_source="caller")
        assert rec.as_of == "2024-01-31"
        assert rec.report_path == "data/runs/x.json"
        assert rec.weight_source == "caller"

    def test_invalid_decision_rejected(self) -> None:
        with pytest.raises(ValidationError):
            record(decision="promote_to_live")

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            record(unexpected="nope")


class TestRunId:
    def test_format(self) -> None:
        rid = create_experiment_run_id(datetime(2026, 6, 14, 12, 30, 5, tzinfo=UTC))
        assert rid.startswith("exp-20260614T123005Z-")
        assert len(rid.split("-")[-1]) == 8

    def test_uniqueness(self) -> None:
        a = create_experiment_run_id()
        b = create_experiment_run_id()
        assert a != b


class TestAppendRead:
    def test_append_and_read_one(self, tmp_path) -> None:
        registry = tmp_path / "nested" / "experiment_registry.jsonl"
        append_experiment_record(registry, record())
        records = read_experiment_records(registry)
        assert registry.is_file()
        assert len(records) == 1
        assert records[0].run_id == "exp-test-001"

    def test_append_two_preserves_order(self, tmp_path) -> None:
        registry = tmp_path / "experiment_registry.jsonl"
        append_experiment_record(registry, record("exp-test-001"))
        append_experiment_record(registry, record("exp-test-002"))
        assert [r.run_id for r in read_experiment_records(registry)] == [
            "exp-test-001",
            "exp-test-002",
        ]
        assert len(registry.read_text(encoding="utf-8").splitlines()) == 2

    def test_duplicate_run_id_on_append_rejected(self, tmp_path) -> None:
        registry = tmp_path / "experiment_registry.jsonl"
        append_experiment_record(registry, record("exp-dup"))
        with pytest.raises(ExperimentRegistryError, match="immutable"):
            append_experiment_record(registry, record("exp-dup", notes="changed"))
        # immutability: registry unchanged (still exactly one line)
        assert len(registry.read_text(encoding="utf-8").splitlines()) == 1

    def test_missing_registry_read_raises(self, tmp_path) -> None:
        with pytest.raises(ExperimentRegistryError, match="does not exist"):
            read_experiment_records(tmp_path / "nope.jsonl")

    def test_invalid_jsonl_raises_with_line(self, tmp_path) -> None:
        registry = tmp_path / "experiment_registry.jsonl"
        append_experiment_record(registry, record())
        with registry.open("a", encoding="utf-8") as f:
            f.write("not-json\n")
        with pytest.raises(ExperimentRegistryError, match="line 2"):
            read_experiment_records(registry)

    def test_duplicate_run_id_on_read_rejected(self, tmp_path) -> None:
        registry = tmp_path / "experiment_registry.jsonl"
        append_experiment_record(registry, record("exp-x"))
        # bypass append guard by writing a second identical run_id directly
        import json

        line = json.dumps(record("exp-x").model_dump(mode="json"), sort_keys=True)
        with registry.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        with pytest.raises(ExperimentRegistryError, match="duplicate run_id"):
            read_experiment_records(registry)


class TestSecrets:
    def test_env_secret_not_serialized(self, tmp_path, monkeypatch) -> None:
        registry = tmp_path / "experiment_registry.jsonl"
        api_key = "configured-key-must-not-appear"
        api_secret = "configured-secret-must-not-appear"
        monkeypatch.setenv("ALPACA_API_KEY_ID", api_key)
        monkeypatch.setenv("ALPACA_API_SECRET_KEY", api_secret)
        append_experiment_record(registry, record())
        serialized = registry.read_text(encoding="utf-8")
        assert api_key not in serialized
        assert api_secret not in serialized

    def test_configured_sensitive_value_rejected(self, tmp_path) -> None:
        registry = tmp_path / "experiment_registry.jsonl"
        secret = "secret-value-must-not-be-written"
        unsafe = record(notes=f"accidental secret: {secret}")
        with pytest.raises(ExperimentRegistryError, match="configured secret value"):
            append_experiment_record(registry, unsafe, sensitive_values=[secret])
        assert not registry.exists()


class TestGitShaAndFactory:
    def test_capture_git_sha_returns_str_or_none(self) -> None:
        sha = capture_git_sha()
        assert sha is None or isinstance(sha, str)

    def test_capture_git_sha_non_repo_returns_none(self, tmp_path) -> None:
        assert capture_git_sha(tmp_path) is None

    def test_new_experiment_record_autofills(self) -> None:
        rec = new_experiment_record(git_sha="fixedsha", dataset_id="rds-1")
        assert rec.run_id.startswith("exp-")
        assert rec.created_at.utcoffset() is not None
        assert rec.git_sha == "fixedsha"
        assert rec.dataset_id == "rds-1"

    def test_new_experiment_record_git_sha_type(self) -> None:
        rec = new_experiment_record()
        assert rec.git_sha is None or isinstance(rec.git_sha, str)

    def test_new_experiment_record_metrics_empty(self) -> None:
        rec = new_experiment_record(git_sha="x")
        assert rec.metrics == {}
