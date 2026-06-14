"""Abstract ``Alpha`` interface.

An alpha maps features to a conviction score in ``[-1, 1]`` per symbol (ARCHITECTURE.md
§3.3, principle P1). Concrete alphas are isolated, testable, and interchangeable.

Polars is the project's dataframe library (see pyproject.toml — polars, not pandas, to
avoid drift). We keep the polars import type-only so that merely importing this interface
does not require heavy data dependencies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    import polars as pl


@dataclass(frozen=True)
class AlphaMetadata:
    """Static description of an alpha.

    Attributes:
        name: Unique registry name.
        horizon: Holding/forecast horizon, e.g. ``"1d"``.
        capacity_usd: Estimated capacity in USD before the edge degrades.
        expected_turnover: Expected annualized turnover (fraction), if known.
        description: Human-readable rationale (economic story for the edge).
    """

    name: str
    horizon: str
    capacity_usd: float
    expected_turnover: float | None = None
    description: str = ""


class Alpha(ABC):
    """Abstract base class for all alphas.

    Subclasses implement :meth:`compute`, returning a conviction score in ``[-1, 1]``
    per symbol, and expose :attr:`metadata`.
    """

    @property
    @abstractmethod
    def metadata(self) -> AlphaMetadata:
        """Static metadata (name, horizon, capacity, ...)."""
        raise NotImplementedError

    @abstractmethod
    def compute(self, features: pl.DataFrame) -> pl.Series:
        """Compute the conviction score per symbol.

        Args:
            features: Point-in-time feature frame (one row per symbol/date).

        Returns:
            A polars ``Series`` of scores in ``[-1, 1]``, one per symbol.
        """
        raise NotImplementedError
