# Alpaca Quant — Current Handoff

Latest clean state:
- Branch: main
- Latest commit: 4c5cef0 feat: add research dataset skeleton
- Repo clean and synced with origin/main (before Sprint 4B work)

Current pipeline:
config loader -> data declaration manifest -> Alpaca bars client -> Parquet writer -> DuckDB query -> mock dry run -> real controlled fetch -> API diagnostics -> run registry -> list-runs CLI -> feature factory -> list-feature-sets CLI -> research dataset loader -> list-research-datasets CLI

Real controlled fetch (alpaca_controlled_002):
- AAPL/MSFT
- 2024-01-02 to 2024-01-08
- feed: iex
- rows_written: 10
- verification_passed: true
- registry artifact produced in local ignored data/runs/

Feature factory (Sprint 3A + 3B):
- compute_features CLI: python scripts/compute_features.py --run <run> --symbol <SYM>
- list_feature_sets CLI: python scripts/list_feature_sets.py --run <run>
- features written to data/runs/<run>/features_<SYM>.parquet (local, not committed)
- manifest written to data/runs/<run>/features_<SYM>_manifest.yaml (local, not committed)
- feature_set_id is deterministic: sha256(resolved_path:SYMBOL)[:8]
- no-lookahead validated by test suite

Research dataset layer (Sprint 4A + 4B):
- load_research_dataset(bars_path, features_path, symbol, start, end, as_of)
  - aligns local bars + features on (symbol, timestamp), inner join, Polars only
  - multi-symbol: symbol accepts list, features_path accepts list of per-symbol files
  - as_of is an inclusive upper-bound lookahead guard, composes with end
  - deterministic sort by (symbol, timestamp); forbidden trading/label columns rejected
- build_research_dataset_manifest(...) -> ResearchDatasetManifest
  - dataset_id deterministic (rds-<sha256[:8]>), created_at UTC, symbols, start/end/as_of,
    bars_path, features_paths, row_count, feature_count, known_gaps,
    no_trading/no_backtesting/no_model_training = true
- inspect_research_dataset CLI: --bars --features... --symbol... --start --end --as-of
  --write-manifest (writes research_dataset_<id>_manifest.yaml, local/ignored)
- list_research_datasets CLI: --run <run> | --dir <path>

Safety:
- .env ignored, contains Alpaca keys, never print/read secrets
- data/runs/ ignored, do not commit data artifacts
- no trading
- no backtesting
- no live execution
- no order submission
- no model training
- feature layer has zero Alpaca API calls

Next recommended sprint:
Sprint 4C / 5A — research protocol scaffolding (experiment registry entries per
RESEARCH_PROTOCOL.md §1) on top of the research dataset layer. Still no labels,
no signals, no backtesting, no model training, no trading.
