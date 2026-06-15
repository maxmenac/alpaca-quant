"""Phase 4D feature registry tests. Synthetic only: no .env, network, API, or artifacts."""

import pytest

from alpaca_quant.research.data_contract import (
    ADJ_BACK_ADJUSTED,
    ADJ_PIT_SAFE,
    ADJ_UNKNOWN,
)
from alpaca_quant.research.feature_registry import (
    NEUTRAL_SAMPLE_DEFINITIONS,
    VERDICT_OK,
    VERDICT_REJECTED,
    VERDICT_SUSPECT,
    FeatureDefinition,
    FeatureRegistryError,
    RegistryValidationConfig,
    build_registry,
    compute_feature_set_id,
    export_feature_definitions,
    list_definitions,
    validate_definition,
    validate_feature_set,
)


def _neutral(name: str = "bar_volume_raw", **overrides) -> FeatureDefinition:
    base = {
        "name": name,
        "family": "mechanical",
        "description": "neutral pass-through feature",
        "dtype": "float64",
        "source": "caller_provided",
        "pit_safe": True,
    }
    base.update(overrides)
    return FeatureDefinition(**base)


# --- definition validation -------------------------------------------------


def test_safe_neutral_feature_passes() -> None:
    assert validate_definition(_neutral()).verdict == VERDICT_OK


def test_sample_neutral_definitions_all_pass() -> None:
    for definition in NEUTRAL_SAMPLE_DEFINITIONS:
        assert validate_definition(definition).verdict == VERDICT_OK


def test_future_looking_feature_rejected() -> None:
    verdict = validate_definition(_neutral(uses_future_data=True))
    assert verdict.verdict == VERDICT_REJECTED
    assert any(r["code"] == "uses_future_data" for r in verdict.reasons)


def test_alpha_like_flag_rejected() -> None:
    assert validate_definition(_neutral(is_alpha_like=True)).verdict == VERDICT_REJECTED


def test_alpha_like_name_rejected() -> None:
    verdict = validate_definition(_neutral(name="rsi_14"))
    assert verdict.verdict == VERDICT_REJECTED
    assert any(r["code"] == "alpha_like_name" for r in verdict.reasons)


def test_phase_not_allowed_rejected() -> None:
    verdict = validate_definition(_neutral(allowed_in_phase=("4C",)))
    assert verdict.verdict == VERDICT_REJECTED
    assert any(r["code"] == "phase_not_allowed" for r in verdict.reasons)


def test_not_pit_safe_is_suspect() -> None:
    verdict = validate_definition(_neutral(pit_safe=False))
    assert verdict.verdict == VERDICT_SUSPECT
    assert any(r["code"] == "not_declared_pit_safe" for r in verdict.reasons)


def test_unknown_adjustment_defaults_to_suspect() -> None:
    definition = _neutral(
        name="px_level", requires_adjusted_price=True, adjustment_safety=ADJ_UNKNOWN
    )
    assert validate_definition(definition).verdict == VERDICT_SUSPECT


def test_unknown_adjustment_can_be_rejected_by_config() -> None:
    definition = _neutral(
        name="px_level", requires_adjusted_price=True, adjustment_safety=ADJ_UNKNOWN
    )
    config = RegistryValidationConfig(unknown_adjustment_verdict=VERDICT_REJECTED)
    assert validate_definition(definition, config=config).verdict == VERDICT_REJECTED


def test_back_adjusted_price_level_rejected() -> None:
    definition = _neutral(
        name="px_level",
        requires_adjusted_price=True,
        adjustment_safety=ADJ_BACK_ADJUSTED,
        pit_safe=True,
    )
    assert validate_definition(definition).verdict == VERDICT_REJECTED


def test_pit_safe_price_level_passes() -> None:
    definition = _neutral(
        name="px_level",
        requires_adjusted_price=True,
        adjustment_safety=ADJ_PIT_SAFE,
        pit_safe=True,
    )
    assert validate_definition(definition).verdict == VERDICT_OK


def test_price_level_without_pit_safe_declaration_is_suspect() -> None:
    definition = _neutral(
        name="px_level",
        requires_adjusted_price=True,
        adjustment_safety=ADJ_PIT_SAFE,
        pit_safe=False,
    )
    verdict = validate_definition(definition)
    assert verdict.verdict == VERDICT_SUSPECT


def test_all_reasons_listed_not_just_first() -> None:
    verdict = validate_definition(
        _neutral(name="alpha_raw", uses_future_data=True, pit_safe=False)
    )
    codes = {r["code"] for r in verdict.reasons}
    assert {"uses_future_data", "not_declared_pit_safe"} <= codes


def test_invalid_null_policy_rejected() -> None:
    with pytest.raises(FeatureRegistryError):
        _neutral(null_policy="zero_fill")


def test_invalid_version_rejected() -> None:
    with pytest.raises(FeatureRegistryError):
        _neutral(version=0)


# --- feature_set_id determinism -------------------------------------------


def test_feature_set_id_invariant_to_order() -> None:
    a = compute_feature_set_id([_neutral("a"), _neutral("b")])
    b = compute_feature_set_id([_neutral("b"), _neutral("a")])
    assert a == b


def test_feature_set_id_changes_with_version() -> None:
    a = compute_feature_set_id([_neutral("a", version=1)])
    b = compute_feature_set_id([_neutral("a", version=2)])
    assert a != b


def test_feature_set_id_changes_with_membership() -> None:
    a = compute_feature_set_id([_neutral("a")])
    b = compute_feature_set_id([_neutral("a"), _neutral("b")])
    assert a != b


def test_feature_set_id_stable_string() -> None:
    fsid = compute_feature_set_id([_neutral("a")])
    assert fsid.startswith("fs-")
    assert fsid == compute_feature_set_id([_neutral("a")])


def test_feature_set_id_rejects_duplicates() -> None:
    with pytest.raises(FeatureRegistryError):
        compute_feature_set_id([_neutral("a"), _neutral("a")])


# --- registry container & feature set validation ---------------------------


def test_build_registry_rejects_duplicates() -> None:
    with pytest.raises(FeatureRegistryError):
        build_registry([_neutral("a"), _neutral("a")])


def test_registry_lookup_and_listing() -> None:
    registry = build_registry([_neutral("b"), _neutral("a")])
    assert registry.names() == ["a", "b"]
    assert registry.has("a")
    assert [row["name"] for row in list_definitions(registry)] == ["a", "b"]
    with pytest.raises(FeatureRegistryError):
        registry.get("missing")


def test_validate_feature_set_ok_for_neutral() -> None:
    result = validate_feature_set(list(NEUTRAL_SAMPLE_DEFINITIONS))
    assert result.verdict == VERDICT_OK
    assert result.rejected == ()
    assert result.feature_set_id.startswith("fs-")


def test_validate_feature_set_flags_rejected() -> None:
    result = validate_feature_set([_neutral("a"), _neutral("b", uses_future_data=True)])
    assert result.verdict == VERDICT_REJECTED
    assert "b" in result.rejected


def test_validate_feature_set_empty_rejected() -> None:
    with pytest.raises(FeatureRegistryError):
        validate_feature_set([])


def test_export_feature_definitions_is_sorted_table() -> None:
    rows = export_feature_definitions([_neutral("z"), _neutral("a")])
    assert [r["name"] for r in rows] == ["a", "z"]
    assert rows[0]["verdict"] == VERDICT_OK
    assert "adjustment_safety" in rows[0]
