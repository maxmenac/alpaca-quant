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
from alpaca_quant.research.experiment_runner import (
    ExperimentRunError,
    ExperimentRunResult,
    compute_config_hash,
    flatten_experiment_metrics,
    run_backtest_experiment,
)

__all__ = [
    "ExperimentRecord",
    "ExperimentRegistryError",
    "ExperimentRunError",
    "ExperimentRunResult",
    "ResearchDatasetError",
    "ResearchDatasetManifest",
    "ResearchDatasetSummary",
    "append_experiment_record",
    "build_research_dataset_manifest",
    "capture_git_sha",
    "compute_config_hash",
    "create_experiment_run_id",
    "flatten_experiment_metrics",
    "load_research_dataset",
    "new_experiment_record",
    "read_experiment_records",
    "run_backtest_experiment",
    "summarize_research_dataset",
]
