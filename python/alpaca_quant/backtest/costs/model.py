"""Linear transaction-cost model (commission + slippage in bps, applied to turnover).

No costs ignored: a backtest without costs is self-deception (CLAUDE.md). Defaults and stress
multipliers come from configs/costs.yaml (RESEARCH_PROTOCOL.md §2). Cost stress (×2/×5) is
*defined* here but only exercised by the null-model battery in a later sprint.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import]

DEFAULT_COSTS_PATH = "configs/costs.yaml"
_STRESS_FIELD = {
    "none": "slippage_bps_daily",
    "2x": "slippage_bps_stress_2x",
    "5x": "slippage_bps_stress_5x",
}


class CostModelError(RuntimeError):
    """Raised when a cost model cannot be built or loaded safely."""


@dataclass(frozen=True)
class CostModel:
    """Linear cost: total bps charged proportionally to traded turnover."""

    commission_bps: float = 0.0
    slippage_bps: float = 0.0

    @property
    def total_bps(self) -> float:
        return self.commission_bps + self.slippage_bps

    @property
    def rate(self) -> float:
        """Cost as a fraction of traded notional (turnover of 1.0 == full rotation)."""
        return self.total_bps / 10_000.0

    def cost_for_turnover(self, turnover: float) -> float:
        """Cost for a given (non-negative) turnover amount."""
        return abs(turnover) * self.rate


def load_cost_model(path: str | Path = DEFAULT_COSTS_PATH, *, stress: str = "none") -> CostModel:
    """Load a CostModel from a costs YAML file, optionally applying a stress multiplier."""
    if stress not in _STRESS_FIELD:
        raise CostModelError(
            f"unknown stress level {stress!r}; expected one of {list(_STRESS_FIELD)}"
        )
    config_path = Path(path)
    if not config_path.is_file():
        raise CostModelError(f"costs config not found: {config_path}")

    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise CostModelError(f"failed to parse costs config: {config_path}") from exc
    if not isinstance(data, dict):
        raise CostModelError(f"costs config must be a mapping: {config_path}")

    slippage_field = _STRESS_FIELD[stress]
    if slippage_field not in data:
        raise CostModelError(f"costs config missing field {slippage_field!r}")

    return CostModel(
        commission_bps=float(data.get("commission_bps", 0.0)),
        slippage_bps=float(data[slippage_field]),
    )
