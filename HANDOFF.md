# Alpaca Quant — Current Handoff

Latest clean checkpoint before Phase 4A integration:
- Branch: main
- Latest commit: 790afe4 feat: polish experiment report readability
- Repo clean and synced with origin/main

Current pipeline:
config loader -> data declaration manifest -> Alpaca bars client -> Parquet writer -> DuckDB query -> mock dry run -> real controlled fetch -> API diagnostics -> run registry -> list-runs CLI -> PIT read layer -> feature factory (PIT-first) -> list-feature-sets CLI -> research dataset loader -> target/label foundation -> list-research-datasets CLI -> experiment registry -> list-experiments CLI -> backtest engine core (PIT, costs, metrics) -> null-model battery -> backtest experiment runner (registry + report + CLI) -> ML dataset assembly + data contract (PIT-safe X/y, no training) -> feature registry + dataset inspection (metadata audit, no computation)

Real controlled fetch (alpaca_controlled_002):
- AAPL/MSFT
- 2024-01-02 to 2024-01-08
- feed: iex
- rows_written: 10
- verification_passed: true
- registry artifact produced in local ignored data/runs/

Feature factory (Sprint 3A + 3B):
- compute_features CLI: python scripts/compute_features.py --run <run> --symbol <SYM>
- list_feature_sets CLI: python scripts/list_feature_sets.py --run <run>
- features written to data/runs/<run>/features_<SYM>.parquet (local, not committed)
- manifest written to data/runs/<run>/features_<SYM>_manifest.yaml (local, not committed)
- feature_set_id is deterministic: sha256(resolved_path:SYMBOL)[:8]
- no-lookahead validated by test suite

Backtest engine core (Phase 3A):
- alpaca_quant.backtest: run_backtest, BacktestResult, BacktestError, forward_returns,
  CostModel/load_cost_model, BacktestMetrics/compute_metrics/equity_curve
- outcomes.forward_returns = EVALUATION OUTCOMES only (never features, never alpha labels);
  last `horizon` bars per symbol are null and excluded from PnL
- run_backtest(df, *, weight_col="weight", horizon=1, cost_model=None, as_of=None):
  - scores CALLER-PROVIDED weights; engine never generates alpha/signals/predictions
  - causal alignment: pnl_t = weight_t * forward_return(t->t+horizon)
  - costs charged on turnover |w_t - w_{t-1}| per symbol (first realizable bar = entry from flat)
  - multi-symbol portfolio = sum across symbols per timestamp
  - if as_of given, assert_no_lookahead (PIT) rejects any row after the cutoff
  - output frame columns: timestamp, gross_return, cost, net_return, equity
  - NEVER creates/requires columns: signal, alpha, prediction, target, order, trade
- metrics: Sharpe/Sortino (252 annualization; 0.0 when variance/downside variance is zero),
  max_drawdown, annual_turnover, total_return, cagr, n_periods
- costs from configs/costs.yaml; stress none/2x/5x defined (exercised by null battery in 3B)
- PURE LIBRARY: no experiment-registry wiring, no CLI in 3A

Null-model battery (Phase 3B):
- alpaca_quant.backtest.null_models: run_null_battery, NullBatteryReport, NullModelResult,
  random_weights, shuffled_weights, shifted_weights, future_leak_weights, NullBatteryError
- DIAGNOSTIC, not a strategy: transforms caller weights (or reruns under cost stress) through
  run_backtest; makes NO alpha claim; gates nothing (human reads report, decides)
- variants: random (seeded uniform), shuffled (seeded permutation), shifted (+1 per symbol),
  future_leak (weight = sign(forward_return) -> must EXPLODE), cost_stress_2x / cost_stress_5x
- deterministic seeds (random<-seed, shuffled<-seed+1; leak/baseline/cost-stress seed-free)
- advisory diagnostics on report: future_leak_detected, random_near_zero, shuffled_near_zero
- transforms fill null weights with 0.0 so the engine never rejects them
- PURE LIBRARY: no CLI, no registry wiring, no real alpha/optimizer/model training in 3B

