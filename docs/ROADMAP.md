# Alpaca Quant — Roadmap (MVP-first)

> Révision après revue : la version précédente était une *North Star* trop lourde
> (Timescale/NATS/websocket dès la Phase 0 = piège « fantasy repo »). Cette version garde
> la vision mais ordonne pour **build vite et honnêtement**. Règle d'or inchangée :
> **aucun capital réel avant un edge prouvé out-of-sample, après coûts, en paper prolongé.**

> Stack MVP : Python + Parquet/DuckDB en local. **Pas** de websocket, Timescale, NATS, OMS
> complexe, microstructure, ni LLM auto-feature au départ. On les ajoute quand ils sont mérités.

---

## Canonical data source (current)

Alpaca remains the current canonical source for controlled US equities historical bars. All
point-in-time guarantees, ingestion manifests, and downstream research datasets are presently
anchored to Alpaca. Any future provider is additive and does not displace Alpaca as canonical
without an explicit roadmap decision.

**Recommended official order (do not reorder without sign-off):**

1. Sprint 5A — Experiment Registry
2. PIT read layer
3. Multi-Source Data Layer / Provider Registry
4. Provider connectors, one by one
5. Honest backtester / null tests — only once traceability and PIT safeguards are in place

---

## Phase 0 — Repo + configs + data lake local
- [ ] Repo propre, `Makefile`, `pyproject.toml`, configs YAML.
- [ ] Data lake **local** : Parquet + DuckDB (zéro infra serveur).
- [ ] `DATA_QUALITY.md` appliqué : chaque dataset porte son tier + sa déclaration.
- **Sortie :** je peux requêter mes données en SQL local et chaque dataset déclare sa qualité.

## Phase 1 — Historical bars downloader
- [ ] Downloader barres journalières Alpaca → **SIP historique** (gratuit, >15 min, 100 % marché).
- [ ] Stockage Parquet partitionné, idempotent, re-runnable.
- [ ] Gestion splits/dividendes (passe Tier 0 → vise Tier 1).
- **Sortie :** un univers de barres daily propres, reproductible, taggé Tier 0/1.

## Phase 2 — Feature factory (simple)
- [ ] Quelques familles de features daily : rendements, vol, momentum, mean-reversion.
- [ ] Feature store versionné (`feature_set_id`), lecture via couche PIT uniquement.
- **Sortie :** features versionnées, jamais lues depuis la donnée brute.

## Phase 3 — Backtester brutalement honnête + null tests
- [ ] Moteur event-driven, point-in-time, zéro lookahead.
- [ ] Modèle de coûts (slippage/commission), métriques (Sharpe, Sortino, DD, turnover, capacité).
- [ ] **Null-Model Battery** (RESEARCH_PROTOCOL §2) : random, shifted, future-leak trap, shuffled, cost stress ×2/×5.
- **Sortie :** le bruit donne Sharpe ≈ 0 ; la fuite volontaire fait EXPLOSER le résultat. Sinon le moteur est cassé — on ne continue pas.

## Phase 4 — 3 alphas simples
- [x] **Phase 4A foundation only** : forward-return labels per symbol, tail nulls preserved,
  deterministic fingerprint/manifest, no alpha/signal/weight/model.
- [x] **Phase 4B QA only** : JSON/Markdown target-quality report, null/distribution audits,
  manifest consistency warnings, no backtest/alpha/signal/model/weight expansion.
- [x] **Phase 4C dataset assembly only** : PIT-safe `(X, y)` assembly behind an adjusted-close /
  PIT universe / `available_at` as-of / symbol-identity data contract. Eligibility flags + null
  matrix + lineage fingerprint + `OK`/`SUSPECT` manifest; purged + embargoed split *definitions*
  (index sets) only. **No model training, no CV execution, no alpha/signal/strategy/optimizer/
  weight/portfolio/backtest/trading.** Split definitions are prepared for future ML but train
  nothing. Phase 4D must be explicitly scoped.
- [x] **Phase 4D feature registry + inspection only** : local feature registry (neutral/mechanical
  metadata only — no feature is computed) with conservative safety classification (future-looking
  / alpha-like → REJECTED, ambiguous adjustment / not-pit-safe → SUSPECT, never safe from name
  alone), deterministic `feature_set_id`, and a 4C dataset inspection report (coverage/safety/null
  tables, lineage, verdict `REJECTED > SUSPECT > OK` listing all reasons, verbatim boundary note).
  **No model training, no CV, no alpha/signal/strategy/optimizer/weight/portfolio/backtest/trading.**
  The registry prevents unsafe features from silently entering datasets; inspection audits 4C
  quality before any future ML. Phase 4E must be explicitly scoped.
- [x] **Phase 4D-1 inspection hardening (flag, never mutate)** : closes the three audit blind spots
  found by the 4E-0 real-data run — `missing_available_at_semantics` (no availability column),
  `ambiguous_adjustment_declaration` (declared corporate-action/adjustment status carried verbatim,
  flagged when absent/partial), `feature_timezone_mismatch` (feature tz ≠ bar tz → join refused, no
  conversion). All SUSPECT-class; detection/classification only — nothing synthesized, inferred, or
  converted. The actual fixes belong to a future ingestion sprint.
- [x] **Phase 4F-0 local synthetic provenance ingestion (build data, not auditor)** : constructs
  local, deterministic provenance fixtures — as-reported bars (per-row `available_at` + `permanent_id`),
  PIT universe (`valid_from`/`valid_to` incl. a delisted symbol), date-bounded identity with a
  mid-window ticker change, explicit corporate-action records (split + dividend), tz-aligned neutral
  feature — and feeds them to the **unchanged** 4C/4D/4D-1 chain. Proves the auditor reaches an honest
  **OK** on a clean slice AND still refuses a dirty slice for one named reason each. Adjustment is
  auditable from records, not asserted. Still local-only: no network, alpha, signal, model, training,
  or trading. An honest OK validates the contract path only — not real prices/provenance.
