# Feature Factory

Transforms point-in-time bars into a tidy feature DataFrame. No Alpaca API calls. No .env reads.
No network. No trading. No backtesting. No model training.

## Point-in-time first (Sprint 6A)

Features are built **through the PIT read layer** ([`data/pit/`](../data/pit/)), never from raw
Parquet directly (ARCHITECTURE.md P2 / §3.1). The official entry point is:

```python
from alpaca_quant.features import build_pit_feature_set

df = build_pit_feature_set(
    "data/runs/alpaca_controlled_002/historical_bars.parquet",
    "AAPL",
    as_of="2024-01-05",   # required: inclusive knowledge cutoff, no lookahead past this
)
```

`build_feature_set(parquet_path, symbol)` still exists but is a **legacy raw-read path** kept
for backward compatibility only — no new CLI or production path should call it. Prefer
`build_pit_feature_set(..., as_of=...)`.

## Computing features

Run from the repository root (activate `.venv` first). `--as-of` is **required**:

```bash
python scripts/compute_features.py --run alpaca_controlled_002 --symbol AAPL --as-of 2024-01-05
# or with an explicit run directory:
python scripts/compute_features.py --run-dir /abs/path/to/run --symbol AAPL --as-of 2024-01-05
```

Outputs written locally to `data/runs/<run>/` — never committed:
- `features_AAPL.parquet` — full feature DataFrame
- `features_AAPL_manifest.yaml` — audit manifest (records the `as_of` cutoff)

## Listing feature sets

```bash
python scripts/list_feature_sets.py --run alpaca_controlled_002
# or with an explicit path:
python scripts/list_feature_sets.py --run-dir /abs/path/to/run
```

Prints `feature_set_id`, `symbol`, `row_count`, `date_range`, `feature_count`, `no_trading`.
Never prints secrets.

## Features produced (Sprint 3A)

| Column | Description | Lookback |
|---|---|---|
| `daily_return` | `close.pct_change()` per symbol | 1 |
| `log_return` | `log(close / close_prev)` per symbol | 1 |
| `rolling_vol_20d` | Annualized realized vol of log returns | 20 |
| `sma_5d` | Simple moving average of close | 5 |
| `sma_20d` | Simple moving average of close | 20 |
| `ema_5d` | Exponential moving average of close | 5 |
| `ema_20d` | Exponential moving average of close | 20 |
| `rolling_vol_volume_20d` | Rolling mean of volume | 20 |

## No-lookahead guarantee

Two layers of protection:
1. **PIT read** — `build_pit_feature_set` loads bars via `load_pit_bars(..., as_of=...)`, which
   drops every row dated after the cutoff and runs `assert_no_lookahead` before returning. No
   future bar can enter the computation. (`assert_no_lookahead` is reusable by the future
   backtester.)
2. **Within-window** — all features are computed per symbol, sorted by timestamp, using
   `.over("symbol")` in Polars; rolling windows use `min_samples=window` so early rows emit
   `null` rather than partial values.

`test_features_no_lookahead.py` proves that mutating future rows does not change past feature
values; `test_pit_features.py` proves PIT features equal legacy features computed on data
manually truncated at the same `as_of`.

## data/runs/ is local only

`data/runs/` is git-ignored. Feature Parquet files and manifests are never committed.
