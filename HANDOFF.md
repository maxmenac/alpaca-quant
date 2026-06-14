# Alpaca Quant — Current Handoff

Latest clean state:
- Branch: main
- Latest commit: 96a9a77 docs: add multi-source data layer roadmap direction
- Repo clean and synced with origin/main (before Sprint 6A work)

Current pipeline:
config loader -> data declaration manifest -> Alpaca bars client -> Parquet writer -> DuckDB query -> mock dry run -> real controlled fetch -> API diagnostics -> run registry -> list-runs CLI -> PIT read layer -> feature factory (PIT-first) -> list-feature-sets CLI -> research dataset loader -> list-research-datasets CLI -> experiment registry -> list-experiments CLI

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
- discipline scaffolding only — NO backtest runs executed yet (RESEARCH_PROTOCOL.md §1)

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
Phase 3 — honest backtester + null-model battery. It should read bars via the PIT layer
(load_pit_bars / assert_no_lookahead), build features via build_pit_feature_set, and write
immutable entries to the experiment registry. A follow-up may remove the legacy raw
build_feature_set once the backtester is fully on PIT.
Still no labels, no signals, no model training, no trading until that sprint is explicitly scoped.