- [x] **Phase 4E dataset/run lineage registry (descriptive provenance only)** : local JSONL ledger
  that records existing 4C manifest + 4D/4D-1 inspection outputs: dataset id/fingerprint,
  `feature_set_id`, label fingerprint, split definitions, declared adjustment posture, inspection
  verdict, and full reason list verbatim. It never evaluates predictive quality and adds no edge,
  signal, model, training, `.fit()`, registry for future edge tests, data ingestion, or trading.
  Forward compatibility is limited to `record_type="lineage"` plus stable entry/dataset/schema ids;
  future edge-research records remain docs-only and gated on 4F-2 + `EDGE_RESEARCH_PROTOCOL.md`.
- [ ] momentum cross-sectional, mean-reversion court terme, un facteur AQR (value/low-vol).
- [ ] Bonus : une famille de patterns Bulkowski **mesurée** (edge à prouver).
- [ ] Chaque alpha suit le Promotion Gate ; matrice de corrélation (on veut la décorrélation).
- **Sortie :** ≥ 2 alphas avec edge OOS positif après coûts, peu corrélés. (Tier 1 requis pour `VALIDATED_OOS`.)

## Phase 5 — Ensemble + portfolio construction
- [ ] Ensemble → forecast unifié. Risk model. Optimiseur (risk parity / mean-var, **Kelly plafonné**).
- [ ] Contraintes turnover/secteur/liquidité.
- **Sortie :** le portefeuille passe les critères corrigés (RESEARCH_PROTOCOL §5).

## Phase 6 — Go risk gate + paper order proposal
- [ ] Risk gate (process séparé) + kill switch documenté.
- [ ] Contrat de signaux (SIGNAL_CONTRACT.md) : Python écrit `data/signals/latest_signal.json`, Go le lit.
- [ ] OMS **minimal** : target → delta → risk gate → proposition → approbation → marketable limit → record. Idempotence via `client_order_id`.
- **Sortie :** le risk gate bloque un ordre qui viole une limite (test d'intrusion volontaire).

## Phase 7 — Alpaca paper trading
- [ ] Pipeline complet en paper, en continu.
- [ ] Vue read-only minimale (Streamlit lisant le registry + PnL paper) — pas Grafana, juste de la visibilité.
- [ ] Comparer perf paper vs backtest ; tout écart = bug ou lookahead caché.
- **Sortie :** ≥ 3 mois de paper où perf ≈ backtest après coûts. Sinon retour Phase 3–6.

## Phase 8 — LLM research assistant
- [ ] `feature_gen` (propose du code à relire), `leakage_check` (relit pour fuites), `research_agent` (hypothèses).
- [ ] Boucle : proposition → leakage check → backtest purgé → promotion conditionnelle → **approbation Max** → paper.
- **Sortie :** le LLM a produit ≥ 1 alpha qui survit au protocole complet (validation auto, approbation humaine).

## Phase 9 — Dashboard / Mission Control
- [ ] Le vrai dashboard Go (positions, expo, PnL, alertes). Bus/Timescale **ici** si justifié, pas avant.

## Phase 10 — Live, capital minuscule
- [ ] Tier 2 (delisted + PIT) requis. Capital minimal, limites serrées, kill switch testé.
- [ ] Réconciliation + TCA quotidiens. Montée en capital seulement si live = paper = backtest sur durée.

---

## Future Phase: Multi-Source Data Layer / Provider Registry

Sequenced after the Experiment Registry and the PIT read layer (see "Recommended official
order" above).

Introduce a provider registry so the data lake can be enriched with free/secondary sources
while keeping Alpaca canonical. The registry is metadata-first: it describes and governs
sources before any connector is implemented. **No fetchers ship in this phase.**

Scope of the registry, tracked per provider:

- **provider name** — e.g. `alpaca`, `fred`, `yfinance`, `alpha_vantage`, `twelve_data`,
  `finnhub`, `ccxt`
- **asset class** — equities, ETF, macro, crypto
- **source role** — canonical, secondary, experimental/bronze
- **API type** — official API vs unofficial wrapper
- **rate-limit notes**
- **license / terms note**
- **delay status** — delayed / EOD / realtime
- **price adjustment** — adjusted vs unadjusted
- **survivorship-bias warning**
- **point-in-time compatibility**
- **source manifest path**
- **ingestion timestamp**
- **quality warnings**

---

## Ordre des dépendances d'infra (ce qu'on ajoute, quand)
```
fichier JSON  →  SQLite/DuckDB  →  Redis/NATS  →  dashboard temps réel
(MVP)            (si besoin)        (si latence)     (Phase 9)

daily SIP historique  →  websocket IEX/SIP realtime
(Phases 1-7)              (seulement si stratégie intraday + abonnement SIP)
```

## Lucidité
- Medallion est fermé et inimitable à l'échelle. L'objectif réaliste : un système systématique
  discipliné qui capte des primes connues et des edges d'exécution à petite échelle.
- Ennemis : overfit, fuite de données, coûts, capacité. L'ordre des phases EST la défense.
- La rentabilité est un résultat de recherche long terme, pas une garantie. Le paper prolongé est le filtre honnête.

> Conception de système, pas conseil en investissement. Les décisions de capital et de risque restent les tiennes.
