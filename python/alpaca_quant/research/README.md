# Research

Notebook-friendly local research datasets. Loads and aligns **local** bars + computed
feature artifacts into a single Polars DataFrame ready for exploration.

**Local Parquet only. No Alpaca API calls. No `.env` reads. No network. No trading.
No backtesting. No model training. No signal / label / target generation.**

## Loading a dataset

```python
from alpaca_quant.research import load_research_dataset, summarize_research_dataset

df = load_research_dataset(
    bars_path="data/runs/alpaca_controlled_002/historical_bars.parquet",
    features_path="data/runs/alpaca_controlled_002/features_AAPL.parquet",
    symbol="AAPL",                 # optional
    start="2024-01-02",            # optional, inclusive ISO date
    end="2024-01-08",              # optional, inclusive ISO date
)

summary = summarize_research_dataset(df)
print(summary)
```

The returned DataFrame is an **inner join** of bars and features on `(symbol, timestamp)`.
Only the join keys, `feature_set_id`, and the known Sprint 3A feature columns are pulled from
the features frame, so OHLCV columns are never duplicated.

## Inspect from the CLI

```bash
python scripts/inspect_research_dataset.py \
    --bars data/runs/alpaca_controlled_002/historical_bars.parquet \
    --features data/runs/alpaca_controlled_002/features_AAPL.parquet \
    --symbol AAPL
```

Prints rows, symbols, date range, feature column count, and per-feature null counts.
No secrets are printed.

## Validation guarantees

`load_research_dataset` rejects:
- a missing bars or features file
- an empty bars or features dataset
- missing required columns (bars need full OHLCV+ schema; features need
  `symbol`, `timestamp`, `feature_set_id`)
- duplicate `(symbol, timestamp)` rows in either input
- a symbol filter that matches no rows
- bars and features with no overlapping symbols
- an empty result after the join
- any trading/label concept column (`target`, `label`, `signal`, `order`, `weight`, …)

## What this layer does NOT do

- No prediction, signal, alpha, label, or target columns
- No model training
- No backtesting
- No order / trade / position concepts
- No Alpaca API calls, no `.env` reads, no network

## data/runs/ is local only

`data/runs/` is git-ignored. Bars, feature Parquet files, and manifests are never committed.