PIT read layer (Sprint 6A):
- alpaca_quant.data.pit: load_pit_bars(bars_path, *, as_of, symbols=None, start=None),
  assert_no_lookahead(df, as_of), PITReadError
- as_of is required (keyword-only), inclusive knowledge cutoff; no row after as_of is returned
- reads local Parquet via the DuckDB query layer; no network, no Alpaca API
- assert_no_lookahead is the reusable hard gate for future backtester code
- feature factory: build_pit_feature_set(bars_path, symbol, *, as_of) is the OFFICIAL path;
  build_feature_set(...) kept as documented legacy raw path only (no new caller may use it)
- compute_features CLI now REQUIRES --as-of (also accepts --run-dir for explicit paths);
  routes through the PIT path; manifest records as_of
- feature_set_id for PIT path is sensitive to as_of (distinct cutoffs => distinct ids)

Research dataset layer (Sprint 4A + 4B):
- load_research_dataset(bars_path, features_path, symbol, start, end, as_of)
  - aligns local bars + features on (symbol, timestamp), inner join, Polars only
  - multi-symbol: symbol accepts list, features_path accepts list of per-symbol files
  - as_of is an inclusive upper-bound lookahead guard, composes with end
  - deterministic sort by (symbol, timestamp); forbidden trading/label columns rejected
- build_research_dataset_manifest(...) -> ResearchDatasetManifest
  - dataset_id deterministic (rds-<sha256[:8]>), created_at UTC, symbols, start/end/as_of,
    bars_path, features_paths, row_count, feature_count, known_gaps,
    no_trading/no_backtesting/no_model_training = true
- inspect_research_dataset CLI: --bars --features... --symbol... --start --end --as-of
  --write-manifest (writes research_dataset_<id>_manifest.yaml, local/ignored)
- list_research_datasets CLI: --run <run> | --dir <path>

Target / Label Foundation (Phase 4A):
- `alpaca_quant.research.targets` adds forward-return labels only:
  - `build_forward_return_labels(df, horizon, price_col, label_col)`
  - stable `(symbol, timestamp)` sort and per-symbol future shift
  - `label[t] = price[t+h] / price[t] - 1`
  - final `horizon` rows per symbol stay null; nulls are never filled with zero
  - `target_null_reason` records insufficient future rows and null source/future prices
- input validation rejects empty/malformed frames, invalid horizons, duplicate keys,
  non-positive/non-finite prices, existing labels, and strategy/trading columns
- `summarize_target_labels` provides coverage plus a null-reason breakdown
- `fingerprint_target_labels` is deterministic across input row ordering
- `build_target_manifest` records target id, fingerprint, provenance, coverage, null breakdown,
  and explicit labels-only safety flags
- no artifact writer: no target CSV/Parquet/JSON or `data/runs` output is created
- safety boundary: labels only; no alpha, strategy, model, optimizer, signal, weight, portfolio,
  trading, order, Alpaca API, network, or `.env` logic
- verification:
    make lint
    python -m pytest -q
    cd go && go test ./... && cd ..
- stop after Phase 4A integration; Phase 4B must be explicitly scoped

Target Quality Report (Phase 4B):
- `alpaca_quant.research.target_report` audits labelled frames plus Phase 4A metadata:
  - `build_target_qa_report(...)` returns a JSON-compatible schema-v1 report
  - `render_target_qa_markdown(...)` produces a compact `Target QA Report`
  - injectable timezone-aware clock makes `generated_at_utc` deterministic in tests
- target metadata: target-set id, fingerprint, source, horizons, and declared target columns
- per-horizon QA: total/valid/null/non-finite counts, null percentage, mean/std/min/max, and
  p01/p05/p50/p95/p99
