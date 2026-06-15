# Alpaca Quant — Current Handoff

Latest clean state:
- Branch: main
- Latest commit: f6755bb feat: add null-model battery for backtest sanity
- Repo clean and synced with origin/main (before Phase 3C work)

Current pipeline:
config loader -> data declaration manifest -> Alpaca bars client -> Parquet writer -> DuckDB query -> mock dry run -> real controlled fetch -> API diagnostics -> run registry -> list-runs CLI -> PIT read layer -> feature factory (PIT-first) -> list-feature-sets CLI -> research dataset loader -> list-research-datasets CLI -> experiment registry -> list-experiments CLI -> backtest engine core (PIT, costs, metrics) -> null-model battery -> backtest experiment runner (registry + report + CLI)

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

Next recommended sprint:
Phase 3D (optional) — walk-forward / purged validation split (RESEARCH_PROTOCOL.md §3,
VALIDATED_OOS), still on caller-provided weights, recorded in the registry.
Then Phase 4 — first real alphas (this is where weight/signal generation finally begins,
each alpha going through the null battery + promotion gate). No model training or real alpha
generation until Phase 4 is explicitly scoped.
