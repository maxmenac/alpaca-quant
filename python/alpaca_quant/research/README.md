# Research

Notebook-friendly local research datasets and audited forward-return labels. The dataset
loader aligns **local** bars + computed feature artifacts into a label-free Polars DataFrame.
The separate Phase 4A target module computes future outcomes only after that boundary.

**Local Parquet only. No Alpaca API calls. No `.env` reads. No network. No trading.
No model training. No alpha, strategy, signal, weight, or order generation.**

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

## Forward-return target labels (Phase 4A)

`build_forward_return_labels(...)` creates one audited label column from an already-loaded
in-memory frame. It does not mutate the research dataset loader or feature factory.

```python
from alpaca_quant.research import (
    build_forward_return_labels,
    build_target_manifest,
    summarize_target_labels,
)

labelled = build_forward_return_labels(df, horizon=5, price_col="close")
summary = summarize_target_labels(
    labelled,
    label_col="label_forward_return_5d",
)
manifest = build_target_manifest(
    labelled,
    horizon=5,
    source_dataset_id="rds-85eb9a7b",
)
```

Contract:
- labels are simple forward returns: `price[t+h] / price[t] - 1`
- rows are stably sorted by `(symbol, timestamp)` before calculation
- future shifts are grouped by symbol, so outcomes never bleed across instruments
- the final `horizon` rows per symbol remain null; nulls are never filled with `0`
- `target_null_reason` distinguishes unavailable future rows and null source/future prices
- invalid horizons, missing columns, duplicate keys, non-positive/non-finite prices, existing
  labels, and strategy/trading columns are rejected
- `fingerprint_target_labels(...)` hashes the deterministic target definition and labelled rows
- `build_target_manifest(...)` records coverage, null breakdown, provenance, fingerprint, and
  explicit labels-only safety flags

These labels contain future information by definition. They must never enter feature generation,
signal generation, or live code. Phase 4A provides no persistence command and writes no CSV,
Parquet, JSON manifest, or `data/runs` artifact.

## Target QA reports (Phase 4B)

Phase 4B audits Phase 4A labels before any alpha, signal, strategy, model, or weight work:

```python
from alpaca_quant.research import (
    TargetReportConfig,
    build_target_qa_report,
    render_target_qa_markdown,
)

report = build_target_qa_report(
    labelled,
    manifest=manifest,
    config=TargetReportConfig(
        max_null_pct=20.0,
        extreme_return_threshold=1.0,
    ),
)
markdown = render_target_qa_markdown(report)
```

The JSON-compatible report includes:
- schema version and injectable UTC generation time
- target-set id, source dataset, fingerprint, horizons, and target columns
- per-horizon counts, null percentage, mean/std/min/max, and p01/p05/p50/p95/p99
- bounded per-symbol distributions and optional deterministic monthly summaries
- manifest/data null-reason breakdowns and consistency checks
- `OK` or `SUSPECT` verdict plus structured warnings

Fail-closed rules:
- missing declared target columns raise `TargetReportError`
- unsupported manifest schema versions raise clearly
- manifest/config target disagreements raise; no horizon is silently inferred over a declaration
- nulls remain null and non-finite values remain visible as warnings; neither becomes zero

Warnings cover missing manifests, excessive nulls, extreme returns, non-finite values,
manifest/data mismatches, and missing null-reason ledgers. Every report also states that adjusted
close handling, point-in-time universe membership, and survivorship bias belong upstream in the
data layer.

Local CLI:

```bash
python scripts/report_targets.py \
    --labels /local/path/targets.parquet \
    --manifest /local/path/target_manifest.json \
    --output-json /local/path/target_qa.json \
    --output-md /local/path/target_qa.md
```

Parquet and CSV labels are supported; manifest input may be JSON or YAML. Outputs are written only
to the explicit local paths. No demo outputs or `data/runs` artifacts are part of the repository.

Boundary: Phase 4B is label QA/reporting only. It is not alpha, signal, strategy, model, backtest
expansion, optimizer, portfolio construction, trading, order logic, or execution.

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

## ML dataset assembly + data contract (Phase 4C)

Phase 4C assembles a **point-in-time-safe `(X, y)` dataset** from existing features and Phase 4A
labels behind a strict adjusted-close / PIT / `available_at` data contract. Its only question is
*"can we assemble X and y without silently leaking future information?"* — never *"can we predict
returns?"*. **It trains no model, runs no cross-validation, and generates no alpha, signal,
strategy, weight, portfolio, optimizer, backtest, or order.** Split definitions are index sets
prepared for a future phase; nothing is trained here.