- per-symbol counts and bounded distributions; optional deterministic monthly summaries
- structured warnings cover missing manifest, excessive nulls, extreme/non-finite returns,
  missing null ledger, detectable manifest/data mismatch, and upstream adjusted-close/PIT
  universe/survivorship responsibilities
- fail-closed:
  - missing declared target columns raise `TargetReportError`
  - unsupported manifest versions raise clearly
  - manifest/config target disagreement raises; no silent horizon inference
  - nulls and non-finite values are never converted to zero
- `scripts/report_targets.py` reads local Parquet/CSV labels plus JSON/YAML manifest and writes
  JSON/Markdown only to explicit output paths
- report boundary note: labels-only audit; not alpha, signal, strategy, model, recommendation,
  trading, or execution
- no backtest expansion, optimizer, portfolio construction, order logic, Alpaca API, network,
  `.env`, external/live data, or `data/runs` artifacts
- verification:
    make lint
    python -m pytest -q
    cd go && go test ./... && cd ..
    git diff --check
- stop after Phase 4B; do not start Phase 4C

Experiment registry (Sprint 5A):
- append-only JSONL at data/runs/experiment_registry.jsonl (local, git-ignored)
- ExperimentRecord (pydantic, extra=forbid): run_id, created_at (UTC), git_sha,
  dataset_id, dataset_manifest_path, feature_set_id, feature_version, config_hash, seed,
  metrics (empty placeholder), decision (default keep_researching), decided_by, notes,
  kind="experiment", no_trading/no_backtesting/no_model_training=true (enforced True)
- run_id unique & immutable: re-appending an existing run_id is rejected, nothing written
- git_sha captured via subprocess `git rev-parse HEAD` only (local, never networks)
- new_experiment_record(...) auto-fills run_id/created_at/git_sha
- list_experiments CLI: --registry <path>
- Phase 3C extended the record: added as_of, report_path, weight_source fields
- capital-safety flags ENFORCED True: no_trading, no_model_training, no_live_execution,
  no_order_submission. no_backtesting is now informational (default True; backtest runs set
  it False) — backtesting is legitimate from Phase 3 on

Backtest experiment runner (Phase 3C):
- research.experiment_runner.run_backtest_experiment(*, bars_path, weights_path, as_of,
  weight_source, seed, horizon, symbols, costs_path, registry_path, report_dir, ...)
- wires PIT read -> run_backtest -> run_null_battery -> JSON+MD report -> registry append
- weights are CALLER-PROVIDED local Parquet (symbol,timestamp,weight); runner generates NO
  strategy/signal/alpha/optimizer/model
- as_of REQUIRED; PIT enforced (load_pit_bars + run_backtest as_of); fail-closed on lookahead
- timestamps normalized to UTC before the bars/weights join (DuckDB can return local tz)
- metrics dict[str,float] strictly numeric; bool diagnostics encoded 1.0/0.0 (e.g.
  nb.future_leak_detected); full structured diagnostics go to the JSON report
- compute_config_hash = sha256 over canonical result-determining config (deterministic)
- experiment_report.py: build_report_payload / render_markdown / write_report (JSON + MD)
- CLI: scripts/run_experiment.py (--bars --weights --as-of --weight-source required)
- reports + registry land in git-ignored data/runs/, never committed

Report hardening (Phase 3D-1 — data declaration + tier banner):
- experiment_report.py now surfaces data honesty at the TOP of every report:
  - build_report_payload(..., data_declaration=<mapping|None>) optional, defaults None
  - JSON payload gains: data_declaration (block or null), data_declaration_status
    (COMPLETE | INCOMPLETE | MISSING), data_declaration_missing_fields (list)
  - Markdown gains a "## Data Declaration" section right under the header, before metrics,
    showing tier, survivorship_bias_status, corporate_actions_status, pit_status,
    data_declaration_id, universe_source, data_feed
  - CRITICAL_DECLARATION_FIELDS = tier, survivorship_bias_status, corporate_actions_status,
    pit_status (DATA_QUALITY.md §2). Missing/blank => report marked SUSPECT (never silently
    clean): absent declaration => "DATA DECLARATION MISSING ... SUSPECT"; partial => INCOMPLETE
  - tier == 0 => visible banner "Tier 0 data validates code, not strategy."
  - summarize_data_declaration(declaration) classifies status + missing fields
