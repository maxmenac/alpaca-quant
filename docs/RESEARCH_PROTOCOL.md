# Alpaca Quant — Research Protocol

> Ce document est la **discipline** du système. C'est ce qui transforme « j'ai eu une idée »
> en « cet alpha a gagné le droit de toucher du capital ». Tout passe par ici.

---

## 1. Experiment Registry

Chaque exécution de recherche (backtest, entraînement, évaluation) produit une entrée
immuable. Pas d'entrée = le run n'a jamais eu lieu (on ne lui fait pas confiance).

```yaml
run:
  run_id: "bt-2026-06-14-001"
  created_at: "2026-06-14T20:01:00Z"
  git_sha: "a1b2c3d"
  data_version: "tier1-2026-06-10"
  data_declaration: { ... }          # cf. DATA_QUALITY.md, copié ici
  feature_version: "features-v003"
  config_hash: "sha256:..."
  model_version: "ensemble-2026-06-14-a"
  seed: 42
  metrics:
    sharpe_net: 0.91
    sortino_net: 1.30
    max_drawdown: -0.14
    turnover_annual: 7.8
    capacity_estimate_usd: 2_500_000
  null_tests: { ... }                # cf. §2, doit être PASS
  plots: ["equity_curve.png", "drawdown.png", "regime_pnl.png"]
  decision: "keep_researching"       # rejected | keep_researching | promote_to_paper
  decided_by: "max"
  notes: "edge concentré 2020-2021, à investiguer"
```

Règles :
- `run_id` unique, jamais réécrit.
- Reproductibilité bit-à-bit : `git_sha` + `data_version` + `config_hash` + `seed` rejouent le run.
- `decision` est **humaine** (principe « recommends, approves »). Le système recommande, Max tranche.

---

## 1A. Target / Label Foundation

Phase 4A introduces forward-return labels as a separate, offline research artifact. A label is a
realized future outcome, not a feature and not an alpha:

- `label[t] = price[t+h] / price[t] - 1`, computed independently per symbol.
- Inputs are stably sorted by `(symbol, timestamp)` before the per-symbol future shift.
- The final `horizon` rows of each symbol remain null. Unknown futures are never replaced by `0`.
- Every null label has an auditable reason; manifests record coverage and a deterministic
  fingerprint.
- Labels must never enter the feature factory, signal generation, portfolio construction, live
  trading, or order code.

This foundation creates no strategy, model, optimizer, signal, or weight.

### Phase 4B — Target Quality Gate

Before labels may be consumed by any later research phase, a local QA report must record:

- target manifest identity, fingerprint, source, horizons, and declared columns
- valid/null/non-finite counts and distribution statistics per horizon
- per-symbol coverage and bounded distribution summaries
- null-reason breakdown plus detectable manifest/data mismatches
- warnings for excessive nulls, extreme returns, unsupported metadata, and upstream data risks

The report verdict is `OK` or `SUSPECT`. It never repairs labels, converts nulls to zero, invents
horizons over a manifest/config disagreement, or expands the backtester. Phase 4B remains labels
QA only; Phase 4C must be explicitly scoped.

### Phase 4C — ML Dataset Assembly + Data Contract (no training)

Phase 4C assembles a point-in-time-safe `(X, y)` dataset from existing features and Phase 4A
labels behind a strict adjusted-close / PIT / `available_at` data contract. It answers only
*"can we assemble X and y without silently leaking future information?"* — never *"can we predict
returns?"*. **Phase 4C trains no model, runs no cross-validation, and generates no alpha, signal,
strategy, weight, portfolio, optimizer, backtest, or order.** It is dataset plumbing, not edge
discovery.

Data contract (fail closed, or mark `SUSPECT` — ambiguous data is never coerced into safe data):

- **Adjusted-close doctrine.** Return labels are back-adjustment invariant when computed
  consistently. Price-level features built on **back-adjusted** prices are *rejected*; features
  with **unknown** adjustment provenance are marked `SUSPECT`; only `pit_safe` (as-reported)
  price levels are accepted. Ambiguous price-level features are never silently trusted.
