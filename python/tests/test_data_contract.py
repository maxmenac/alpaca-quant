"""Phase 4C data contract tests. Synthetic only: no .env, network, API, or artifacts."""

import pytest

from alpaca_quant.research.data_contract import (
    ADJ_BACK_ADJUSTED,
    ADJ_PIT_SAFE,
    ADJ_UNKNOWN,
    AVAILABILITY_LAGGED,
    CLASS_REJECTED,
    CLASS_SAFE,
    CLASS_SUSPECT,
    DataContractError,
    FeatureSpec,
    assert_features_acceptable,
    classify_feature_specs,
    feature_availability_summary,
    normalize_feature_specs,
)


def test_default_feature_is_safe_and_point_in_time() -> None:
    spec = FeatureSpec("dollar_volume")
    assert spec.classify() == CLASS_SAFE
    assert spec.price_level is False


def test_price_level_must_declare_adjustment() -> None:
    with pytest.raises(DataContractError):
        FeatureSpec("close_level", price_level=True)


def test_back_adjusted_price_level_is_rejected() -> None:
    spec = FeatureSpec("close_level", price_level=True, adjustment=ADJ_BACK_ADJUSTED)
    assert spec.classify() == CLASS_REJECTED


def test_unknown_adjusted_price_level_is_suspect() -> None:
    spec = FeatureSpec("close_level", price_level=True, adjustment=ADJ_UNKNOWN)
    assert spec.classify() == CLASS_SUSPECT


def test_pit_safe_price_level_is_safe() -> None:
    spec = FeatureSpec("close_level", price_level=True, adjustment=ADJ_PIT_SAFE)
    assert spec.classify() == CLASS_SAFE


def test_non_price_level_cannot_declare_price_adjustment() -> None:
    with pytest.raises(DataContractError):
        FeatureSpec("ratio", adjustment=ADJ_PIT_SAFE)


def test_lagged_requires_positive_lag() -> None:
    with pytest.raises(DataContractError):
        FeatureSpec("x", availability=AVAILABILITY_LAGGED, lag_bars=0)
    ok = FeatureSpec("x", availability=AVAILABILITY_LAGGED, lag_bars=2)
    assert ok.lag_bars == 2


def test_invalid_availability_and_adjustment_rejected() -> None:
    with pytest.raises(DataContractError):
        FeatureSpec("x", availability="future")
    with pytest.raises(DataContractError):
        FeatureSpec("x", price_level=True, adjustment="magic")


def test_blank_name_rejected() -> None:
    with pytest.raises(DataContractError):
        FeatureSpec("   ")


def test_normalize_rejects_duplicate_names() -> None:
    with pytest.raises(DataContractError):
        normalize_feature_specs([FeatureSpec("a"), FeatureSpec("a")])


def test_normalize_rejects_empty() -> None:
    with pytest.raises(DataContractError):
        normalize_feature_specs([])


@pytest.mark.parametrize("token", ["alpha", "signal", "rsi", "macd", "momentum", "rank"])
def test_normalize_rejects_alpha_like_names(token: str) -> None:
    with pytest.raises(DataContractError):
        normalize_feature_specs([FeatureSpec(token)])


def test_normalize_accepts_string_and_mapping() -> None:
    specs = normalize_feature_specs(["dollar_volume", {"name": "bar_count"}])
    assert [s.name for s in specs] == ["dollar_volume", "bar_count"]


def test_normalize_rejects_unknown_mapping_key() -> None:
    with pytest.raises(DataContractError):
        normalize_feature_specs([{"name": "x", "bogus": 1}])


def test_assert_features_acceptable_raises_on_back_adjusted() -> None:
    specs = normalize_feature_specs(
        [FeatureSpec("close_level", price_level=True, adjustment=ADJ_BACK_ADJUSTED)]
    )
    with pytest.raises(DataContractError):
        assert_features_acceptable(specs)


def test_assert_features_acceptable_returns_suspects() -> None:
    specs = normalize_feature_specs(
        [
            FeatureSpec("vol"),
            FeatureSpec("close_level", price_level=True, adjustment=ADJ_UNKNOWN),
        ]
    )
    suspects = assert_features_acceptable(specs)
    assert suspects == ["close_level"]


def test_classify_groups_by_class() -> None:
    specs = normalize_feature_specs(
        [
            FeatureSpec("a"),
            FeatureSpec("b_level", price_level=True, adjustment=ADJ_UNKNOWN),
            FeatureSpec("c_level", price_level=True, adjustment=ADJ_BACK_ADJUSTED),
        ]
    )
    grouped = classify_feature_specs(specs)
    assert grouped[CLASS_SAFE] == ["a"]
    assert grouped[CLASS_SUSPECT] == ["b_level"]
    assert grouped[CLASS_REJECTED] == ["c_level"]


def test_availability_summary_is_sorted_and_serializable() -> None:
    specs = normalize_feature_specs([FeatureSpec("z"), FeatureSpec("a")])
    summary = feature_availability_summary(specs)
    assert [row["name"] for row in summary] == ["a", "z"]
    assert summary[0]["safety_class"] == CLASS_SAFE