- experiment_runner.run_backtest_experiment(..., data_declaration=<mapping|None>) threads the
  declaration through to the report (no engine/alpha/strategy change)
- report-only change: no trading/order/model/optimizer/API/backtest-logic touched
- verification:
    cd /Users/maxencedelabrousse/Developer/alpaca-quant && source .venv/bin/activate
    ruff check python && (cd go && go vet ./...) && python -m pytest python/tests -q
- next recommended step: Phase 3D-2 — Null Battery verdict + ENGINE_SUSPECT (surface the
  null-battery PASS/FAIL verdicts at the top of the report; if the future-leak trap does NOT
  explode, flag the report ENGINE_SUSPECT — the trap tests the backtester itself)

Report hardening (Phase 3D-2 — null battery verdict + ENGINE_SUSPECT):
- experiment_report.py summarizes the EXISTING null battery at the report layer (no engine
  change, no strategy logic):
  - summarize_null_battery(null_battery) -> {available, verdicts, future_leak_exploded,
    engine_suspect}. Verdicts (PASS/FAIL/UNKNOWN): random_signal, shifted_signal,
    future_leak_trap, shuffled_labels, cost_stress_2x, cost_stress_5x
  - mapping from existing diagnostics: random_signal<-random_near_zero,
    shuffled_labels<-shuffled_near_zero, future_leak_trap<-future_leak_detected;
    shifted_signal PASS if shifted.sharpe <= baseline.sharpe (must not improve);
    cost_stress_{2x,5x} PASS if that variant's total_return > 0
  - future-leak trap is special: engine_suspect = not future_leak_detected (the trap tests the
    backtester itself)
  - compute_report_health(declaration_status, battery_summary) -> OK | SUSPECT | ENGINE_SUSPECT
    - ENGINE_SUSPECT wins (broken engine invalidates everything)
    - SUSPECT if battery unavailable, any CORE check (random/shuffled/future_leak) not PASS, or
      declaration not COMPLETE
    - OK only if declaration COMPLETE and core battery passes
    - CORE_BATTERY_CHECKS gate health; cost_stress/shifted are displayed-but-informational
  - JSON payload gains: report_health, null_battery_summary
  - Markdown gains: top-of-report health banner (✅ OK / ⚠️ SUSPECT / 🛑 ENGINE_SUSPECT) right
    under the title, and a "## Null Battery Verdict" section after Data Declaration
- report-only change: no engine/null_models/alpha/strategy/optimizer/order/API touched
- verification:
    cd /Users/maxencedelabrousse/Developer/alpaca-quant && source .venv/bin/activate
    ruff check python && (cd go && go vet ./...) && python -m pytest python/tests -q
- next recommended step: Phase 3D-3 — reproducibility fingerprint + fail-closed report schema
  validation (surface git_sha + data_version + config_hash + seed in the report, and validate
  the report payload against a fixed schema; refuse to render a report missing critical fields)