```python
from alpaca_quant.research import (
    FeatureSpec, DatasetConfig, assemble_ml_dataset,
    make_temporal_split, assert_split_disjoint_and_purged,
    render_dataset_manifest_markdown,
)

result = assemble_ml_dataset(
    labels=labelled_panel,                 # Phase 4A: one row per (symbol, timestamp) + label_*
    features=feature_panel,                # mechanical, pass-through features (never recomputed)
    feature_specs=[FeatureSpec("dollar_volume")],
    label_columns=["label_forward_return_1d"],
    target_manifest=target_manifest,       # Phase 4A manifest -> lineage fingerprint
    universe=pit_universe,                 # optional: symbol/permanent_id, valid_from, valid_to
    identity=symbol_identity,              # optional: permanent_id, ticker, valid_from, valid_to
    reference=fundamentals,                # optional: needs available_at (as-of join)
    reference_value_columns=["eps"],
    config=DatasetConfig(),                # PIT universe enforced unless synthetic_no_universe
)
result.frame      # stably sorted (id, timestamp); features, labels, + eligibility metadata
result.manifest   # lineage, null matrix, universe coverage, as-of summary, fingerprint, verdict
```

Contract enforced (fail closed / mark `SUSPECT`, never silently coerce):

- **Adjusted-close caveat.** Return labels are back-adjustment invariant when computed
  consistently. Price-level features using **back-adjusted** prices are *rejected*; **unknown**
  adjustment provenance is marked `SUSPECT`; only `pit_safe` (as-reported) price levels pass.
- **PIT universe / anti-survivorship.** A row is eligible only if the symbol is in the universe
  at that timestamp (`valid_from <= t <= valid_to`, open-ended `valid_to` allowed). Missing
  universe marks `SUSPECT` unless `synthetic_no_universe` is explicit.
- **As-of joins.** Reference/fundamental values join on real availability time
  (`available_at <= timestamp`, backward per id). Late-published values never appear early;
  restatements preserve the value known as of `t`. Missing `available_at` fails closed.
- **Symbol identity.** `permanent_id` is preferred for lineage; tickers are mapped only within
  date bounds (never merged blindly). No identity table → fall back to ticker + `SUSPECT`.
- **Feature cutoff vs label entry.** `feature_cutoff_time` is the prior bar (lag ≥ 1), strictly
  before the row timestamp; feature windows never overlap the forward label window.

Rows are **never silently dropped, filled, imputed, or globally scaled** — each carries
`eligible` / `eligibility_reason`, and the manifest records null counts and exclusion reasons.

Purged + embargoed temporal split **definitions** (`make_temporal_split`) produce
train/validation/test index sets: training rows whose label window overlaps evaluation are
purged, and an embargo of at least `max_horizon` bars is removed before each evaluation block.
`assert_split_disjoint_and_purged` fails closed on any violation. **No CV is run.**

CLI: `python scripts/assemble_dataset.py --labels ... --features ... --spec ... --output-json ...
--output-md ...` writes only the manifest (JSON/Markdown) and, optionally, the dataset to a
caller-specified path — never into `data/runs/`.

## Feature registry + dataset inspection (Phase 4D)

Phase 4D adds a **local feature registry** (neutral/mechanical feature *metadata* only) and a
**dataset inspection report** that audits a 4C dataset before any future ML work. **It computes
no feature, trains no model, runs no CV, and produces no alpha, signal, strategy, weight,
portfolio, optimizer, backtest, or order.** The registry exists to stop unsafe features from
silently entering a dataset; the inspection report exists to audit 4C dataset quality. The only
"features" here are synthetic, test-only, declared pass-through columns — never RSI/MACD/momentum
or any alpha-ish computation.

```python
from alpaca_quant.research import (
    FeatureDefinition, build_registry, validate_definition, validate_feature_set,
    compute_feature_set_id, build_dataset_inspection_report,
    render_dataset_inspection_markdown,
)

definition = FeatureDefinition(
    name="bar_volume_raw", family="mechanical_volume",
    description="Raw traded volume, as reported.", dtype="float64",
    source="caller_provided", pit_safe=True,            # never assumed safe from the name alone
)
registry = build_registry([definition])
validate_definition(definition).verdict                 # OK / SUSPECT / REJECTED + all reasons
compute_feature_set_id([definition])                    # deterministic; order/row invariant
report = build_dataset_inspection_report(
    dataset_frame, manifest=dataset_manifest, registry=registry,
    requested_features=["bar_volume_raw"], splits=[temporal_split],
)
render_dataset_inspection_markdown(report)              # includes the verbatim boundary note
```

Registry decision rules (conservative, ordered — ambiguity is never coerced into safety):

1. `pit_safe = False` unless explicitly declared.
2. `uses_future_data = True` → **REJECTED** (look-ahead).
3. `is_alpha_like = True` (or an alpha-like name, or a phase not in `allowed_in_phase`) →
   **REJECTED** for Phase 4D.
4. unknown `adjustment_safety` → **SUSPECT** (or **REJECTED** per config).
5. price-level feature (`requires_adjusted_price = True`) without an explicit PIT-safe adjustment
   declaration → **SUSPECT/REJECTED**.
6. a feature is **never** assumed safe from its name alone.

`feature_set_id` is a deterministic `fs-…` hash over name-sorted, canonically-serialized
definitions (including each `version`): invariant to feature/row order, sensitive to value or
version changes, with no environment dependency.

