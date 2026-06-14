"""Research scratch space (notebooks, experiments). Never imported in production.

Sprint 4A exposes a local-only dataset loader that aligns bars + computed features.
Sprint 4B adds multi-symbol loading, an as_of lookahead guard, and a lightweight
research dataset manifest.
Sprint 5A adds an append-only experiment registry (discipline scaffolding for future
backtests; records metadata only, no backtest runs yet).
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
from alpaca_quant.research.experiment_registry import (
    ExperimentRecord,
    ExperimentRegistryError,
    append_experiment_record,
    capture_git_sha,
    create_experiment_run_id,
    new_experiment_record,
    read_experiment_records,
)

__all__ = [
    "ExperimentRecord",
    "ExperimentRegistryError",
    "ResearchDatasetError",
    "ResearchDatasetManifest",
    "ResearchDatasetSummary",
    "append_experiment_record",
    "build_research_dataset_manifest",
    "capture_git_sha",
    "create_experiment_run_id",
    "load_research_dataset",
    "new_experiment_record",
    "read_experiment_records",
    "summarize_research_dataset",
]
