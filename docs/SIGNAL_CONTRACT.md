# Alpaca Quant — Signal Contract (Python → Go)  ·  v1.1.0

> La frontière entre recherche et exécution. Python **produit des poids cibles** ;
> Go **transforme en ordres** après risk gate. Pas d'appel direct, pas d'ordres bruts
> traversant la frontière. Ce schéma est versionné et figé.
>
> v1.1 ajoute : traçabilité du mode d'approbation (`approval_*`, `generated_by`), la sémantique
> de rebalancement (`rebalance_type`, `reduce_only`), les bornes d'exposition portefeuille, et
> le lien direct vers la qualité de données (`data_declaration_id`).

---

## 1. Schéma v1.1

```jsonc
{
  "schema_version": "1.1.0",
  "signal_id": "uuid",                       // idempotence / dédup côté Go
  "created_at": "2026-06-14T20:01:00Z",      // heure de production
  "as_of": "2026-06-14T20:00:00Z",           // PIT : connaissance à cette date
  "valid_until": "2026-06-15T20:00:00Z",     // après ça, signal périmé → rejet

  "mode": "paper",                           // paper | live  (Go vérifie la cohérence)
  "rebalance_type": "target_weight",         // target_weight | reduce_only | close_only | rebalance_to_zero
  "generated_by": "python-research-pipeline",
  "approval_required": true,                 // principe "recommends, approves"
  "approval_status": "pending",              // pending | approved | rejected

  "model_id": "ensemble-2026-06-14-a",
  "feature_set_id": "features-v003",
  "universe_id": "us-largecap-v001",
  "backtest_run_id": "bt-2026-06-14-001",    // → experiment registry
  "data_declaration_id": "dq-tier1-us-largecap-2026-06-14",  // → DATA_QUALITY (prouve le tier)

  "horizon": "1d",

  "targets": [
    {
      "symbol": "AAPL",
      "asset_class": "us_equity",
      "target_weight": 0.012,
      "conviction": 0.31,
      "max_position_weight": 0.02,           // borne dure, Go ne dépasse jamais
      "reason_codes": ["momentum", "low_vol"],
      "reduce_only": false                   // override par position si besoin
    }
  ],

  "metadata": {
    "expected_turnover": 0.07,
    "expected_cost_bps": 4.2,
    "risk_score": 0.22,
    "target_gross_exposure": 0.85,           // |longs| + |shorts| — vérifié par le risk gate
    "target_net_exposure": 0.20              // longs − shorts
  }
}
```

---

## 2. Validation côté Go (fail-closed, rejet automatique)

Go **rejette et journalise** tout signal auquel il manque un champ critique, ou qui viole une
invariante de sécurité. Champs requis : `schema_version`, `signal_id`, `valid_until`, `mode`,
`rebalance_type`, `backtest_run_id`, `data_declaration_id`.

Règles de rejet :
- `schema_version` majeure inconnue → **rejet** (on ne devine jamais un champ qui touche au capital).
- `now > valid_until` → **rejet pour péremption** (anti signal périmé).
- `mode != mode_du_processus` (ex. signal `live` reçu par un exécuteur `paper`) → **rejet**.
- `mode == "live"` mais l'app n'a pas `allow_live_trading=true` → **rejet** (cf. SAFETY_POLICY.md).
- ordre vivant proposé alors que `approval_required=true` et `approval_status!="approved"` → **bloqué** au stade proposition.
- `target_gross_exposure` / `target_net_exposure` au-delà des limites de `risk.yaml` → **rejet du signal entier**.

Chaque rejet écrit une ligne de log structurée (`signal_id`, raison, timestamp). L'absence de
signal valide = **pas de trade** (jamais d'exécution « par défaut »).

---

## 3. Sémantique de `rebalance_type` (sécurité par construction)

| Type | Effet | Niveau d'autorisation |
|------|-------|-----------------------|
| `target_weight` | Atteindre les poids cibles (peut augmenter l'expo) | Approbation requise (augmente le risque) |
| `reduce_only` | Ne peut que réduire les positions | Plus permissif (réduit le risque) |
| `close_only` | Ferme les positions listées | Permissif |
| `rebalance_to_zero` | Liquide tout (kill / flatten) | Toujours autorisé (action de sécurité) |

C'est l'asymétrie clé du système : **augmenter l'exposition exige l'approbation de Max ;
réduire l'exposition est plus facilement autorisé** (cohérent avec la demotion automatique de
RESEARCH_PROTOCOL §4).

---

## 4. Transformation poids cible → ordre (côté Go)

```
target_weight (par symbole)
  → position actuelle (portfolio live)
  → delta désiré (filtré par rebalance_type / reduce_only)
  → risk gate : limites expo/secteur/DD + max_position_weight + gross/net exposure
  → proposition d'ordre (paper order proposal)
  → [approval_status == approved]            ← recommends / approves
  → marketable limit order (idempotent : client_order_id = signal_id + symbol)
  → enregistrement ordre/fill + TCA
```

Phase MVP : **pas** de TWAP/VWAP/POV — un marketable limit order suffit. L'idempotence via
`client_order_id` est obligatoire dès le départ (Alpaca documente le `client_order_id` pour
organiser/retrouver les ordres) afin de ne jamais doubler un ordre sur retry.

---

## 5. Évolution du schéma

`schema_version` suit semver. Champ requis ajouté/modifié = **bump majeur**, et Go refuse les
majeures inconnues (fail-closed). Mieux vaut un signal rejeté qu'un signal mal interprété qui
touche au capital.
