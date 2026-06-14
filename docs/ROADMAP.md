# Alpaca Quant — Roadmap (MVP-first)

> Révision après revue : la version précédente était une *North Star* trop lourde
> (Timescale/NATS/websocket dès la Phase 0 = piège « fantasy repo »). Cette version garde
> la vision mais ordonne pour **build vite et honnêtement**. Règle d'or inchangée :
> **aucun capital réel avant un edge prouvé out-of-sample, après coûts, en paper prolongé.**

> Stack MVP : Python + Parquet/DuckDB en local. **Pas** de websocket, Timescale, NATS, OMS
> complexe, microstructure, ni LLM auto-feature au départ. On les ajoute quand ils sont mérités.

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
