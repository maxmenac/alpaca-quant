# Alpaca Quant — Data Quality

> Principe : **le système ne ment jamais sur la qualité de ses données.**
> Chaque backtest déclare son niveau, et ce niveau **limite** ce qu'un alpha a le droit de
> devenir (voir RESEARCH_PROTOCOL.md → Promotion Gate).

---

## 1. Les niveaux (data quality tiers)

| Tier | Nom | Contenu | Sources typiques | À quoi ça sert |
|------|-----|---------|------------------|----------------|
| **Tier 0** | Research toy data | Barres Alpaca, pas de garantie survivorship-free, corporate actions partielles | Alpaca free (IEX live / SIP historique >15min) | Valider que le **pipeline** marche. JAMAIS une preuve d'edge. |
| **Tier 1** | Serious backtest data | Corporate actions propres (splits/dividendes), snapshots d'univers datés, daily bars SIP | Alpaca SIP historique, vendor avec ajustements | Backtests crédibles intra-univers. Première vraie évaluation d'alpha. |
| **Tier 2** | Institutional-grade | Actifs délistés inclus, fondamentaux PIT, filings PIT, manifests vendeur | Vendor payant (delisted + PIT) | Validation finale avant capital réel. |

> **Réalité Alpaca (formulation prudente)** : le flux SIP historique est interrogeable **sans**
> abonnement SIP temps réel tant que la fin de requête a au moins 15 min. Le **latest/temps réel**
> en SIP exige un abonnement ; sinon c'est IEX (~2 % du volume). → Daily-horizon d'abord ;
> l'intraday/microstructure attend un abonnement SIP realtime. (Cette formulation reste juste
> même si Alpaca change son pricing.)
>
> **Corporate actions Alpaca = best-effort, pas PIT garanti.** Alpaca documente qu'il n'y a
> aucune garantie sur le temps de création des corporate actions (délais de réception et de
> traitement possibles). De plus, les **delistings / radiations / changements de symbole ne sont
> pas exposés par l'API**, et l'historique ne remonte qu'à ~avril 2020. Conséquences directes :
> on ne peut **pas** revendiquer `corporate_actions_status: clean` ni `pit_status: guaranteed`
> à partir d'Alpaca seul, et **les actifs délistés ne viendront jamais d'Alpaca** → le Tier 2
> (survivorship controlled) exige obligatoirement un vendor tiers.

---

## 2. Déclaration obligatoire par backtest

Aucun backtest n'est valide sans ce bloc. Il est écrit dans le manifest du run (voir
EXPERIMENT_REGISTRY) et **affiché** sur tout rapport.

```yaml
data_declaration:
  data_declaration_id: "dq-tier1-us-largecap-2026-06-14"   # référencé par le Signal Contract
  tier: 0                         # 0 | 1 | 2
  universe_source: "alpaca-us-active-2026"
  universe_id: "us-largecap-v001"
  survivorship_bias_status: partial    # unknown | partial | controlled
  corporate_actions_status: partial    # none | partial | clean
  pit_status: best_effort              # none | best_effort | guaranteed
  data_feed: "sip-historical"          # iex | sip-historical | sip-realtime
  date_range: ["2018-01-01", "2026-06-01"]
  known_gaps: ["pre-2020 delistings missing"]
```

Champs non optionnels : `tier`, `survivorship_bias_status`, `corporate_actions_status`,
`pit_status`. Un champ à `unknown`/`none` n'est pas une faute — **mentir** dessus en est une.

---

## 3. Gating : quelle qualité débloque quoi

C'est la règle qui empêche le piège « j'ai validé un edge sur de la toy data ».

| Transition de cycle de vie | Tier minimum requis |
|----------------------------|---------------------|
| `IDEA` → `RESEARCH` → `BACKTESTED` | Tier 0 OK |
| `BACKTESTED` → `VALIDATED_OOS` | **Tier 1 minimum** |
| `VALIDATED_OOS` → `PAPER_CANDIDATE` | Tier 1 minimum |
| `PAPER_ACTIVE` → `LIVE_CANDIDATE` | **Tier 2 fortement recommandé** |
| `LIVE_CANDIDATE` → `LIVE_SMALL` | Tier 2 (delisted + PIT) requis |

Conséquence concrète : tu peux **tout** construire et itérer sur Tier 0 (rapide, gratuit),
mais aucune conclusion Tier 0 ne sert de justification pour mettre du capital. La toy data
valide le code, pas la stratégie.

---

## 4. Anti-fuite (CI)

Un check automatique en CI refuse un merge si :
- une feature lit `data/raw/` au lieu de la couche PIT,
- un backtest utilise une `as_of` postérieure à une donnée qu'il consomme,
- le bloc `data_declaration` est absent d'un run.

---

## 5. Provider registry quality fields

When the Provider Registry phase begins (see `ROADMAP.md` → Future Phase: Multi-Source Data
Layer / Provider Registry), every source entered into the lake must carry the metadata listed
there (provider name, asset class, source role, API type, rate-limit notes, license/terms,
delay status, price adjustment, survivorship-bias warning, point-in-time compatibility, source
manifest path, ingestion timestamp, quality warnings).

Two fields are treated as **gating** for promotion above experimental/bronze:

- **point-in-time compatibility**
- **survivorship-bias warning**

A source missing a clear answer to either stays **bronze**.

---

## 6. Free / secondary source warning

Free data sources are useful but must be treated with care. Known hazards:

- **Rate limits** — free tiers cap calls/min and calls/day; pipelines fail mid-run when the
  ceiling is hit. Record limits in the registry before building on a source.
- **Fragility / unofficial APIs** — wrappers around public sites, such as `yfinance`, can break
  without notice and have no contract.
- **Delayed / EOD data** — most free equity feeds are end-of-day or delayed, not realtime.
- **Survivorship bias** — many free datasets contain only currently-listed symbols, so history
  looks better than reality. Flag and document this per source.

---

## 7. Indicator methodology design rule

Do not trust provider-computed technical indicators as alpha truth. Indicators returned by
external providers, such as moving averages, RSI, or MACD, can use undocumented or unversioned
methodology and can silently introduce leakage or reproducibility issues. All indicators must
be computed internally through our own feature factory so we control methodology, versioning,
leakage handling, and reproducibility. External indicator endpoints may be used only for
cross-checking, never as inputs to research datasets.
