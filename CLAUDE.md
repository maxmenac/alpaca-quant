# CLAUDE.md — Alpaca Quant

## Project

Alpaca Quant is a solo systematic quant research platform using Alpaca, Python, Go, machine learning, and LLM-assisted research.

Core philosophy: Alpaca Quant recommends, Max approves.

This is not an AI that predicts markets directly. It is a disciplined quant research environment.

## Non-negotiable safety rules

- Paper mode by default.
- No live trading unless explicitly enabled and approved by Max.
- No autonomous capital action.
- Python never executes trades.
- Go is the only future execution and risk-gate layer.
- API keys must never be committed.
- .env.example only.
- Fail closed by default.
- allow_live_trading: false by default.
- require_human_approval: true by default.
- Never bypass the risk gate.
- Never trade expired signals.
- Never trade if broker reconciliation failed.
- Reduce-only, close, and flatten actions may be allowed for risk reduction.
- Increasing exposure requires approval.

## Architecture boundary

Python is for research:
- data collection
- data quality declarations
- feature engineering
- alpha research
- backtesting
- null-model tests
- experiment registry
- ML / ensemble
- signal generation

Go is for execution and risk:
- signal validation
- risk gate
- future order proposals
- portfolio state
- safety checks
- future Alpaca paper/live execution

Python outputs target-weight signals. Go validates them and may later transform them into paper order proposals. Python never sends broker orders.

## Source-of-truth docs

Read these before changing architecture:
- docs/ARCHITECTURE.md
- docs/ROADMAP.md
- docs/DATA_QUALITY.md
- docs/RESEARCH_PROTOCOL.md
- docs/SAFETY_POLICY.md
- docs/SIGNAL_CONTRACT.md
- docs/DECISIONS.md

SIGNAL_CONTRACT.md v1.1.0 is binding for Go signal structs and validation.

## Current status

Sprint 0 foundation is complete:
- repository foundation created
- docs pasted verbatim
- configs created
- Python package skeleton created
- Go module skeleton created
- fail-closed signal and safety validation added
- tests pass
- no live-trading code added

Initial commit:
chore: bootstrap alpaca quant foundation

## Development commands

From repo root:

source .venv/bin/activate
make lint
make test

Python:
python -m pytest python/tests
ruff check python

Go:
cd go
gofmt -w .
go test ./...
go vet ./...

## Current MVP roadmap

Next sprint:
Sprint 1 — Alpaca historical daily bars downloader.

Scope:
- daily bars only
- Alpaca historical SIP-compatible flow
- request end time must be at least 15 minutes old
- Parquet storage
- DuckDB indexing/querying
- data_declaration manifests
- no trading
- no websocket
- no Timescale/NATS/Redis
- no dashboard
- no live execution

## Coding style

- Keep MVP-first.
- Do not overbuild.
- Do not add infrastructure early.
- Add tests before trusting behavior.
- If a safety test fails, fix implementation, not the test.
- Do not weaken safety rules to make code easier.
- Do not add files outside the intended sprint scope unless explicitly asked.
- Prefer simple local files, Parquet, and DuckDB before services.

## Important project principle

The goal is not to build a hype trading bot. The goal is to build a disciplined research machine that prevents self-deception:
- no lookahead
- no survivorship lies
- no fake backtest edge
- no costs ignored
- no live capital before paper proof
