"""Research scratch space (notebooks, experiments). Never imported in production.

Sprint 4A exposes a local-only dataset loader that aligns bars + computed features.
No trading, no backtesting, no model training, no Alpaca API calls.
"""

from alpaca_quant.research.dataset import (
    ResearchDatasetError,
    ResearchDatasetSummary,
    load_research_dataset,
    summarize_research_dataset,
)

__all__ = [
    "ResearchDatasetError",
    "ResearchDatasetSummary",
    "load_research_dataset",
    "summarize_research_dataset",
]
