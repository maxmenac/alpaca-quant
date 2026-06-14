"""Tests for fail-closed data quality declarations."""

import pytest
import yaml
from pydantic import ValidationError

from alpaca_quant.data.manifest import DataDeclaration


def declaration(**overrides) -> DataDeclaration:
    values = {
        "data_declaration_id": "dq-tier0-us-active-2026-06-14",
        "tier": 0,
        "universe_source": "alpaca-us-active-2026",
        "universe_id": "us-active-v001",
        "survivorship_bias_status": "partial",
        "corporate_actions_status": "partial",
        "pit_status": "best_effort",
        "data_feed": "sip-historical",
        "date_range": ["2020-01-01", "2026-06-01"],
        "known_gaps": ["pre-2020 delistings missing"],
    }
    values.update(overrides)
    return DataDeclaration(**values)


def test_valid_tier_0_declaration():
    manifest = declaration()

    assert manifest.tier == 0
    assert manifest.survivorship_bias_status == "partial"
    assert manifest.pit_status == "best_effort"


def test_valid_tier_1_declaration():
    manifest = declaration(
        data_declaration_id="dq-tier1-us-largecap-2026-06-14",
        tier=1,
        universe_id="us-largecap-v001",
        corporate_actions_status="clean",
    )

    assert manifest.tier == 1
    assert manifest.corporate_actions_status == "clean"


def test_invalid_tier_rejected():
    with pytest.raises(ValidationError):
        declaration(tier=3)


@pytest.mark.parametrize(
    "date_range",
    [
        ["2026-06-01"],
        ["2020-01-01", "2026-06-01", "2026-06-14"],
        ["2026-06-01", "2020-01-01"],
    ],
)
def test_invalid_date_range_rejected(date_range):
    with pytest.raises(ValidationError):
        declaration(date_range=date_range)


def test_tier_2_without_controlled_survivorship_rejected():
    with pytest.raises(ValidationError, match="controlled survivorship"):
        declaration(tier=2, survivorship_bias_status="partial", pit_status="guaranteed")


def test_tier_2_without_guaranteed_pit_rejected():
    with pytest.raises(ValidationError, match="guaranteed point-in-time"):
        declaration(tier=2, survivorship_bias_status="controlled", pit_status="best_effort")


def test_serialization_helpers_emit_manifest():
    manifest = declaration()

    serialized = manifest.to_dict()
    assert serialized["date_range"] == ["2020-01-01", "2026-06-01"]

    document = yaml.safe_load(manifest.to_yaml())
    assert document == {"data_declaration": serialized}
