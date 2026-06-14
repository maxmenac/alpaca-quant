# Alpaca Quant

A solo systematic quant research platform built on Alpaca, Python, Go, ML, and
LLM-assisted research.

## Philosophy

**Alpaca Quant recommends, Max approves.**

The system may recommend trades, produce target weights, run backtests, generate
reports, and create paper order proposals. It must **never** execute real capital
without (1) automatic risk controls, (2) safety checks, and (3) explicit human
approval. This is **not** an AI that predicts markets directly — it is a disciplined
research environment.

The full design principles live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (P1–P8).

## Paper-first rule

- **Paper mode by default.** There is **no live trading** in this MVP — no live order
  execution, no autonomous capital action.
- Fail-closed defaults: `allow_live_trading: false`, `require_human_approval: true`,
  `kill_switch_armed: true` (see [`configs/app.yaml`](configs/app.yaml) and
  [`docs/SAFETY_POLICY.md`](docs/SAFETY_POLICY.md)).
- Increasing exposure requires human approval; reducing risk
  (`reduce_only` / `close_only` / `rebalance_to_zero`) is always permitted.

## Python-research / Go-execution split

- **Python** (`python/alpaca_quant/`) is the only research/ML/backtest environment and
  **never touches capital**. It produces target-weight **signals**.
- **Go** (`go/`) is the only (future) execution / risk-gate layer. It **validates and
  risk-gates** signals and proposes future orders.
- The boundary is a versioned, file-based **signal contract**
  ([`docs/SIGNAL_CONTRACT.md`](docs/SIGNAL_CONTRACT.md), schema v1.1.0) — never a direct
  call. See [ADR-001 / ADR-002](docs/DECISIONS.md).

## Current MVP scope (Sprint 0)

- Repository skeleton, docs, configs, fail-closed defaults.
- Python: minimal importable package with an abstract `Alpha` interface and a registry.
- Go: signal structs + fail-closed validation + boot-time safety config validation.
  **Types and validation only — no broker client, no order execution.**
- Local data lake first (Parquet/DuckDB). No NATS/Timescale/websocket/dashboard yet.

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the MVP-first Phase 0 → 10 ordering.

## What this project is NOT

- **Not** an AI that predicts markets or trades autonomously.
- **Not** a live-trading system (no live execution exists in this sprint).
- **Not** a place where Python can reach the broker — execution is Go-only, behind a risk gate.
- **Not** a "fantasy repo" of unused infra (no message bus, no real-time DB, no dashboard yet).

## Running the initial checks

```sh
make test        # runs both Python and Go test suites
make test-python # python -m pytest python/tests
make test-go     # cd go && gofmt -w . && go test ./...
make lint        # ruff check python && cd go && go vet ./...
make tree        # print the repository tree
```

Copy [`.env.example`](.env.example) to `.env` and fill in your Alpaca **paper** keys
(`.env` is git-ignored and never committed).

> System design, not investment advice. Capital and risk decisions remain yours.
