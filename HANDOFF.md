# Alpaca Quant — Current Handoff

Latest clean state:
- Branch: main
- Latest commit: 9f165cb feat: add controlled fetch run listing
- Repo clean and synced with origin/main

Current pipeline:
config loader -> data declaration manifest -> Alpaca bars client -> Parquet writer -> DuckDB query -> mock dry run -> real controlled fetch -> API diagnostics -> run registry -> list-runs CLI

Real controlled fetch:
- AAPL/MSFT
- 2024-01-02 to 2024-01-08
- feed: iex
- rows_written: 10
- verification_passed: true
- registry artifact produced in local ignored data/runs/

Safety:
- .env ignored, contains Alpaca keys, never print/read secrets
- data/runs/ ignored, do not commit data artifacts
- no trading
- no backtesting
- no live execution
- no order submission

Next recommended sprint:
Sprint 3A — feature factory foundation using local Parquet only.
No model training yet. No backtesting yet. No trading.