Report hardening (Phase 3D-3 — reproducibility fingerprint + fail-closed schema):
- experiment_report.py adds an auditable, registry-linked reproducibility fingerprint and
  fail-closed validation (still report-layer only; no engine/strategy change):
  - build_reproducibility(...) -> reproducibility block: run_id, created_at, config_hash, seed,
    git_sha, dataset_id, data_declaration_id, feature_set_id, weight_source, weights_path,
    cost_config_path. Optional fields degrade to "UNKNOWN" — never faked.
  - build_report_payload gained optional created_at/git_sha/dataset_id/feature_set_id/
    cost_config_path; JSON payload now carries a top-level "reproducibility" block.
  - Markdown gains "## Reproducibility" (compact table) right under the health banner, plus a
    replay hint "Replay requires: git_sha + dataset/data_version + config_hash + seed + weights
    input." shown ONLY when those essentials are all present (no invented/executable command).
  - validate_report_payload(payload) — FAIL-CLOSED via ExperimentReportError:
    - CRITICAL_REPORT_FIELDS = run_id, config_hash, report_health, headline_metrics,
      reproducibility (registry linkage = run_id present)
    - CRITICAL_REPRODUCIBILITY_FIELDS = run_id, created_at, config_hash
    - called at the top of BOTH render_markdown and write_report (guards MD and JSON); never
      substitutes defaults for a missing critical field
  - missing OPTIONAL fields render as UNKNOWN/null; missing CRITICAL fields raise loudly
- experiment_runner.run_backtest_experiment threads record.created_at/git_sha/dataset_id/
  feature_set_id + costs_path into the report (record built before payload)
- report-only change: no engine/null_models/alpha/strategy/optimizer/order/API touched
- verification:
    cd /Users/maxencedelabrousse/Developer/alpaca-quant && source .venv/bin/activate
    ruff check python && (cd go && go vet ./...) && python -m pytest python/tests -q
- next recommended step: Phase 3D-4 (OPTIONAL polish — e.g. regime PnL surfacing, plot
  references, net-of-cost metric labels) OR pause and hold before Phase 4. Phase 4 (first real
  alphas / weight generation) must be explicitly scoped: it is where signal generation begins
  and each alpha goes through the null battery + promotion gate. Do not start it implicitly.

Report hardening (Phase 3D-4 — report readability polish):
- experiment_report.py keeps established JSON metric keys stable and clarifies Markdown display:
  - headline performance labels explicitly say net where applicable: Sharpe net, Sortino net,
    Total return net, and CAGR net
  - the headline section states that performance metrics use net returns after costs
  - null-model diagnostic table labels are also explicitly net-of-cost
- Markdown top sections now follow the audit-first order: title, health, reproducibility, data
  declaration, null battery verdict, headline metrics, Regime PnL, Plot References, then
  diagnostics and the existing safety boundary
- the current payload has no regime diagnostics or plot references, so reports say explicitly:
  - "Regime PnL: not available in this report."
  - "Plots: not generated for this report."
- report-layer only: no engine, alpha, strategy, model, optimizer, portfolio, signal/weight
  generation, trading, order, or API logic changed
- verification:
    make lint
    make test
- recommendation: pause after Phase 3D-4 before Phase 4
- warning: Phase 4 begins signal / weight / alpha territory and must be explicitly scoped before
  any implementation starts

Safety:
- .env ignored, contains Alpaca keys, never print/read secrets
- data/runs/ ignored, do not commit data artifacts
- no trading
- no backtesting
- no live execution
- no order submission
- no model training
- feature layer has zero Alpaca API calls

Data sources — current & future direction:
- Canonical now: Alpaca is the canonical source for controlled US equities historical bars.
- Future direction: a metadata-first Multi-Source Data Layer / Provider Registry will let us
  enrich the lake with free/secondary sources: FRED -> yfinance bronze -> Alpha Vantage /
  Twelve Data / Finnhub secondary -> CCXT crypto branch, without displacing Alpaca.
- Sequencing: Experiment Registry -> PIT read layer -> Provider Registry -> connectors one by
  one -> honest backtester/null tests last, only after PIT and traceability are in place.
- Hard rules: indicators are computed internally via the feature factory, not provider-supplied;
  free sources are treated cautiously because of rate limits, unofficial APIs, delayed/EOD data,
  and survivorship bias.

ML dataset assembly + data contract (Phase 4C):
- alpaca_quant.research: assemble_ml_dataset, FeatureSpec, DatasetConfig, AssembledMLDataset,
  make_temporal_split, assert_split_disjoint_and_purged, build_dataset_manifest,
  render_dataset_manifest_markdown, fingerprint_dataset, annotate_universe_membership,
  asof_join_reference, resolve_permanent_ids
