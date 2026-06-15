"""Research-only datasets, target labels, experiment records, and reports.

Sprint 4A exposes a local-only dataset loader that aligns bars + computed features.
Sprint 4B adds multi-symbol loading, an as_of lookahead guard, and a lightweight
research dataset manifest.
Phase 4A Target / Label Foundation adds audited forward-return labels in a separate
module. Labels are future outcomes only: never features, alpha, signals, or weights.
Sprint 5A adds an append-only experiment registry (discipline scaffolding for future
backtests; records metadata only, no backtest runs yet).
No trading, no model training, no Alpaca API calls.
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
from alpaca_quant.research.targets import (
    TargetLabelError,
    TargetLabelSummary,
    TargetManifest,
    build_forward_return_labels,
    build_target_manifest,
    fingerprint_target_labels,
    summarize_target_labels,
)

__all__ = [
    "ExperimentRecord",
    "ExperimentRegistryError",
    "ExperimentRunError",
    "ExperimentRunResult",
    "ResearchDatasetError",
    "ResearchDatasetManifest",
    "ResearchDatasetSummary",
    "TargetLabelError",
    "TargetLabelSummary",
    "TargetManifest",
    "append_experiment_record",
    "build_forward_return_labels",
    "build_research_dataset_manifest",
    "build_target_manifest",
    "capture_git_sha",
    "compute_config_hash",
    "create_experiment_run_id",
    "flatten_experiment_metrics",
    "fingerprint_target_labels",
    "load_research_dataset",
    "new_experiment_record",
    "read_experiment_records",
    "run_backtest_experiment",
    "summarize_research_dataset",
    "summarize_target_labels",
]
