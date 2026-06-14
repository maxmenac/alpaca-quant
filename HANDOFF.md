# Alpaca Quant — Current Handoff

Latest clean state:
- Branch: main
- Latest commit: 8dc8284 feat: add feature factory foundation
- Repo clean and synced with origin/main

Current pipeline:
config loader -> data declaration manifest -> Alpaca bars client -> Parquet writer -> DuckDB query -> mock dry run -> real controlled fetch -> API diagnostics -> run registry -> list-runs CLI -> feature factory -> list-feature-sets CLI

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
Sprint 4A — research skeleton: notebook-friendly entry point that loads bars + features
for a symbol/date-range, foundation for first signal or alpha exploration.
No trading, no backtesting, no model training yet.