- **PIT universe / anti-survivorship.** A row `(symbol, t)` is eligible only if the symbol is in
  the universe at `t` (`valid_from <= t <= valid_to`, open-ended `valid_to` allowed). Delisted
  symbols remain until `valid_to`; not-yet-listed symbols are absent before `valid_from`. Missing
  universe marks `SUSPECT` unless `synthetic_no_universe` is explicit.
- **As-of join doctrine.** Reference/fundamental values join on real availability time
  (`available_at <= timestamp`, backward as-of per id). A value published late never appears
  before its `available_at`; restatements preserve the value known as of `t` (not the latest
  revision). Missing `available_at` fails closed (or marks `SUSPECT` by config).
- **Symbol identity doctrine.** `permanent_id` is preferred for lineage; tickers are mapped to a
  permanent id only within valid date bounds and are never merged just because they match across
  time. With ticker only, the limitation is documented and the dataset marked `SUSPECT`.
- **Feature cutoff vs label entry.** `feature_cutoff_time` (the prior bar, lag ≥ 1) is strictly
  before the row timestamp; feature windows never overlap the forward label window.

Rows are never silently dropped, filled, imputed, or globally scaled. Each row carries `eligible`
and `eligibility_reason`; the manifest records the null matrix, excluded-by-reason counts,
universe coverage, as-of summary, config hash, Phase 4A source label fingerprint (lineage), a
reproducible dataset fingerprint, the `OK`/`SUSPECT` verdict, and a boundary statement.

Purged + embargoed temporal split **definitions** are index sets prepared for a future ML phase:
training rows whose label window overlaps validation/test are purged, and an embargo of at least
`max_horizon` bars is removed before each evaluation block. **No cross-validation is executed and
no model is trained.** Phase 4D must be explicitly scoped.

---

## 2. Null-Model Test Battery

Avant qu'un alpha soit pris au sérieux, il doit **survivre** à une batterie de tests conçus
pour tuer les faux edges. Un bon backtester fait échouer le bruit. Tous doivent passer.

| Test | Ce qu'on fait | Critère de PASS |
|------|---------------|-----------------|
| **Random signal** | Remplacer l'alpha par du bruit aléatoire | Sharpe net ≈ 0 (sinon : backtester biaisé) |
| **Shifted signal** | Décaler le signal de +1 période (info passée seulement) | Edge s'effondre ou reste cohérent, jamais meilleur |
| **Future-leak trap** | Injecter une feature *connue* qui regarde le futur, dans un test contrôlé | Doit produire un résultat **anormalement élevé** (Sharpe irréaliste). Si ça ne réagit pas : soit le trap est mal calibré, soit le backtester ne consomme pas les features comme prévu → bug à corriger avant tout |
| **Shuffled labels** | Mélanger les rendements cibles | Sharpe net ≈ 0 |
| **Cost stress ×2 / ×5** | Multiplier les coûts par 2 puis 5 | L'edge survit à ×2 ; à ×5 on connaît la marge de sécurité |

> Le **future-leak trap** est le test le plus précieux : c'est un test de ton *backtester*,
> pas de ton alpha. La fuite est injectée de façon *contrôlée et connue*, et doit produire un
> résultat irréaliste. Si elle ne le fait pas, soit le trap est mal conçu, soit ton moteur ne
> consomme pas les features comme tu le crois — dans les deux cas, à corriger avant de faire
> confiance au moindre autre résultat.

---

## 3. Alpha Lifecycle / Promotion Gate

Chaque alpha vit dans un état explicite. Chaque transition exige des critères **écrits** +
une entrée registry + l'approbation de Max.

```
IDEA → RESEARCH → BACKTESTED → VALIDATED_OOS → PAPER_CANDIDATE
     → PAPER_ACTIVE → LIVE_CANDIDATE → LIVE_SMALL → LIVE_ACTIVE → RETIRED
```

