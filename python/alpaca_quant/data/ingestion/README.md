# Data ingestion

Vendor connectors that pull raw market data into the local data lake.

**Status: not implemented yet (Sprint 0).** No real downloader exists.

Every produced dataset must carry a validated `data_declaration` manifest recording its quality
tier, universe provenance, survivorship and point-in-time guarantees, feed, date range, and known
gaps. These declarations make data limitations explicit and gate how far research may be promoted.

## Parquet writer

Sprint 1D writes already-parsed `Bar` objects to local Parquet files only. It performs no real
Alpaca API calls, and DuckDB indexing remains outside this sprint.

## DuckDB query layer

Sprint 1E uses an in-memory DuckDB connection to query existing local Parquet files. It performs
no real API calls, creates no persistent database, and contains no trading logic.

## Point-in-time (PIT) read layer

Sprint 6A adds `alpaca_quant.data.pit` — the sanctioned read path for feature computation.
`load_pit_bars(bars_path, *, as_of, symbols=None, start=None)` reads local bars as known at the
`as_of` knowledge cutoff (inclusive) and guarantees zero lookahead via `assert_no_lookahead`.
Features read through this layer, never from raw Parquet directly (ARCHITECTURE.md P2 / §3.1).
No real API calls, no network, no trading.

## Mock ingestion dry run

Sprint 1F connects the Tier 0 manifest, Parquet writer, and DuckDB query layer using mocked bars
only. It performs no real Alpaca API calls and contains no trading logic.

## Running the mock ingestion dry run

Run `python scripts/run_mock_ingestion_dry_run.py --output data/runs/mock_001` from the repository
root. The command uses mocked bars only, makes no real Alpaca API call, and contains no trading
logic.

## Controlled real Alpaca historical fetch

Run from the repository root:

```bash
python scripts/run_controlled_historical_fetch.py --output data/runs/alpaca_controlled_001 --symbols AAPL,MSFT --start 2024-01-02 --end 2024-01-08 --feed iex
```

The command requires `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY`, defaults to a tiny AAPL/MSFT
daily range, and includes no trading, backtesting, or live execution.

Failed API calls include safe HTTP status and `X-Request-ID` diagnostics with secrets redacted.
SSL certificate failures also include a macOS `Install Certificates.command` hint.

## Controlled fetch run registry

Each successful controlled fetch appends one validated, metadata-only JSON object to a local
append-only JSONL registry. The default path is:

```
data/runs/fetch_registry.jsonl
```

A custom path can be passed with `--registry PATH`. Records contain provenance and artifact
paths only — **never** credentials, secrets, or trading logic. The `data/runs/` directory
is git-ignored and remains entirely local; the registry is never committed.

Each record captures: `run_id`, `created_at`, `symbols`, `start`, `end`, `feed`,
`rows_written`, `output_dir`, `parquet_path`, `manifest_path`, `data_declaration_id`,
`verification_passed`, `status`, and `known_gaps`. Secret values are actively rejected
before the record is written.

### Listing runs

To print a non-secret summary of all recorded runs:

```bash
python scripts/list_fetch_runs.py
# or with a custom registry path:
python scripts/list_fetch_runs.py --registry data/runs/fetch_registry.jsonl
```

The output shows one row per run: `run_id`, `created_at`, `symbols`, `date_range`, `feed`,
`rows_written`, `verification_passed`, and `status`. No secrets are printed.

## Future behavior (Sprint 1 — Alpaca historical daily bars)

- Download Alpaca **daily** bars from the **SIP historical** feed (free, queryable as
  long as the request end is ≥ 15 min old; 100% of market vs ~2% for IEX).
- **Daily horizon only.** Intraday/microstructure waits for a real-time SIP subscription
  (see [`docs/DATA_QUALITY.md`](../../../../docs/DATA_QUALITY.md)).
- Write **immutable** raw output to `data/raw/`, partitioned by symbol/date, **idempotent
  and re-runnable**.
- Emit a `data_declaration` manifest for every dataset (tier, survivorship/corporate-actions/
  PIT status, feed, date range, known gaps) per `DATA_QUALITY.md §2`.
- Alpaca corporate actions are **best-effort, not PIT-guaranteed**, and delisted symbols are
  never exposed → cannot claim `corporate_actions_status: clean` or `pit_status: guaranteed`
  from Alpaca alone; Tier 2 requires a third-party vendor.

Keys come from `.env` (never committed); see [`.env.example`](../../../../.env.example).
Paper/data URLs only — this layer reads market data, it never places orders.
