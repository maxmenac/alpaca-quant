# Alpaca Quant — Architecture

> Système de trading systématique personnel.
> Philosophie : *Alpaca Quant recommends, Max approves.* Aucune action de capital ne s'exécute
> sans contrôle de risque automatique + approbation explicite.

---

## 0. Principes de conception (le « meilleur de chacun »)

Ces principes priment sur toute décision technique. Quand un choix d'implémentation
contredit un principe, c'est l'implémentation qui change.

| # | Principe | Origine | Conséquence dans le code |
|---|----------|---------|--------------------------|
| P1 | **Many weak signals, one model.** Beaucoup de signaux faibles, peu corrélés, combinés. | Medallion / RenTech | Chaque alpha est isolé, testable, interchangeable (`alphas/`). On ne cherche pas LE signal magique. |
| P2 | **Data hygiene first.** L'edge vient surtout des données propres et point-in-time. | RenTech | Couche `data/pit/` non négociable. Pas de lookahead, pas de biais de survie. |
| P3 | **Costs are the strategy.** Modéliser slippage, commissions, borrow, impact. | Medallion / Jane Street | `backtest/costs/` + `tca/` obligatoires. Un alpha non rentable APRÈS coûts n'existe pas. |
| P4 | **Diversify across uncorrelated streams.** | Bridgewater / Dalio | L'optimiseur cible des sources de rendement décorrélées, pas la concentration. |
| P5 | **Systematic factor premia.** Value, momentum, carry, quality, low-vol. | AQR | Famille `features/factor/` + sleeve plus lent. |
| P6 | **Correctness > cleverness en prod.** Le code qui touche au capital doit être trivialement correct. | Jane Street | OMS en Go, state machine explicite, kill switch, réconciliation quotidienne. |
| P7 | **No faith, only out-of-sample.** Un signal n'est vrai que validé hors échantillon. | tous | `models/validation/` (walk-forward purgé). Bulkowski inclus = features à prouver. |
| P8 | **Human-in-the-loop.** Le LLM propose, l'humain valide avant le live. | design Maxence OS | Rien ne passe `paper → live` sans approbation. |

---

## 1. Vue d'ensemble

```
                ┌─────────────────────────────────────────────┐
                │                  RESEARCH (Python)            │
                │  données → features → alphas → modèle →       │
                │  backtest → validation → signaux              │
                └───────────────────────┬─────────────────────┘
                                         │  signaux validés (fichiers/bus)
                                         ▼
                ┌─────────────────────────────────────────────┐
                │              EXECUTION (Go)                   │
                │  signal → risk gate → portfolio → OMS →       │
                │  exécution → broker (Alpaca) → réconciliation │
                └───────────────────────┬─────────────────────┘
                                         │  fills, PnL, positions
                                         ▼
                ┌─────────────────────────────────────────────┐
                │   MISSION CONTROL (dashboard) + OPS/MONITOR   │
                └─────────────────────────────────────────────┘
```

**Pourquoi Go ET Python :**
- **Python** = recherche, ML, backtest. Écosystème data-science. Itération rapide. Personne ne touche au capital ici.
- **Go** = services temps réel (OMS, risk gate, exécution, ingestion live). Concurrence, latence, robustesse. Esprit Jane Street : ce code doit être *correct*, pas *malin*.

La frontière est nette : **Python produit des signaux, Go les exécute.** Ils communiquent par un contrat de données figé (schéma de signaux versionné), jamais par appels directs.

---

## 2. Arborescence complète