| Transition | Critères requis |
|------------|-----------------|
| `IDEA → RESEARCH` | Hypothèse écrite + rationale économique (pourquoi cet edge devrait exister) |
| `RESEARCH → BACKTESTED` | Implémenté, run registry présent, data_declaration complète |
| `BACKTESTED → VALIDATED_OOS` | Null-model battery PASS + walk-forward purgé positif **après coûts** + **Tier 1 min** (DATA_QUALITY §3) |
| `VALIDATED_OOS → PAPER_CANDIDATE` | Décorrélé des alphas existants (|corr| < seuil) + capacité ≥ taille visée |
| `PAPER_CANDIDATE → PAPER_ACTIVE` | Approbation Max + branché au pipeline de signaux |
| `PAPER_ACTIVE → LIVE_CANDIDATE` | ≥ N mois de paper où perf paper ≈ backtest après coûts |
| `LIVE_CANDIDATE → LIVE_SMALL` | Tier 2 + risk policy validée + kill switch testé |
| `LIVE_SMALL → LIVE_ACTIVE` | Cohérence live = paper sur durée significative |
| `* → RETIRED` | Trigger de décroissance (§4) OU décision discrétionnaire |

Aucune transition n'est automatique vers le live. Le système peut **recommander** une promotion
(« cet alpha remplit les critères X, Y, Z ») ; Max approuve.

---

## 4. Decay Monitoring & Demotion (l'ajout critique)

Les alphas meurent. Sans surveillance, tu trades des signaux morts. Un monitoring continu
compare la perf **live/paper récente** à la **baseline de validation** :

- Si le Sharpe glissant tombe sous X % de la valeur validée pendant K jours → **alerte**.
- Si dépassement d'un seuil de drawdown spécifique à l'alpha → **demotion automatique** d'un cran
  (`LIVE_ACTIVE → LIVE_SMALL`, puis `→ RETIRED`), avec notification, **sans attendre l'humain**
  (la rétrogradation est une action de réduction de risque, donc autorisée sans approbation —
  contrairement à l'augmentation d'exposition).
- Toute demotion crée une entrée registry expliquant le trigger.

C'est l'asymétrie clé : **augmenter le risque exige l'approbation de Max ; réduire le risque
ne l'exige jamais.**

---

## 5. Critères d'acceptation du portefeuille (corrigé)

> Remplace l'ancien critère erroné « Sharpe agrégé > somme des Sharpes isolés ».
> Un Sharpe ne s'additionne pas ; le bon baseline est le blend equal-weight.

Le portefeuille agrégé est accepté si **tous** :
- Sharpe/Sortino net **s'améliore vs un blend equal-weight** des mêmes alphas.
- Max drawdown **diminue ou reste acceptable** (pas dégradé par l'agrégation).
- Turnover reste **tradable** après coûts.
- La performance **survit au walk-forward** (pas juste in-sample).
- La performance **n'est pas concentrée dans un seul régime** (vérifier le PnL par régime).
- **Aucun alpha unique** n'explique la majorité du PnL (sinon ce n'est pas un portefeuille,
  c'est un pari déguisé).

---

## 6. Recommended future source order

When the registry opens to new providers (see `ROADMAP.md` → Future Phase: Multi-Source Data
Layer / Provider Registry), onboard in this order:

1. **FRED first** — macro / economic data; official API, stable, clean point-in-time semantics.
2. **`yfinance` later** — experimental/bronze research data only. Never canonical.
3. **Alpha Vantage / Twelve Data / Finnhub** — possible secondary comparison providers for
   validation and coverage cross-checks, not canonical.
4. **CCXT / exchange APIs** — only later, on a separate crypto branch, isolated from the
   US-equities canonical path.

---

## 7. Internal features only (cross-reference DATA_QUALITY.md)

Research datasets derive features exclusively from the internal feature factory.
Provider-side indicators are out of scope for the research protocol to preserve leakage control
and reproducibility across experiment runs. See `DATA_QUALITY.md` → Indicator methodology
design rule.
