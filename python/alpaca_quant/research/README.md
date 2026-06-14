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
    symbol="AAPL",                 # optional: str or list[str]
    start="2024-01-02",            # optional, inclusive ISO date
    end="2024-01-08",              # optional, inclusive ISO date
    as_of="2024-01-05",            # optional, inclusive upper bound (lookahead guard)
)

summary = summarize_research_dataset(df)
print(summary)
```

The returned DataFrame is an **inner join** of bars and features on `(symbol, timestamp)`.
Only the join keys, `feature_set_id`, and the known Sprint 3A feature columns are pulled from
the features frame, so OHLCV columns are never duplicated. The result is always sorted by
`(symbol, timestamp)` for deterministic ordering.

### Multi-symbol loading (Sprint 4B)

`symbol` accepts a list, and `features_path` accepts one path or a list of per-symbol files:

```python
df = load_research_dataset(
    bars_path="data/runs/run/historical_bars.parquet",
    features_path=[
        "data/runs/run/features_AAPL.parquet",
        "data/runs/run/features_MSFT.parquet",
    ],
    symbol=["AAPL", "MSFT"],
)
```

All feature files must expose the same feature columns; mismatches are rejected.

### `as_of` lookahead guard (Sprint 4B)

`as_of` is an **inclusive upper bound** on the date — no rows after it are ever returned. It
composes with `end` (both bounds are applied), so research can be reproduced "as it would have
looked" on a given day without future leakage.

## Research dataset manifest (Sprint 4B)

`build_research_dataset_manifest(df, bars_path, features_path, as_of=..., known_gaps=...)`
returns a `ResearchDatasetManifest` with: `dataset_id`, `created_at` (UTC), `symbols`,
`start`, `end`, `as_of`, `bars_path`, `features_paths`, `row_count`, `feature_count`,
`known_gaps`, and the safety flags `no_trading`, `no_backtesting`, `no_model_training`
(all `True`). `dataset_id` is deterministic (`rds-<sha256[:8]>` of the inputs).

`scripts/inspect_research_dataset.py --write-manifest` writes the manifest next to the bars
file as `research_dataset_<dataset_id>_manifest.yaml` (local, git-ignored).

## Inspect from the CLI

```bash
python scripts/inspect_research_dataset.py \
    --bars data/runs/alpaca_controlled_002/historical_bars.parquet \
    --features data/runs/alpaca_controlled_002/features_AAPL.parquet \
    --symbol AAPL
```

`--features` and `--symbol` accept multiple values; `--as-of` and `--write-manifest` are
optional. Prints rows, symbols, date range, feature column count, and per-feature null counts.
No secrets are printed.

## List research datasets from the CLI

```bash
python scripts/list_research_datasets.py --run alpaca_controlled_002
# or with an explicit directory:
python scripts/list_research_datasets.py --dir /abs/path/to/dir
```

Prints `dataset_id`, `symbols`, date range, `as_of` (if any), `row_count`, `feature_count`,
and `created_at` for each `research_dataset_*_manifest.yaml`. Fails clearly on a missing
directory, no manifests, or a malformed/incomplete manifest. No secrets are printed.

## Validation guarantees

`load_research_dataset` rejects:
- a missing bars or features file
- an empty bars or features dataset
- missing required columns (bars need full OHLCV+ schema; features need
  `symbol`, `timestamp`, `feature_set_id`)
- duplicate `(symbol, timestamp)` rows in either input (including duplicates created by
  combining multiple feature files)
- feature files with mismatched feature columns
- a symbol filter that matches no rows in bars or in features
- bars and features with no overlapping symbols
- an invalid date range (`end` before `start`, or `as_of` before `start`)
- a malformed `as_of`/`start`/`end` date
- an empty result after the join
- any trading/label concept column (`target`, `label`, `signal`, `order`, `weight`, …)

## Experiment registry (Sprint 5A)

An append-only JSONL registry records research experiment runs — discipline scaffolding
(RESEARCH_PROTOCOL.md §1) that future backtests will write to. **This sprint records metadata
only: no backtest runs, `metrics` ships empty, and the safety flags are enforced `True`.**

```python
from alpaca_quant.research import (
    new_experiment_record,
    append_experiment_record,
    read_experiment_records,
)

