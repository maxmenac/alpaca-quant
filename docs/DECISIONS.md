# Alpaca Quant — Decision Log (ADRs)

> Architecture Decision Records. Chaque ADR est immuable une fois `accepted` ;
> une décision qui change crée un nouvel ADR qui supersède l'ancien.

---

## ADR-001 — Split Python (research) / Go (execution & risk gate)

- **Status:** accepted
- **Date:** 2026-06-14
- **Context:** Le système doit itérer vite côté recherche (ML, backtests, data science) tout
  en gardant un code qui touche au capital trivialement correct, concurrent et robuste. Un
  langage unique forcerait un compromis entre vélocité de recherche et rigueur d'exécution.
- **Decision:** Python est le seul environnement de recherche/ML/backtest et **ne touche jamais
  au capital**. Go est la seule couche (future) d'exécution / risk gate. La frontière est un
  contrat de données figé (voir ADR-002), jamais un appel direct.
- **Consequences:** Deux toolchains à maintenir, mais une séparation des responsabilités nette.
  Python ne peut pas court-circuiter le contrôle de risque. Conforme aux principes P6 et P8 de
  `ARCHITECTURE.md`.

---

## ADR-002 — File-based signal boundary (`data/signals/`) pour le MVP

- **Status:** accepted
- **Date:** 2026-06-14
- **Context:** La communication Python → Go pourrait passer par un bus (NATS/Kafka/redis), mais
  ajouter de l'infra serveur dès le MVP est le piège « fantasy repo » dénoncé dans `ROADMAP.md`.
- **Decision:** Pour le MVP, la frontière est **file-based** : Python écrit un signal JSON
  (schéma `SIGNAL_CONTRACT v1.1.0`) dans `data/signals/`, Go le lit, le valide (fail-closed) et
  propose des ordres. Pas de NATS/Timescale/websocket/dashboard à ce stade.
- **Consequences:** Zéro infra serveur, simple à reproduire et à versionner. Le bus temps réel
  sera ajouté plus tard (Phase 9) **si** justifié, sans changer le contrat de signaux.

---

## ADR-003 — Fail-closed defaults (`allow_live_trading=false`, approbation humaine requise)

- **Status:** accepted
- **Date:** 2026-06-14
- **Context:** Tout système qui touche au capital doit échouer du côté sûr. Un défaut permissif
  (live activé implicitement) est inacceptable.
- **Decision:** `app.yaml` démarre fail-closed : `mode: paper`, `allow_live_trading: false`,
  `require_human_approval: true`, `kill_switch_armed: true`. Go refuse de démarrer en cas
  d'incohérence (`mode: live` sans `allow_live_trading: true`, ou `require_human_approval: false`
  en live). Augmenter l'exposition exige l'approbation ; réduire le risque est toujours permis.
- **Consequences:** Aucun ordre live possible dans ce sprint. Les invariants de `SAFETY_POLICY.md`
  sont appliqués au boot et à la validation de chaque signal.