- modules: research/data_contract.py, research/pit_joins.py, research/splits.py,
  research/ml_dataset.py, research/dataset_manifest.py
- ASSEMBLES A PIT-SAFE (X, y) DATASET ONLY. No model training, no .fit(), no fit/transform,
  no cross-validation execution, no alpha/signal/strategy/weight/portfolio/optimizer/backtest/
  order/trading, no Alpaca API, no network, no .env, no global scaling, no fillna/imputation.
- Data contract enforced: adjusted-close safety (back-adjusted price-level features rejected,
  unknown adjustment -> SUSPECT, only pit_safe passes); PIT universe / anti-survivorship
  (valid_from <= t <= valid_to, open-ended allowed; missing universe -> SUSPECT unless
  synthetic_no_universe); as-of joins (available_at >= timestamp, backward per id,
  restatement-preserving, missing available_at fails closed); symbol identity (date-bounded
  ticker -> permanent_id, never blind-merged; missing identity -> SUSPECT); feature cutoff is
  the prior bar, strictly before the row timestamp = label entry.
- Eligibility never silently drops rows: each row carries eligible / eligibility_reason;
  manifest records null matrix, excluded-by-reason, universe coverage, as-of summary,
  config hash, Phase 4A source label fingerprint (lineage), dataset fingerprint, verdict
  (OK / SUSPECT), and boundary statement. Injectable/frozen clock for generated_at_utc.
- Purged + embargoed split DEFINITIONS only (train/validation/test index sets). Purge removes
  training rows whose label window overlaps evaluation; embargo >= max_horizon. NO CV is run.
- CLI: python scripts/assemble_dataset.py --labels ... --features ... --spec ... --output-json
  ... --output-md ... [--output-dataset ...]; writes manifest only, never into data/runs/.

Feature registry + dataset inspection (Phase 4D):
- alpaca_quant.research: FeatureDefinition, FeatureRegistry, build_registry, validate_definition,
  validate_feature_set, compute_feature_set_id, list_definitions, export_feature_definitions,
  RegistryValidationConfig; build_dataset_inspection_report, render_dataset_inspection_markdown,
  attach_feature_set_id, DatasetReportConfig
- modules: research/feature_registry.py, research/dataset_report.py
- FEATURE METADATA + DATASET INSPECTION ONLY. No feature computation (except synthetic test-only
  pass-through), no model training, no .fit(), no fit/transform, no CV execution, no global
  scaling, no fillna/imputation, no alpha/signal/strategy/weight/portfolio/optimizer/backtest/
  order/trading, no Alpaca API, no network, no .env.
- Feature registry holds neutral/mechanical metadata only and exists to stop unsafe features from
  silently entering datasets. Conservative ordered rules: pit_safe defaults False; uses_future_data
  -> REJECTED; is_alpha_like / alpha-like name / phase-not-allowed -> REJECTED; unknown adjustment
  -> SUSPECT (or REJECTED per config); price-level without explicit PIT-safe declaration ->
  SUSPECT/REJECTED; never safe from the name alone. feature_set_id is a deterministic fs-... hash:
  order/row invariant, version-sensitive, no environment dependency.
- Dataset inspection report audits a 4C dataset: lineage (4A + dataset fingerprint + feature_set_id),
  feature coverage + safety tables, null matrix, eligible/ineligible counts + reasons, PIT universe
  coverage, as-of join coverage, symbol identity coverage, split summaries (definitions only — NO
  CV), warnings, and a verdict with strict precedence REJECTED > SUSPECT > OK listing ALL reasons.
  Markdown carries the verbatim boundary note. Injectable/frozen clock for generated_at_utc.
- CLI: python scripts/inspect_dataset.py --dataset ... --manifest ... [--feature-registry ...]
  --output-json ... --output-md ...; writes the report only, never into data/runs/.

