# Alpaca Quant — Current Handoff

Latest clean state:
- Branch: main
- Latest commit: 0d5f939 feat: polish research dataset workflow
- Repo clean and synced with origin/main (before Sprint 5A work)

Current pipeline:
config loader -> data declaration manifest -> Alpaca bars client -> Parquet writer -> DuckDB query -> mock dry run -> real controlled fetch -> API diagnostics -> run registry -> list-runs CLI -> feature factory -> list-feature-sets CLI -> research dataset loader -> list-research-datasets CLI -> experiment registry -> list-experiments CLI

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

Experiment registry (Sprint 5A):
- append-only JSONL at data/runs/experiment_registry.jsonl (local, git-ignored)
- ExperimentRecord (pydantic, extra=forbid): run_id, created_at (UTC), git_sha,
  dataset_id, dataset_manifest_path, feature_set_id, feature_version, config_hash, seed,
  metrics (empty placeholder), decision (default keep_researching), decided_by, notes,
  kind="experiment", no_trading/no_backtesting/no_model_training=true (enforced True)
- run_id unique & immutable: re-appending an existing run_id is rejected, nothing written
- git_sha captured via subprocess `git rev-parse HEAD` only (local, never networks)
- new_experiment_record(...) auto-fills run_id/created_at/git_sha
- list_experiments CLI: --registry <path>
- discipline scaffolding only — NO backtest runs executed yet (RESEARCH_PROTOCOL.md §1)

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
PIT read layer (python/alpaca_quant/data/pit/ is still a stub) to enforce
"features read only via the PIT layer, never raw" (ROADMAP Phase 2 output, DATA_QUALITY §4),
then Phase 3 — honest backtester + null-model battery (writes experiment registry entries).
Still no labels, no signals, no model training, no trading until the backtester sprint.