```
alpaca-quant/
├── README.md
├── Makefile                     # cibles: research, backtest, paper, live, lint, test
├── docker-compose.yml           # postgres/timescale, NATS/redis, dashboard
├── .env.example
│
├── go/                          # === TEMPS RÉEL — touche au capital ===
│   ├── cmd/
│   │   ├── executor/            # OMS : reçoit les signaux, gère le cycle de vie des ordres
│   │   ├── marketdata/          # gateway d'ingestion temps réel (ws Alpaca/Polygon)
│   │   ├── riskgate/            # contrôles pré-trade + kill switch (process séparé exprès)
│   │   ├── dashboard/           # API + serveur du Mission Control
│   │   └── reconciler/          # réconciliation fin de journée positions/cash vs broker
│   ├── internal/
│   │   ├── alpaca/              # client broker (REST + websocket), ret- ry, idempotence
│   │   ├── oms/                 # state machine d'ordre : new→sent→partial→filled→done
│   │   ├── execution/           # algos d'exécution : TWAP, VWAP, POV, peg, smart routing
│   │   ├── tca/                 # transaction cost analysis : slippage réalisé vs attendu
│   │   ├── risk/                # limites temps réel : expo brute/nette, secteur, DD, var
│   │   ├── signals/             # consumer : lit les signaux produits par Python
│   │   ├── portfolio/           # positions live + PnL temps réel
│   │   ├── marketdata/          # carnet, ticks, barres, normalisation
│   │   ├── store/               # persistance (timeseries + postgres)
│   │   ├── bus/                 # abstraction message bus (NATS/Kafka/redis)
│   │   ├── config/              # chargement typé des YAML
│   │   └── telemetry/           # metrics (Prometheus), logs structurés, tracing
│   └── pkg/                     # libs partagées exportables
│
├── python/                      # === RECHERCHE & ML — ne touche jamais au capital ===
│   ├── alpaca_quant/            # package installable (pip install -e .)
│   │   ├── data/
│   │   │   ├── ingestion/       # connecteurs vendeurs : alpaca, polygon, fred, edgar...
│   │   │   ├── cleaning/        # corporate actions, splits, dividendes, ajustements
│   │   │   ├── universe/        # construction d'univers SANS biais de survie
│   │   │   └── pit/             # point-in-time / as-of : garantit zéro lookahead
│   │   ├── features/
│   │   │   ├── price/           # rendements, volatilité, momentum, mean-reversion
│   │   │   ├── microstructure/  # spread, order-flow imbalance, volume profile
│   │   │   ├── patterns/        # Bulkowski : patterns codés comme features mesurables
│   │   │   ├── factor/          # value, quality, low-vol, carry  (AQR)
│   │   │   ├── macro/           # régimes, inputs risk-parity, corrélations  (Dalio)
│   │   │   ├── sentiment/       # features dérivées NLP/LLM (news, filings)
│   │   │   └── store/           # feature store versionné (parquet + manifest)
│   │   ├── alphas/              # signaux faibles INDÉPENDANTS  (P1 — Medallion)
│   │   │   ├── base.py          # interface Alpha : .compute() -> score [-1,1]
│   │   │   ├── mean_reversion/
│   │   │   ├── momentum/
│   │   │   ├── factor/
│   │   │   ├── pattern/         # alphas basés sur features patterns validées
│   │   │   ├── seasonality/
│   │   │   └── registry.py      # enregistrement + métadonnées (capacité, horizon)
│   │   ├── models/
│   │   │   ├── train/           # entraînement (gradient boosting, linéaire régularisé...)
│   │   │   ├── predict/         # inférence -> forecast de rendement par actif
│   │   │   ├── ensemble/        # combine les alphas en un forecast unifié (P1)
│   │   │   └── validation/      # walk-forward purgé, CV avec embargo (de Prado) (P7)
│   │   ├── portfolio/
│   │   │   ├── optimizer/       # mean-variance, risk parity, Kelly PLAFONNÉ
│   │   │   ├── risk_model/      # covariance factorielle, expositions
│   │   │   └── constraints/     # limites de poids, secteur, turnover, liquidité
│   │   ├── backtest/
│   │   │   ├── engine/          # event-driven, point-in-time, ZÉRO lookahead
│   │   │   ├── costs/           # slippage, commission, borrow, impact  (P3)
│   │   │   └── metrics/         # Sharpe, Sortino, Calmar, max DD, turnover, capacité
│   │   ├── llm/                 # couche orchestration LLM (l'« auto-amélioration », cadrée)
│   │   │   ├── research_agent/  # génère des hypothèses, revue de littérature
│   │   │   ├── feature_gen/     # propose de nouvelles features SOUS FORME DE CODE
│   │   │   ├── leakage_check/   # relit le code pour détecter lookahead / fuite
│   │   │   └── reporting/       # synthèses narratives des runs de recherche
│   │   ├── research/            # notebooks, expériences (jamais importé en prod)
│   │   └── signals_out/         # écrit les signaux validés pour le consumer Go
│   ├── pyproject.toml
│   └── tests/
│
├── data/
│   ├── raw/                     # immutable, tel que reçu des vendeurs
│   ├── processed/               # nettoyé, ajusté
│   ├── features/                # feature store matérialisé
│   ├── universe/                # univers historiques (sans biais de survie)
│   └── backtests/               # résultats + artefacts reproductibles
│
├── configs/
│   ├── universe.yaml            # définition de l'univers tradable
│   ├── strategies.yaml          # composition des sleeves (rapide / lent)
│   ├── alphas.yaml              # quels alphas actifs, poids, horizons
│   ├── risk.yaml                # limites : DD, expo, secteur, position max
│   ├── execution.yaml           # algos par défaut, urgence, participation
│   ├── costs.yaml               # hypothèses de coûts par classe d'actif
│   └── llm.yaml                 # modèles, garde-fous, prompts système
│
├── ops/
│   ├── monitoring/              # dashboards Grafana, règles d'alerte
│   ├── runbooks/                # procédures : kill switch, panne broker, désync
│   └── ci/                      # pipelines de tests + checks de fuite de données
│
└── docs/
    ├── ARCHITECTURE.md          # ce fichier
    ├── ROADMAP.md               # plan de build par phases
    ├── DATA_GOVERNANCE.md       # règles point-in-time, anti-fuite
    ├── RISK_POLICY.md           # limites, règles de drawdown, sizing
    ├── RESEARCH_PROTOCOL.md     # comment un alpha passe de l'idée au live
    └── DECISIONS.md             # Architecture Decision Records (ADR)
```

