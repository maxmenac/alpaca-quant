"""Simple alpha registry: register / get by name.

Placeholder for the metadata-rich registry described in ARCHITECTURE.md §3.3. Concrete
alphas register themselves here so the ensemble and config layers can resolve them by name.
"""

from __future__ import annotations

from alpaca_quant.alphas.base import Alpha

_REGISTRY: dict[str, Alpha] = {}


def register(name: str, alpha: Alpha) -> None:
    """Register ``alpha`` under ``name``.

    Raises:
        ValueError: if ``name`` is already registered (no silent overwrite).
    """
    if name in _REGISTRY:
        raise ValueError(f"alpha already registered: {name!r}")
    _REGISTRY[name] = alpha


def get(name: str) -> Alpha:
    """Return the alpha registered under ``name``.

    Raises:
        KeyError: if ``name`` is not registered.
    """
    return _REGISTRY[name]


def registered_names() -> list[str]:
    """Return the sorted list of registered alpha names."""
    return sorted(_REGISTRY)