record = new_experiment_record(            # auto-fills run_id, created_at (UTC), git_sha
    dataset_id="rds-85eb9a7b",
    dataset_manifest_path="data/runs/run/research_dataset_rds-85eb9a7b_manifest.yaml",
    feature_set_id="feat-AAPL-27d52941",
    config_hash="sha256:...",
    seed=42,
    decided_by="max",
)
append_experiment_record("data/runs/experiment_registry.jsonl", record)
```

Record fields: `run_id`, `created_at`, `git_sha`, `dataset_id`, `dataset_manifest_path`,
`feature_set_id`, `feature_version`, `config_hash`, `seed`, `as_of`, `report_path`,
`weight_source`, `metrics` (numeric only), `decision` (default `keep_researching`),
`decided_by`, `notes`, `kind="experiment"`. Capital-safety flags `no_trading`,
`no_model_training`, `no_live_execution`, `no_order_submission` are **enforced `True`**
(fail-closed). `no_backtesting` is informational (default `True`; real backtest runs set it
`False`) — backtesting is a legitimate research activity from Phase 3 on.

Guarantees:
- `run_id` is **unique and immutable** — re-appending an existing `run_id` is rejected and
  nothing is written.
- `created_at` must be timezone-aware (coerced to UTC).
- `git_sha` is captured via `subprocess` (`git rev-parse HEAD`) only — local, read-only, never
  networks, returns `None` if unavailable.
- secrets are rejected before writing; malformed/duplicate JSONL lines are rejected on read.

### List experiments from the CLI

```bash
python scripts/list_experiments.py
# or a custom path:
python scripts/list_experiments.py --registry data/runs/experiment_registry.jsonl
```

Prints `run_id`, `created_at`, `git_sha`, `dataset_id`, `feature_set_id`, `seed`, `decision`,
`decided_by`. Fails clearly on a missing/malformed registry. No secrets are printed.

## Backtest experiments (Phase 3C)

`run_backtest_experiment(...)` wires the existing blocks into one immutable, traceable run:
PIT read (`load_pit_bars`) → backtest engine (`run_backtest`) → null-model battery
(`run_null_battery`) → JSON + Markdown report → experiment registry entry.

```python
from alpaca_quant.research import run_backtest_experiment

result = run_backtest_experiment(
    bars_path="data/runs/run/historical_bars.parquet",
    weights_path="data/runs/run/weights_AAPL.parquet",  # caller-provided; NOT generated here
    as_of="2024-01-31",                                  # required, PIT cutoff (no lookahead)
    weight_source="caller: my_weights_v1",
    seed=12345,
)
result.record        # ExperimentRecord with numeric metrics, config_hash, report_path
result.report_paths  # JSON (canonical) + Markdown (human)
```

- **It creates no strategy.** Weights come only from a local Parquet (`symbol, timestamp,
  weight`); the runner never computes a signal/alpha/optimizer/model.
- **PIT enforced**: bars are read via `load_pit_bars(as_of=...)` and `run_backtest(as_of=...)`
  re-asserts no-lookahead.
- **`metrics` stays strictly numeric**: backtest + null-battery numbers; boolean diagnostics
  (e.g. `nb.future_leak_detected`) are encoded `1.0`/`0.0`. Full structured diagnostics live in
  the JSON report.
- **`config_hash`** is a deterministic `sha256:` over the result-determining config.
- CLI: `python scripts/run_experiment.py --bars ... --weights ... --as-of ... --weight-source ...`

## What this layer does NOT do

- No prediction, signal, alpha, label, or target generation (weights are caller-provided)
- No optimizer, no strategy discovery, no model training
- No order / trade / position / live-execution concepts
- No Alpaca API calls, no `.env` file reads, no network

## data/runs/ is local only

`data/runs/` is git-ignored. Bars, feature Parquet files, manifests, and the experiment
registry are never committed.