---

## 3. Les couches en détail

### 3.1 Data (RenTech / Two Sigma) — *la fondation*

C'est ici que la majorité de l'edge se gagne ou se perd. Deux invariants absolus :

- **Point-in-time (P2).** Toute donnée doit être interrogeable « telle qu'elle était connue à la date T ». Un fondamental publié le 15 ne doit jamais apparaître dans une feature du 10. Le module `data/pit/` matérialise cette garantie ; rien dans `features/` ne lit la donnée brute directement.
- **Pas de biais de survie.** L'univers historique doit contenir les actifs *délistés/faillis*. Sinon ton backtest n'a vu que les gagnants — l'erreur la plus commune et la plus fatale.

Les corporate actions (splits, dividendes, fusions) sont gérées dans `cleaning/`, pas ad hoc.

### 3.2 Features (Two Sigma) — *le feature store*

Chaque feature est : (1) calculée à partir de données PIT, (2) versionnée, (3) accompagnée d'un manifest (auteur, date, dépendances, fenêtre de calcul). Le **feature store** évite de recalculer et garantit que recherche et prod voient *exactement* la même feature.

Familles :
- `price/` — rendements, vol réalisée, momentum, mean-reversion.
- `microstructure/` — spread, order-flow imbalance (utile horizons courts).
- `patterns/` — **Bulkowski**. Chaque pattern (head-and-shoulders, triangles, drapeaux…) est codé comme un détecteur produisant une feature numérique (présence, force, qualité). On mesure ensuite son edge réel ; il n'a aucun statut privilégié.
- `factor/` — **AQR** : value, quality, low-vol, carry.
- `macro/` — **Dalio** : indicateurs de régime, inputs de risk parity.
- `sentiment/` — features NLP/LLM dérivées de news et filings (voir §3.7).

### 3.3 Alphas (Medallion) — *beaucoup de signaux faibles*

Un **alpha** = une fonction qui, à partir de features, produit un score de conviction `[-1, 1]` par actif et par date. Interface unique (`base.py`), enregistrement dans `registry.py` avec ses métadonnées (horizon, capacité estimée, turnover attendu).

La règle d'or (P1) : on ne cherche pas un alpha à fort Sharpe isolé (souvent un artefact d'overfit). On cherche **beaucoup d'alphas peu corrélés entre eux**, chacun avec un edge modeste mais réel. La décorrélation est ce qui fait le Sharpe agrégé.

### 3.4 Ensemble / forecast (RenTech + AQR)

Le module `models/ensemble/` combine les scores d'alphas en un **forecast de rendement unifié** par actif. C'est l'équivalent du « modèle unique » de RenTech : tout converge dans une seule prévision, pondérée par la performance out-of-sample et la corrélation des alphas. Modèles privilégiés : linéaires régularisés et gradient boosting — interprétables, robustes, difficiles à sur-ajuster.