The inspection report's verdict follows strict precedence **`REJECTED > SUSPECT > OK`** and lists
**all** reasons (future-looking/alpha-like/undeclared-price-level/invalid-split → REJECTED;
missing metadata, ambiguous adjustment, null ratio over threshold, missing PIT universe / symbol
identity / `available_at`, undeclared dataset column, feature missing from dataset → SUSPECT). It
includes lineage (4A + dataset fingerprint + `feature_set_id`), coverage/safety tables, null
matrix, universe/as-of/identity/split summaries, warnings, and the verbatim note: *"This report
inspects dataset and feature metadata only. It is not an alpha, signal, strategy, model, trading
recommendation, or execution component."*

CLI: `python scripts/inspect_dataset.py --dataset ... --manifest ... --feature-registry ...
--output-json ... --output-md ...` writes only the report (JSON/Markdown) to caller paths — never
into `data/runs/`.

### 4D-1 hardening — provenance blind-spot flags (detect, never mutate)

The inspection layer surfaces three provenance conditions found by the 4E-0 real-data run. Each
is **detection/classification only** — no value is synthesized, inferred, normalized, or filled.

- **`missing_available_at_semantics` (standalone, SUSPECT).** When the inspected source carries no
  `available_at` column and no reference availability semantics at all, as-of provenance cannot be
  proven, so the report flags it even though no reference table was passed. The absent
  `available_at` is never created or inferred.
- **`ambiguous_adjustment_declaration` (SUSPECT).** `assemble_ml_dataset(..., data_declaration=…)`
  carries the **declared** `corporate_actions_status` / `adjustment_status` into the manifest
  verbatim (`declared_corporate_actions_status`, `declared_adjustment_status`). When that declared
  status is absent or not unambiguously clean (e.g. `partial` / `best_effort`), both manifest and
  report flag it — **independent of whether any price-level feature is present**. No adjustment
  posture is inferred, computed, or re-derived from the bars.
- **`feature_timezone_mismatch` (SUSPECT).** Assembly compares the feature-source timezone against
  the bar timestamp timezone. When they differ, the features are **not** joined (a cross-timezone
  join is refused) and the condition is flagged in `timezone_alignment` + warnings — **no
  `tz_convert` / `tz_localize` / `replace_time_zone` is ever called.** Re-stamping feature
  timezones belongs to a future ingestion/feature sprint. A feature whose non-null coverage falls
  below the null-ratio threshold is surfaced by the existing coverage/null reporting (never
  dropped or filled).

These three additions are **SUSPECT-class** (missing provenance, not active leakage); precedence
stays `REJECTED > SUSPECT > OK`, and the warning set is emitted in a stable, sorted order so the
report is reproducible across row/column orderings. They **flag, never mutate**: no `available_at`,
adjustment posture, or timezone is synthesized, inferred, or converted — those fixes live in a
future scoped ingestion sprint.

## Local synthetic provenance fixtures (Phase 4F-0)

`synthetic_provenance.py` constructs small, fully-local, deterministic provenance fixtures and
feeds them to the **existing** 4C/4D/4D-1 chain — it modifies no auditor logic (build data, not
auditor). It proves both halves of the contract:

- **Clean path → honest OK.** As-reported bars (with per-row `available_at >= timestamp` and a
  `permanent_id`), a PIT universe with `valid_from`/`valid_to` (including a delisted symbol), a
  date-bounded identity carrying a mid-window ticker change under one `permanent_id`, explicit
  corporate-action records (split + dividend) that also feed the as-of reference join, and a
  tz-aligned neutral feature (`bar_volume_raw`). Strict-mode assembly yields a non-empty eligible
  band and both the 4C manifest and 4D inspection return **OK** with all four 4D-1 warnings absent.
- **Dirty path → still refused for one named reason each.** delisted → `not_in_universe` after
  `valid_to`; withheld identity → `missing_symbol_identity`; no reference/available_at →
  `missing_available_at_semantics`; `corporate_actions_status=partial` →
  `ambiguous_adjustment_declaration`; foreign feature timezone → `feature_timezone_mismatch`;
  too-short window → 0-eligible / tail-null.

Adjustment safety is **auditable from records** (split/dividend rows with effective dates), never
asserted by a bare flag. An honest OK on synthetic data validates the *contract path* only — it
does not validate real prices or real provenance; real-data ingestion is a future scoped sprint.
The `convert_time_zone` call in the tz-mismatch fixture is **fixture authoring**, not an auditor
path — the inspection layer still converts nothing.

## What this layer does NOT do

- No prediction, signal, alpha, strategy, weight, or order generation
- No model training, no `.fit()`, no fit/transform, no cross-validation execution, no global
  scaling — Phase 4C assembles datasets and split *definitions* only, and Phase 4D inspects
  feature/dataset *metadata* only (no feature is computed except synthetic test-only pass-through)
- The only target generation is the separate Phase 4A forward-return label module described
  above; labels are future outcomes, never model inputs or features
- No optimizer, no strategy discovery, no model training
- No order / trade / position / live-execution concepts
- No Alpaca API calls, no `.env` file reads, no network

## data/runs/ is local only

`data/runs/` is git-ignored. Bars, feature Parquet files, manifests, and the experiment
registry are never committed.
