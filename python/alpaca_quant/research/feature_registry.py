"""Phase 4D local feature registry: neutral/mechanical feature DEFINITIONS only.

The registry holds metadata, provenance, and availability semantics for pass-through features.
It NEVER computes a feature, searches for edge, or generates alpha/signal/weight/strategy. Its
job is to stop unsafe (future-looking, alpha-like, or ambiguously adjusted) features from
silently entering a Phase 4C dataset. Conservative by default: a feature is never assumed safe
from its name alone.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from alpaca_quant.research.data_contract import (
    ADJ_BACK_ADJUSTED,
    ADJ_NOT_APPLICABLE,
    ADJ_PIT_SAFE,
    ADJ_UNKNOWN,
    AVAILABILITY_LAGGED,
    AVAILABILITY_POINT_IN_TIME,
    SUPPORTED_ADJUSTMENT,
    SUPPORTED_AVAILABILITY,
    FeatureSpec,
)

FEATURE_REGISTRY_SCHEMA_VERSION = 1
CURRENT_PHASE = "4D"

# Verdicts (precedence: REJECTED > SUSPECT > OK).
VERDICT_OK = "OK"
VERDICT_SUSPECT = "SUSPECT"
VERDICT_REJECTED = "REJECTED"
_VERDICT_RANK = {VERDICT_OK: 0, VERDICT_SUSPECT: 1, VERDICT_REJECTED: 2}

# feature_cutoff_rule vocabulary (mechanical, declared — never inferred from data).
CUTOFF_PRIOR_BAR = "prior_bar"
CUTOFF_SAME_BAR = "same_bar"
CUTOFF_ASOF_AVAILABLE_AT = "asof_available_at"
SUPPORTED_CUTOFF_RULES = frozenset({CUTOFF_PRIOR_BAR, CUTOFF_SAME_BAR, CUTOFF_ASOF_AVAILABLE_AT})

# null_policy vocabulary (no fill / no imputation is the only safe policy in this layer).
NULL_PRESERVE = "preserve"
SUPPORTED_NULL_POLICIES = frozenset({NULL_PRESERVE})

# Name tokens that betray alpha/signal intent; used only as an extra guard, never as a safety
# certificate (a clean name never makes a feature safe).
ALPHA_LIKE_TOKENS: frozenset[str] = frozenset(
    {
        "alpha",
        "signal",
        "edge",
        "rsi",
        "macd",
        "momentum",
        "rank",
        "zscore",
        "factor",
        "score",
        "forecast",
        "prediction",
        "weight",
    }
)


class FeatureRegistryError(RuntimeError):
    """Raised when a feature definition or feature set cannot be registered or validated safely."""


@dataclass(frozen=True)
class RegistryValidationConfig:
    """Deterministic knobs for how aggressively ambiguity is treated. No randomness."""

    unknown_adjustment_verdict: str = VERDICT_SUSPECT
    unsafe_price_level_verdict: str = VERDICT_SUSPECT
    phase: str = CURRENT_PHASE

    def __post_init__(self) -> None:
        for name in ("unknown_adjustment_verdict", "unsafe_price_level_verdict"):
            value = getattr(self, name)
            if value not in {VERDICT_SUSPECT, VERDICT_REJECTED}:
                raise FeatureRegistryError(
                    f"{name} must be {VERDICT_SUSPECT!r} or {VERDICT_REJECTED!r}"
                )
        if not isinstance(self.phase, str) or not self.phase.strip():
            raise FeatureRegistryError("phase must be a non-empty string")


@dataclass(frozen=True)
class FeatureDefinition:
    """Neutral, mechanical metadata for one pass-through feature column. No computation here."""

    name: str
    family: str
    description: str
    dtype: str
    source: str
    availability: str = AVAILABILITY_POINT_IN_TIME
    feature_cutoff_rule: str = CUTOFF_PRIOR_BAR
    requires_adjusted_price: bool = False
    adjustment_safety: str = ADJ_NOT_APPLICABLE
    pit_safe: bool = False
    uses_future_data: bool = False
    null_policy: str = NULL_PRESERVE
    is_alpha_like: bool = False
    allowed_in_phase: tuple[str, ...] = ("4C", "4D")
    version: int = 1

    def __post_init__(self) -> None:
        for text_field in ("name", "family", "description", "dtype", "source"):
            value = getattr(self, text_field)
            if not isinstance(value, str) or not value.strip():
                raise FeatureRegistryError(f"feature {text_field!r} must be a non-empty string")
        if self.name != self.name.strip():
            raise FeatureRegistryError(f"feature name {self.name!r} has surrounding whitespace")
        if self.availability not in SUPPORTED_AVAILABILITY:
            raise FeatureRegistryError(
                f"feature {self.name!r} has unsupported availability {self.availability!r}"
            )
        if self.feature_cutoff_rule not in SUPPORTED_CUTOFF_RULES:
            raise FeatureRegistryError(
                f"feature {self.name!r} has unsupported feature_cutoff_rule "
                f"{self.feature_cutoff_rule!r}"
            )
        if self.adjustment_safety not in SUPPORTED_ADJUSTMENT:
            raise FeatureRegistryError(
                f"feature {self.name!r} has unsupported adjustment_safety "
                f"{self.adjustment_safety!r}"
            )
        if self.null_policy not in SUPPORTED_NULL_POLICIES:
            raise FeatureRegistryError(
                f"feature {self.name!r} declares unsupported null_policy {self.null_policy!r}; "
                f"only {NULL_PRESERVE!r} is allowed (no fill / no imputation)"
            )
        for flag in ("requires_adjusted_price", "pit_safe", "uses_future_data", "is_alpha_like"):
            if not isinstance(getattr(self, flag), bool):
                raise FeatureRegistryError(f"feature {self.name!r} {flag} must be a boolean")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise FeatureRegistryError(f"feature {self.name!r} version must be an integer >= 1")
        if not self.allowed_in_phase:
            raise FeatureRegistryError(f"feature {self.name!r} must allow at least one phase")
        if self.availability == AVAILABILITY_LAGGED and self.feature_cutoff_rule == CUTOFF_SAME_BAR:
            raise FeatureRegistryError(
                f"feature {self.name!r} is lagged but declares same_bar cutoff"
            )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_in_phase"] = list(self.allowed_in_phase)
        return data

    def to_feature_spec(self) -> FeatureSpec:
        """Project this definition onto the Phase 4C data-contract FeatureSpec."""
        adjustment = self.adjustment_safety
        if not self.requires_adjusted_price:
            adjustment = ADJ_NOT_APPLICABLE
        return FeatureSpec(
            name=self.name,
            price_level=self.requires_adjusted_price,
            adjustment=adjustment,
            availability=self.availability,
            lag_bars=1 if self.availability == AVAILABILITY_LAGGED else 0,
        )


@dataclass(frozen=True)
class DefinitionVerdict:
    """Verdict (OK/SUSPECT/REJECTED) plus every reason — never just the first."""

    name: str
    verdict: str
    reasons: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "verdict": self.verdict, "reasons": list(self.reasons)}


def _coerce_definition(value: object) -> FeatureDefinition:
    if isinstance(value, FeatureDefinition):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        known = set(FeatureDefinition.__dataclass_fields__)
        unknown = set(payload) - known
        if unknown:
            raise FeatureRegistryError(f"feature definition has unknown keys: {sorted(unknown)}")
        if "allowed_in_phase" in payload and not isinstance(payload["allowed_in_phase"], tuple):
            payload["allowed_in_phase"] = tuple(payload["allowed_in_phase"])
        return FeatureDefinition(**payload)
    raise FeatureRegistryError("feature definition must be a FeatureDefinition or mapping")


def _reason(code: str, severity: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message}


def validate_definition(
    definition: FeatureDefinition | Mapping[str, Any],
    *,
    config: RegistryValidationConfig | None = None,
) -> DefinitionVerdict:
    """Apply the conservative decision rules and return a verdict with all reasons.

    Rules (each contributes a reason; the worst severity wins):
      2. uses_future_data        -> REJECTED
      3. is_alpha_like           -> REJECTED for the validation phase
         phase not allowed       -> REJECTED
         name looks alpha-like   -> REJECTED (extra guard)
      4. unknown adjustment      -> SUSPECT (or REJECTED per config)
      5. price-level w/o pit_safe -> SUSPECT/REJECTED per config
      1. not pit_safe            -> SUSPECT (never assumed safe)
    """
    resolved = config or RegistryValidationConfig()
    definition = _coerce_definition(definition)
    reasons: list[dict[str, Any]] = []

    if definition.uses_future_data:
        reasons.append(
            _reason(
                "uses_future_data",
                VERDICT_REJECTED,
                f"feature {definition.name!r} declares uses_future_data=True (look-ahead).",
            )
        )
    if definition.is_alpha_like:
        reasons.append(
            _reason(
                "alpha_like_feature",
                VERDICT_REJECTED,
                f"feature {definition.name!r} is declared alpha-like; rejected pre-alpha.",
            )
        )
    if resolved.phase not in definition.allowed_in_phase:
        reasons.append(
            _reason(
                "phase_not_allowed",
                VERDICT_REJECTED,
                f"feature {definition.name!r} is not allowed in phase {resolved.phase!r} "
                f"(allowed: {list(definition.allowed_in_phase)}).",
            )
        )
    lowered = definition.name.lower()
    name_hits = sorted(t for t in ALPHA_LIKE_TOKENS if t in lowered.split("_") or t == lowered)
    if name_hits:
        reasons.append(
            _reason(
                "alpha_like_name",
                VERDICT_REJECTED,
                f"feature name {definition.name!r} matches alpha-like tokens {name_hits}.",
            )
        )

    if definition.requires_adjusted_price:
        if definition.adjustment_safety == ADJ_BACK_ADJUSTED:
            reasons.append(
                _reason(
                    "back_adjusted_price_level",
                    VERDICT_REJECTED,
                    f"price-level feature {definition.name!r} uses back-adjusted prices.",
                )
            )
        elif definition.adjustment_safety == ADJ_UNKNOWN:
            reasons.append(
                _reason(
                    "ambiguous_adjustment",
                    resolved.unknown_adjustment_verdict,
                    f"price-level feature {definition.name!r} has unknown adjustment safety.",
                )
            )
        elif definition.adjustment_safety != ADJ_PIT_SAFE or not definition.pit_safe:
            reasons.append(
                _reason(
                    "undeclared_price_level_safety",
                    resolved.unsafe_price_level_verdict,
                    f"price-level feature {definition.name!r} lacks an explicit PIT-safe "
                    f"adjustment declaration.",
                )
            )
    elif definition.adjustment_safety == ADJ_UNKNOWN:
        reasons.append(
            _reason(
                "ambiguous_adjustment",
                resolved.unknown_adjustment_verdict,
                f"feature {definition.name!r} has unknown adjustment safety.",
            )
        )

    if not definition.pit_safe:
        reasons.append(
            _reason(
                "not_declared_pit_safe",
                VERDICT_SUSPECT,
                f"feature {definition.name!r} is not declared pit_safe; never assumed safe.",
            )
        )

    verdict = VERDICT_OK
    for item in reasons:
        if _VERDICT_RANK[item["severity"]] > _VERDICT_RANK[verdict]:
            verdict = item["severity"]
    return DefinitionVerdict(name=definition.name, verdict=verdict, reasons=tuple(reasons))


@dataclass(frozen=True)
class FeatureRegistry:
    """An immutable collection of neutral feature definitions keyed by name."""

    definitions: tuple[FeatureDefinition, ...] = field(default_factory=tuple)

    def names(self) -> list[str]:
        return sorted(d.name for d in self.definitions)

    def get(self, name: str) -> FeatureDefinition:
        for definition in self.definitions:
            if definition.name == name:
                return definition
        raise FeatureRegistryError(f"feature {name!r} is not in the registry")

    def has(self, name: str) -> bool:
        return any(d.name == name for d in self.definitions)


def build_registry(
    definitions: Sequence[FeatureDefinition | Mapping[str, Any]],
) -> FeatureRegistry:
    """Register definitions, rejecting duplicates. No definition is computed or executed."""
    resolved = tuple(_coerce_definition(item) for item in definitions)
    seen: set[str] = set()
    for definition in resolved:
        if definition.name in seen:
            raise FeatureRegistryError(f"duplicate feature definition for {definition.name!r}")
        seen.add(definition.name)
    return FeatureRegistry(definitions=resolved)


def list_definitions(registry: FeatureRegistry) -> list[dict[str, Any]]:
    """Return registry definitions as stable, serializable dicts sorted by name."""
    return [
        registry.get(name).to_dict() for name in registry.names()
    ]


def _canonical_definition(definition: FeatureDefinition) -> dict[str, Any]:
    data = definition.to_dict()
    data["allowed_in_phase"] = sorted(data["allowed_in_phase"])
    return data


def compute_feature_set_id(
    definitions: Sequence[FeatureDefinition | Mapping[str, Any]],
) -> str:
    """Deterministic id for a feature set: invariant to order, sensitive to version/values.

    Canonical JSON over name-sorted definitions (including each ``version``). Stable across
    processes and independent of environment.
    """
    resolved = [_coerce_definition(item) for item in definitions]
    names = [d.name for d in resolved]
    if len(names) != len(set(names)):
        raise FeatureRegistryError("feature set contains duplicate feature names")
    canonical = json.dumps(
        {
            "schema_version": FEATURE_REGISTRY_SCHEMA_VERSION,
            "features": sorted(
                (_canonical_definition(d) for d in resolved),
                key=lambda item: item["name"],
            ),
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"fs-{digest[:12]}"


@dataclass(frozen=True)
class FeatureSetValidation:
    """Outcome of validating a requested feature set against the 4C data contract."""

    feature_set_id: str
    verdict: str
    per_feature: tuple[DefinitionVerdict, ...]
    rejected: tuple[str, ...]
    suspect: tuple[str, ...]
    reasons: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_set_id": self.feature_set_id,
            "verdict": self.verdict,
            "per_feature": [v.to_dict() for v in self.per_feature],
            "rejected": list(self.rejected),
            "suspect": list(self.suspect),
            "reasons": list(self.reasons),
        }


def validate_feature_set(
    definitions: Sequence[FeatureDefinition | Mapping[str, Any]],
    *,
    config: RegistryValidationConfig | None = None,
) -> FeatureSetValidation:
    """Validate every definition and cross-check against the Phase 4C data contract."""
    resolved = [_coerce_definition(item) for item in definitions]
    if not resolved:
        raise FeatureRegistryError("a feature set must contain at least one definition")
    per_feature = tuple(validate_definition(d, config=config) for d in resolved)
    rejected = tuple(v.name for v in per_feature if v.verdict == VERDICT_REJECTED)
    suspect = tuple(v.name for v in per_feature if v.verdict == VERDICT_SUSPECT)
    reasons: list[dict[str, Any]] = []
    for v in per_feature:
        reasons.extend(v.reasons)

    # Cross-check with the 4C contract: it must agree that no feature is hard-unsafe.
    from alpaca_quant.research.data_contract import (
        DataContractError,
        assert_features_acceptable,
        normalize_feature_specs,
    )

    if not rejected:
        try:
            specs = normalize_feature_specs([d.to_feature_spec() for d in resolved])
            assert_features_acceptable(specs)
        except DataContractError as exc:  # pragma: no cover - defensive parity check
            reasons.append(_reason("data_contract_rejection", VERDICT_REJECTED, str(exc)))
            rejected = tuple(sorted({*rejected, *(d.name for d in resolved)}))

    verdict = VERDICT_OK
    for item in reasons:
        if _VERDICT_RANK.get(item["severity"], 0) > _VERDICT_RANK[verdict]:
            verdict = item["severity"]

    return FeatureSetValidation(
        feature_set_id=compute_feature_set_id(resolved),
        verdict=verdict,
        per_feature=per_feature,
        rejected=rejected,
        suspect=suspect,
        reasons=tuple(reasons),
    )


def export_feature_definitions(
    definitions: Sequence[FeatureDefinition | Mapping[str, Any]],
    *,
    config: RegistryValidationConfig | None = None,
) -> list[dict[str, Any]]:
    """Export a serializable feature safety + availability table for manifests/reports."""
    resolved = [_coerce_definition(item) for item in definitions]
    rows = []
    for definition in resolved:
        verdict = validate_definition(definition, config=config)
        rows.append(
            {
                "name": definition.name,
                "family": definition.family,
                "version": definition.version,
                "availability": definition.availability,
                "feature_cutoff_rule": definition.feature_cutoff_rule,
                "requires_adjusted_price": definition.requires_adjusted_price,
                "adjustment_safety": definition.adjustment_safety,
                "pit_safe": definition.pit_safe,
                "uses_future_data": definition.uses_future_data,
                "is_alpha_like": definition.is_alpha_like,
                "null_policy": definition.null_policy,
                "verdict": verdict.verdict,
            }
        )
    return sorted(rows, key=lambda item: item["name"])


# --- Neutral synthetic definitions (test/fixture use only — declared metadata, no computation) -

NEUTRAL_SAMPLE_DEFINITIONS: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(
        name="close_to_open_return_declared",
        family="mechanical_return",
        description="Declared pass-through close/open ratio return supplied by upstream.",
        dtype="float64",
        source="caller_provided",
        availability=AVAILABILITY_POINT_IN_TIME,
        feature_cutoff_rule=CUTOFF_PRIOR_BAR,
        pit_safe=True,
    ),
    FeatureDefinition(
        name="bar_volume_raw",
        family="mechanical_volume",
        description="Raw traded volume for the bar, as reported.",
        dtype="float64",
        source="caller_provided",
        pit_safe=True,
    ),
    FeatureDefinition(
        name="spread_bps_mock",
        family="mechanical_microstructure",
        description="Mock declared spread in basis points (synthetic fixture only).",
        dtype="float64",
        source="caller_provided",
        pit_safe=True,
    ),
    FeatureDefinition(
        name="sector_code_asof_mock",
        family="reference_categorical",
        description="Mock sector code joined as-of available_at (synthetic fixture only).",
        dtype="utf8",
        source="reference_table",
        availability=AVAILABILITY_LAGGED,
        feature_cutoff_rule=CUTOFF_ASOF_AVAILABLE_AT,
        pit_safe=True,
    ),
    FeatureDefinition(
        name="shares_outstanding_asof_mock",
        family="reference_fundamental",
        description="Mock shares outstanding joined as-of available_at (synthetic fixture only).",
        dtype="float64",
        source="reference_table",
        availability=AVAILABILITY_LAGGED,
        feature_cutoff_rule=CUTOFF_ASOF_AVAILABLE_AT,
        pit_safe=True,
    ),
)


__all__ = [
    "ALPHA_LIKE_TOKENS",
    "CUTOFF_ASOF_AVAILABLE_AT",
    "CUTOFF_PRIOR_BAR",
    "CUTOFF_SAME_BAR",
    "FEATURE_REGISTRY_SCHEMA_VERSION",
    "NEUTRAL_SAMPLE_DEFINITIONS",
    "NULL_PRESERVE",
    "VERDICT_OK",
    "VERDICT_REJECTED",
    "VERDICT_SUSPECT",
    "DefinitionVerdict",
    "FeatureDefinition",
    "FeatureRegistry",
    "FeatureRegistryError",
    "FeatureSetValidation",
    "RegistryValidationConfig",
    "build_registry",
    "compute_feature_set_id",
    "export_feature_definitions",
    "list_definitions",
    "validate_definition",
    "validate_feature_set",
]
