# Feature Factory

Transforms raw Parquet bars into a tidy feature DataFrame. No Alpaca API calls. No .env reads.
No network. No trading. No backtesting. No model training.

## Computing features

Run from the repository root (activate `.venv` first):

```bash
python scripts/compute_features.py --run alpaca_controlled_002 --symbol AAPL
```

Outputs written locally to `data/runs/<run>/` — never committed:
- `features_AAPL.parquet` — full feature DataFrame
- `features_AAPL_manifest.yaml` — audit manifest

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

All features are computed per symbol, sorted by timestamp, using `.over("symbol")` in Polars.
Rolling windows use `min_samples=window` so early rows emit `null` rather than partial values.
The test suite (`test_features_no_lookahead.py`) proves that mutating future rows does not
change past feature values.

## data/runs/ is local only

`data/runs/` is git-ignored. Feature Parquet files and manifests are never committed.
