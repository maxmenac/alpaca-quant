"""Alphas (ARCHITECTURE.md §3.3): many weak, uncorrelated signals (P1).

Each alpha maps features -> a conviction score in [-1, 1] per symbol. The public
surface is the abstract ``Alpha`` interface and a simple ``registry``.
"""

from alpaca_quant.alphas.base import Alpha, AlphaMetadata
from alpaca_quant.alphas.registry import get, register, registered_names

__all__ = ["Alpha", "AlphaMetadata", "register", "get", "registered_names"]