Inspection hardening (Phase 4D-1) — closes 3 audit blind spots found by 4E-0; detect, never mutate:
- modules touched: research/dataset_report.py, research/dataset_manifest.py, research/ml_dataset.py
- `missing_available_at_semantics` (standalone, SUSPECT): a source with no available_at column and
  no reference availability is flagged; the absent available_at is never synthesized.
- `ambiguous_adjustment_declaration` (SUSPECT): assemble_ml_dataset(data_declaration=...) carries the
  DECLARED corporate_actions_status/adjustment_status into the manifest verbatim
  (declared_corporate_actions_status/declared_adjustment_status); absent or non-clean (partial/
  best_effort) is flagged in manifest + report regardless of any price-level feature. Nothing inferred.
- `feature_timezone_mismatch` (SUSPECT): assembly compares feature-source tz vs bar tz; on mismatch
  the features are NOT joined and the condition is flagged (timezone_alignment) — NO tz_convert/
  tz_localize/replace_time_zone is ever called. Because the cross-timezone feature join is refused,
  the dirty fixture may also emit collateral `feature_missing_from_dataset`; this is acceptable as
  a documented consequence. Coverage shortfall stays surfaced by the null gate.
- All three are SUSPECT-class (missing provenance, not leakage); precedence REJECTED > SUSPECT > OK
  preserved; warnings emitted in stable sorted order. The real fixes (re-stamp tz, backfill
  available_at/adjustment provenance) belong to a future ingestion sprint, not 4D-1.

Local synthetic provenance ingestion (Phase 4F-0) — build data, not auditor:
- new files: research/synthetic_provenance.py (fixtures), tests/test_synthetic_provenance_clean.py,
  tests/test_synthetic_provenance_dirty.py. NO auditor module changed (4C/4D/4D-1 untouched).
- builds local, deterministic, in-memory provenance: as-reported bars (per-row available_at >=
  timestamp + permanent_id), PIT universe (valid_from/valid_to incl. a delisted symbol whose
  valid_to ends mid-dataset), date-bounded identity with a mid-window ticker change under one
  permanent_id, explicit corporate-action records (split + dividend) that also feed the as-of
  reference join, and a tz-aligned neutral feature (bar_volume_raw) declared in the registry.
- Clean path: strict assembly → 6 eligible rows; 4C manifest verdict OK AND 4D inspection verdict
  OK; all four 4D-1 warnings absent. Declared corporate_actions_status='full', honest and
  consistent with the supplied records (adjustment auditable from records, not asserted).
- Dirty path (one named reason each): delisted → not_in_universe/ineligible after valid_to;
  no identity → missing_symbol_identity; no reference/available_at → missing_available_at_semantics;
  corporate_actions_status='partial' → ambiguous_adjustment_declaration; foreign feature tz →
  feature_timezone_mismatch (with possible collateral `feature_missing_from_dataset` because the
  cross-timezone feature join is refused); too-short window → 0-eligible/tail-null.
  REJECTED > SUSPECT > OK held.
- determinism: frozen clock in tests, stable sorted warning set, reproducible fingerprints.
- Limitation: an honest OK on synthetic data validates the CONTRACT PATH only; it does NOT validate
  real prices or real provenance. Real-data ingestion (network fetch, vendor corporate actions,
  real PIT universe, tz re-stamping) still owes that and remains a future explicitly-scoped sprint.

Edge Research Protocol:
- docs/EDGE_RESEARCH_PROTOCOL.md is locked as no-code governance. It does not authorize alpha,
  signal, model training, .fit(), or trading logic.

Next recommended sprint:
Pause after Phase 4F-0. Do not start the Experiment Registry, Phase 4E proper, real-data fetch, or
ML training implicitly. Any such work must be explicitly scoped. No alpha, signal, strategy, model
training, optimizer, portfolio construction, trading, order, API, or execution begins automatically.