### 3.5 Portfolio construction (AQR / Dalio)

Du forecast aux **poids réels** :
- `risk_model/` — covariance factorielle (pas juste historique brute).
- `optimizer/` — mean-variance OU risk parity selon le sleeve ; **Kelly plafonné** (jamais full-Kelly, qui est suicidaire en pratique).
- `constraints/` — poids max, expo secteur, turnover (P3 : un optimiseur qui ignore le turnover génère des coûts qui mangent l'alpha), liquidité.

Deux sleeves possibles : un **rapide** (alphas court terme, esprit Medallion, exécution critique) et un **lent** (factor premia AQR, faible turnover). Dalio entre ici : les deux sleeves doivent être *décorrélés*.

### 3.6 Risk gate + Execution (Jane Street)

**Risk gate** = process Go **séparé** (volontairement isolé du moteur d'exécution) qui peut tout arrêter. Contrôles pré-trade : exposition brute/nette, limites par position/secteur, drawdown intraday, sanity checks (prix aberrant, taille folle). Le **kill switch** est un bouton physique du système, documenté dans `ops/runbooks/`.

**Execution.** L'edge horizon court de RenTech vit ou meurt à l'exécution. Algos dans `execution/` (TWAP/VWAP/POV/peg). `tca/` mesure en continu le slippage réalisé vs attendu — si l'exécution dégrade l'alpha, la recherche le saura.

**Reconciler.** Chaque fin de journée : positions et cash du système vs broker Alpaca. Toute divergence = alerte bloquante.

### 3.7 LLM (l'« auto-amélioration », cadrée honnêtement)

Le LLM **ne trade pas** et **n'optimise jamais sur les rendements passés.** Rôles autorisés :

- `research_agent/` — génère des hypothèses d'alpha, fait de la revue de littérature.
- `feature_gen/` — propose de nouvelles features **sous forme de code** que tu lis avant de l'exécuter.
- `leakage_check/` — relit le code de feature/alpha pour repérer un lookahead ou une fuite (un usage où le LLM excelle vraiment).
- `reporting/` — résume les runs de recherche en langage clair.

**La boucle d'auto-amélioration réelle** (et sûre) :

```
  LLM propose une feature/un alpha (code)
        ↓
  leakage_check (LLM + tests automatiques)
        ↓
  backtest avec walk-forward purgé + coûts  (models/validation, backtest/costs)
        ↓
  promu SEULEMENT si edge out-of-sample APRÈS coûts ET décorrélé de l'existant
        ↓
  Max approuve  →  paper trading  →  (re-validation)  →  live
```

C'est ça, ton système « qui s'enrichit constamment » : pas une IA qui devine le marché, mais un **pipeline de découverte d'alphas discipliné** que le LLM accélère. Le garde-fou anti-overfit (P7) est ce qui le rend crédible plutôt que dangereux.

---

## 4. Contrat Python → Go

La frontière est un **schéma de signaux versionné** (pas d'appel direct). Python écrit dans
`signals_out/` (ou publie sur le bus) un message du type :

```jsonc
{
  "schema_version": "1.0.0",
  "as_of": "2026-06-14T20:00:00Z",   // PIT : connaissance à cette date
  "model_id": "ensemble-2026-06-14-a",
  "horizon": "1d",
  "targets": [
    { "symbol": "AAPL", "target_weight": 0.012, "conviction": 0.31 },
    { "symbol": "MSFT", "target_weight": -0.008, "conviction": 0.18 }
  ],
  "metadata": { "expected_turnover": 0.07, "expected_cost_bps": 4.2 }
}
```

Go reçoit des **poids cibles**, jamais des ordres bruts. C'est Go (risk gate + portfolio + execution) qui transforme poids cibles → ordres, applique les limites, et exécute. Cette séparation est volontaire : la recherche ne peut pas court-circuiter le contrôle de risque.

---

## 5. Reproductibilité (non négociable)

Tout backtest doit être rejouable bit-à-bit : données versionnées, code taggé (git SHA),
config figée, seed fixé. Un résultat non reproductible n'est pas un résultat. Les artefacts
vivent dans `data/backtests/<run_id>/` avec le manifest complet.
