"""Phase 4C data contract: feature availability + adjusted-close safety declarations.

This module declares and enforces the anti-leakage contract for ML dataset assembly. It does
NOT compute features, alpha, signals, strategies, models, weights, or trades. It only classifies
caller-provided feature columns as PIT-safe, suspect, or rejected so that assembly can fail
closed on ambiguous price-level (back-adjusted) features instead of silently trusting them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

# Feature availability semantics: when is the information embedded in a feature value known?
AVAILABILITY_POINT_IN_TIME = "point_in_time"
"""The feature value for row t uses only information available at or before t."""
AVAILABILITY_LAGGED = "lagged"
"""The feature uses only information available at or before t - lag_bars (extra safety margin)."""

SUPPORTED_AVAILABILITY = frozenset({AVAILABILITY_POINT_IN_TIME, AVAILABILITY_LAGGED})

# Adjustment policy for price-level features (back-adjustment leak surface).
ADJ_NOT_APPLICABLE = "not_applicable"
"""Feature is not a price level (e.g. a count, ratio, or already-PIT return)."""
ADJ_PIT_SAFE = "pit_safe"
"""Price-level feature uses as-reported (un-back-adjusted) prices; safe against future splits."""
ADJ_BACK_ADJUSTED = "back_adjusted"
"""Price-level feature uses back-adjusted prices; UNSAFE — rewritten by future splits/dividends."""
ADJ_UNKNOWN = "unknown"
"""Adjustment provenance is undeclared; treated as ambiguous (SUSPECT), never silently safe."""

SUPPORTED_ADJUSTMENT = frozenset(
    {ADJ_NOT_APPLICABLE, ADJ_PIT_SAFE, ADJ_BACK_ADJUSTED, ADJ_UNKNOWN}
)

# Classification outcomes for a declared feature.
CLASS_SAFE = "safe"
CLASS_SUSPECT = "suspect"
CLASS_REJECTED = "rejected"

# Names that look like alpha/signal/strategy output and must not enter as 4C features.
FORBIDDEN_FEATURE_TOKENS: frozenset[str] = frozenset(
    {
        "alpha",
        "signal",
        "prediction",
        "score",
        "weight",
        "target",
        "order",
        "trade",
        "position",
        "rank",
        "momentum",
        "rsi",
        "macd",
    }
)


class DataContractError(RuntimeError):
    """Raised when the feature availability / adjusted-close contract cannot be satisfied."""


@dataclass(frozen=True)
class FeatureSpec:
    """Declared availability + adjustment semantics for one pass-through feature column.

    4C never recomputes features; it only carries them through. The spec is the contract that
    lets assembly reject a back-adjusted price-level column instead of leaking future splits.
    """

    name: str
    price_level: bool = False
    adjustment: str = ADJ_NOT_APPLICABLE
    availability: str = AVAILABILITY_POINT_IN_TIME
    lag_bars: int = 0
    required: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise DataContractError("feature name must be a non-empty string")
        if self.name != self.name.strip():
            raise DataContractError(f"feature name {self.name!r} has surrounding whitespace")
        if self.availability not in SUPPORTED_AVAILABILITY:
            raise DataContractError(
                f"feature {self.name!r} has unsupported availability {self.availability!r}"
            )
        if self.adjustment not in SUPPORTED_ADJUSTMENT:
            raise DataContractError(
                f"feature {self.name!r} has unsupported adjustment {self.adjustment!r}"
            )
        if isinstance(self.lag_bars, bool) or not isinstance(self.lag_bars, int):
            raise DataContractError(f"feature {self.name!r} lag_bars must be an integer")
        if self.lag_bars < 0:
            raise DataContractError(f"feature {self.name!r} lag_bars must be >= 0")
        if self.availability == AVAILABILITY_LAGGED and self.lag_bars < 1:
            raise DataContractError(
                f"feature {self.name!r} is lagged but declares lag_bars < 1"
            )
        if not self.price_level and self.adjustment in {ADJ_PIT_SAFE, ADJ_BACK_ADJUSTED}:
            raise DataContractError(
                f"feature {self.name!r} declares price adjustment but is not price_level"
            )
        if self.price_level and self.adjustment == ADJ_NOT_APPLICABLE:
            raise DataContractError(
                f"price-level feature {self.name!r} must declare an adjustment policy "
                f"(one of pit_safe / back_adjusted / unknown)"
            )

    def classify(self) -> str:
        """Return the safety class: rejected (hard unsafe), suspect (ambiguous), or safe."""
        if self.price_level and self.adjustment == ADJ_BACK_ADJUSTED:
            return CLASS_REJECTED
        if self.price_level and self.adjustment == ADJ_UNKNOWN:
            return CLASS_SUSPECT
        return CLASS_SAFE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce_spec(value: object) -> FeatureSpec:
    if isinstance(value, FeatureSpec):
        return value
    if isinstance(value, str):
        return FeatureSpec(name=value)
    if isinstance(value, Mapping):
        known = {
            "name",
            "price_level",
            "adjustment",
            "availability",
            "lag_bars",
            "required",
            "description",
        }
        unknown = set(value) - known
        if unknown:
            raise DataContractError(
                f"feature spec has unknown keys: {sorted(unknown)}"
            )
        return FeatureSpec(**value)  # type: ignore[arg-type]
    raise DataContractError("feature spec must be a FeatureSpec, str, or mapping")


def normalize_feature_specs(
    specs: Sequence[FeatureSpec | str | Mapping[str, Any]],
) -> tuple[FeatureSpec, ...]:
    """Coerce, validate, and de-duplicate declared feature specs.

    Rejects empty declarations, duplicate names, and names that look like alpha/signal output.
    """
    if not specs:
        raise DataContractError("at least one feature spec is required")
    resolved = tuple(_coerce_spec(item) for item in specs)
    seen: set[str] = set()
    for spec in resolved:
        if spec.name in seen:
            raise DataContractError(f"duplicate feature spec for column {spec.name!r}")
        seen.add(spec.name)
        lowered = spec.name.lower()
        hits = sorted(
            token
            for token in FORBIDDEN_FEATURE_TOKENS
            if token in lowered.split("_") or token == lowered
        )
        if hits:
            raise DataContractError(
                f"feature {spec.name!r} looks like alpha/signal output (matched {hits}); "
                f"4C carries mechanical features only"
            )
    return resolved


def classify_feature_specs(
    specs: Sequence[FeatureSpec],
) -> dict[str, list[str]]:
    """Group declared feature names by safety class (safe / suspect / rejected)."""
    grouped: dict[str, list[str]] = {
        CLASS_SAFE: [],
        CLASS_SUSPECT: [],
        CLASS_REJECTED: [],
    }
    for spec in specs:
        grouped[spec.classify()].append(spec.name)
    for names in grouped.values():
        names.sort()
    return grouped


def assert_features_acceptable(specs: Sequence[FeatureSpec]) -> list[str]:
    """Fail closed on rejected (back-adjusted price-level) features; return suspect names.

    Raises ``DataContractError`` when any feature is hard-unsafe. Suspect (ambiguous adjustment)
    features are allowed through but returned so callers can mark the dataset SUSPECT.
    """
    grouped = classify_feature_specs(specs)
    if grouped[CLASS_REJECTED]:
        raise DataContractError(
            "back-adjusted price-level features are not PIT-safe and were not declared safe: "
            f"{grouped[CLASS_REJECTED]}"
        )
    return list(grouped[CLASS_SUSPECT])


def feature_availability_summary(specs: Sequence[FeatureSpec]) -> list[dict[str, Any]]:
    """Return a stable, serializable description of every feature's availability contract."""
    rows = [
        {
            "name": spec.name,
            "price_level": spec.price_level,
            "adjustment": spec.adjustment,
            "availability": spec.availability,
            "lag_bars": spec.lag_bars,
            "required": spec.required,
            "safety_class": spec.classify(),
        }
        for spec in specs
    ]
    return sorted(rows, key=lambda item: item["name"])
