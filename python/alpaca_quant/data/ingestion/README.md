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
