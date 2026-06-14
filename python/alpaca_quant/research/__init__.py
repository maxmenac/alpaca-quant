"""Research scratch space (notebooks, experiments). Never imported in production.

Sprint 4A exposes a local-only dataset loader that aligns bars + computed features.
Sprint 4B adds multi-symbol loading, an as_of lookahead guard, and a lightweight
research dataset manifest.
No trading, no backtesting, no model training, no Alpaca API calls.
"""

from alpaca_quant.research.dataset import (
    ResearchDatasetError,
    ResearchDatasetManifest,
    ResearchDatasetSummary,
    build_research_dataset_manifest,
    load_research_dataset,
    summarize_research_dataset,
)

__all__ = [
    "ResearchDatasetError",
    "ResearchDatasetManifest",
    "ResearchDatasetSummary",
    "build_research_dataset_manifest",
    "load_research_dataset",
    "summarize_research_dataset",
]
