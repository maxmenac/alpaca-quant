# Alpaca Quant — Safety Policy

> **RISK_POLICY.md** = limites financières (combien risquer).
> **SAFETY_POLICY.md** (ce fichier) = invariants que le système **n'a jamais le droit** de violer,
> quelles que soient les limites financières. Ce sont des barrières dures, pas des paramètres.

---

## 1. Invariants absolus (fail-closed)

Le système doit **refuser de démarrer** ou **s'arrêter** plutôt que de violer un de ces points :

1. **Pas d'ordre live sans flag explicite.** `allow_live_trading=true` doit être positionné
   explicitement. Absent ou ambigu → le système démarre en `paper`, point.
2. **Jamais contourner le risk gate.** Aucun chemin de code n'envoie un ordre sans passer par lui.
3. **Python n'exécute jamais.** Python produit des signaux. Toute exécution passe par Go.
4. **Jamais trader un signal périmé.** `now > valid_until` → rejet (cf. SIGNAL_CONTRACT §2).
5. **Jamais trader si la réconciliation broker a échoué.** Désync positions/cash = arrêt, pas trade.
6. **Jamais augmenter l'exposition sans approbation** quand `approval_required=true`.
7. **Les actions reduce-only / close / flatten sont autorisées** sous la politique de demotion,
   sans approbation (réduire le risque ne nécessite jamais d'attendre l'humain).
8. **Kill switch prioritaire.** Une fois déclenché, aucun nouvel ordre d'augmentation d'expo
   n'est accepté jusqu'à réarmement manuel.

> Asymétrie fondamentale du système : **augmenter le risque → approbation humaine requise ;
> réduire le risque → toujours permis.** Tout le reste en découle.

---

## 2. Configuration globale (fail-closed par défaut)

`configs/app.yaml` :

```yaml
mode: paper                    # paper | live
allow_live_trading: false      # doit être true EXPLICITEMENT pour tout ordre live
require_human_approval: true   # principe "recommends, approves"
max_notional_order_usd: 1000   # plafond dur par ordre (sécurité MVP)
kill_switch_armed: true        # au moindre doute, désarme l'augmentation d'expo
```

Au démarrage, Go **vérifie et journalise** la config résolue. Règles de boot :
- `mode: live` **mais** `allow_live_trading: false` → **refus de démarrer** (incohérence).
- `require_human_approval: false` en `mode: live` → refus de démarrer (interdit en MVP).
- tout ordre dont le notional dépasse `max_notional_order_usd` → rejet de l'ordre.

---

## 3. Procédures (renvoi runbooks)

Les procédures détaillées vivent dans `ops/runbooks/` :
- déclenchement et réarmement du kill switch,
- panne broker / API Alpaca indisponible,
- divergence de réconciliation,
- drawdown limite atteint (→ flatten ou reduce-only selon RISK_POLICY).

---

## 4. Pourquoi séparer SAFETY de RISK

Les limites de risque **évoluent** (tu ajustes ton expo cible, ton DD toléré). Les invariants
de sécurité **ne se négocient pas** : ils protègent contre les bugs, pas contre les pertes de
marché. Mélanger les deux finit toujours par « assouplir temporairement » une barrière de
sécurité pour une raison financière. On garde le mur de sécurité hors de portée du tuning.
