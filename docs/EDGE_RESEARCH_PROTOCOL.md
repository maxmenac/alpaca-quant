# Edge Research Protocol (Design Doc — No Code)

**Document status:** `Design locked / no-code / pre-edge governance`

**Status:** design only. No implementation in this document. No alpha, signal, model
training, `.fit()`, or trading logic is introduced here. This document defines the
*rules of the game* for the eventual edge-research phase, and must be locked before the
first hypothesis is tested.

**Purpose in one sentence:** the same way the PIT/provenance layer refuses to bless data
it cannot audit, this protocol refuses to bless an "edge" it cannot distinguish from luck.

---

## 0. Why this document exists before any edge work

Every prior sprint (4A–4F) was *tractable*: you write a spec, implement it, the test goes
green. Edge research is not like that. You cannot decide to have an edge and code it. You
pose a hypothesis — "this mechanical feature has predictive power over this horizon" — and
the market answers yes or no, and the honest answer is **no** the large majority of the
time, even for excellent researchers.

The danger is specific and predictable: when you *believe* an edge is there, you will find
it — in noise. Two hundred features tested, one looks beautiful by chance, and you keep it.
This is overfitting / data-snooping / p-hacking, and it is how nearly every self-taught
quant lies to themselves. This protocol is the anti-illusion machine, written while your
head is cold and you have no result to protect.

A valid, successful outcome of the edge-research phase is: **"none of the tested hypotheses
showed an edge net of costs."** That is a real finding, exactly as a wall of SUSPECT in
4E-0 was a real finding. The protocol succeeds when the verdict is *honest*, not when it
is *green*.

---

## 1. Inspirations — what to copy and what to ignore

This is part of the protocol, not preamble, because the wrong role model produces the
wrong research behavior.

**Copy the skepticism, not the signals.**

- **AQR (Asness et al.)** — copy directly. Published, serious work on factors and on
  statistical honesty in backtesting (multiple-testing, data-mining of anomalies, why most
  published "anomalies" don't survive). This is the most directly useful inspiration on the
  list. Read their methodology papers as prior art for this protocol.
- **Jane Street** — copy the engineering discipline and the treatment of trading as a
  rigorous, measured, cost-aware activity. Not a source of signals.
- **Two Sigma / Ray Dalio (*Principles*)** — copy the *process* philosophy: systematize,
  write rules in advance, separate the decision from the outcome. Matches how this whole
  repo already works.

**Treat with extreme caution.**

- **Renaissance / Medallion / Simons** — the most dangerous inspiration on the list.
  Probably irreproducible: decades of proprietary data, dozens of math/physics PhDs,
  bespoke execution infrastructure, and an edge living in short-horizon micro-signals
  exploited before everyone else. They have published nothing usable, and the fund is
  closed precisely because the edge dilutes with size. Its defining property is that it
  *does not copy*. Taking Medallion as a target induces the false belief that a huge
  persistent edge exists and you merely need to be clever enough to find it — which is
  exactly the belief that manufactures overfitting. **Do not use as a model.** Admire; do
  not imitate.
- **Bulkowski / chart patterns** — most caution required. Attractive because patterns feel
  like concrete mechanical features you could code. But classical chart-pattern edges
  (head-and-shoulders, triangles, etc.) are, under serious evaluation, weak-to-nonexistent
  net of costs, and notoriously victims of survivorship and data-snooping — the human eye
  finds patterns everywhere, including in random walks. Bulkowski at least *quantifies* his
  statistics, which beats anecdotal technical analysis. But "this pattern worked 63% of the
  time in my sample" is exactly the claim this protocol exists to falsify, not to accept.
  If chart patterns are tested, they are hypotheses to be killed like any other — never a
  presumed edge.

**Synthesis:** none of these people succeeded by *finding* an edge. They succeeded by
having a brutally honest process that let them distinguish the rare real edge from abundant
noise. What you copy is the scepticism. This document encodes it.

---

## 2. Core principles (locked)

1. **Hypothesis before data look.** Every test starts as a written hypothesis with a
   rationale, registered *before* results are seen. No retrofitting a story onto a number.
2. **Decide the metric before the result.** The success metric and threshold are chosen and
   written down before running. You do not get to pick the metric that makes your favorite
   feature look good after seeing the numbers.
3. **The holdout is sacred.** A final test set is touched exactly once, at the very end,
   after everything else is frozen. If you look at it twice, it is burned and no longer a
   holdout.
4. **Count every hypothesis.** The Experiment Registry records *every* test, including the
   failures and the abandoned ideas. You cannot distinguish a real edge from luck without
   knowing how many shots you took.
5. **Net of costs or it doesn't exist.** Every edge claim is evaluated after realistic
   transaction costs, slippage, and capacity assumptions. A gross edge is not an edge.
6. **Falsify, don't confirm.** The job is to try to *kill* each hypothesis. An edge that
   survives a genuine attempt to destroy it is interesting; one that survives only gentle
   testing is noise.
7. **No protocol changes to rescue a result.** Once locked, the splits, metric, holdout,
   and hypothesis budget do not change to accommodate a result you like. Changing the rules
   after seeing data is the cardinal sin.

---

## 3. Data discipline (inherited from 4A–4F)

The edge phase runs *on top of* the existing PIT/provenance contract. It does not relax it.

- PIT-safe only: no feature may use information unavailable at decision time
  (`reference.available_at <= target.timestamp`; bars `available_at >= timestamp`).
- Purged + embargoed splits (already built) are mandatory — they prevent leakage across
  the train/test boundary from overlapping label horizons.
- No fillna / imputation / global scaling that leaks across the split boundary.
- **`.fit()` is forbidden until the first explicitly scoped modeling/preprocessing
  sprint, and then only inside a purged/walk-forward fold boundary** — fit on the
  training portion of a fold only and applied forward, never on the whole dataset, never
  outside a fold. The default state is *forbidden*; the exception is narrow and dated, so
  no agent may invoke it early on the grounds that the protocol "allows it later."
- Survivorship must be controlled by a real PIT universe (delisted included) before any
  edge claim is trusted. A synthetic-OK dataset (4F-0) validates the contract path only; it
  does **not** validate a real edge.

---

## 4. The split protocol (lock the geometry before any test)

Decide and freeze, in writing, before the first hypothesis:

- **Train / Validation / Test (Holdout) partition.** Time-ordered, never random across
  time. Purged and embargoed at each boundary.
- **Walk-forward vs single split.** Specify which, and the exact window sizes, before
  testing. Walk-forward is generally more honest for time series but multiplies the
  multiple-testing problem — account for it.
- **The Holdout date range is written down and sealed.** It is not loaded, inspected, or
  touched until the final single evaluation. Treat reading it early as a leakage incident
  to be logged, not hidden.
- **Embargo length** is justified explicitly by the longest label horizon, so no test-set
  information bleeds into training via overlapping forward returns.

---

## 5. The metric protocol (decide before, not after)

- **Primary metric:** one, chosen in advance (e.g. out-of-sample information coefficient,
  or Sharpe of a simple long/short portfolio formed from the signal, net of costs). Write
  down *which* and *why* before running.
- **Threshold for "interesting":** a pre-registered bar the result must clear to be worth a
  holdout shot. Set it before seeing anything.
- **Secondary / diagnostic metrics** are allowed for understanding, but cannot be
  retroactively promoted to primary because they looked better.
- **Cost model is part of the metric.** Specify the assumed transaction cost, slippage, and
  capacity before evaluating. Net, always.

---

## 6. The hypothesis budget and multiple-testing discipline (the heart of it)

This is the section that separates honest research from self-deception.

- **Declare a hypothesis budget in advance** — roughly how many independent hypotheses you
  intend to test in this research campaign. This is not a hard cap on curiosity; it is the
  denominator you must respect when interpreting any "winner."
- **Correct for multiple testing.** If you test N hypotheses, the best one will look good by
  chance even if all are worthless. Apply an explicit correction (Bonferroni as a blunt
  floor; ideally a deflated-Sharpe / multiple-testing-aware adjustment as in the AQR /
  Harvey-Liu literature). The Experiment Registry's count of *all* tests — including
  abandoned ones — feeds this correction. This is *why* the registry must exist before edge
  work begins.
- **No "just one more variation."** Tweaking a feature 40 ways and keeping the best is 40
  hypotheses, not one. The registry counts them all.
- **Pre-register families, not infinite freedom.** Decide the *families* of mechanical
  features you'll explore (e.g. price-derived returns over declared horizons, volume-based,
  cross-sectional rank of a declared quantity) before starting, so the search space is
  bounded and countable rather than an open-ended fishing expedition.

---

## 7. The holdout ritual (the single most important rule)

- The holdout is evaluated **once**, at the end, after the splits, metric, threshold,
  hypothesis budget, and final candidate are all frozen.
- You get **one** number from it. If the candidate clears the pre-registered threshold on
  the holdout *after* multiple-testing correction, it is interesting. If not, it is not an
  edge — and you do not get to go back, tweak, and re-test on the same holdout.
- Burning the holdout (looking early, or re-using it) means you need *new* unseen data
  before you can make any honest out-of-sample claim. Log it as an incident.

---

## 8. What counts as success in the edge phase

- **Success is an honest verdict, not a positive one.** "No tested hypothesis survives
  multiple-testing correction net of costs on the holdout" is a complete, valuable result.
- A *positive* result is only the beginning: a surviving edge then needs out-of-sample
  persistence over time, capacity analysis, and — before any real money — a live paper
  period and then small real-capital trading, for a long time, before the word "fund" is
  appropriate.
- The protocol explicitly protects you from the failure mode your working style invites:
  building beautiful, tractable infrastructure forever because it never says "no," while
  avoiding the intractable question — *do I have an edge?* — that can answer no. At some
  point you connect the model and accept that answer, whatever it is.

---

## 9. Build sequence (where this sits)

1. Finish 4F-1 (hardened-auditor re-diagnostic on real data) — in progress.
2. **4E — Experiment Registry.** Now defensible (a strict OK exists in synthetic). Required
   *before* edge work, because it is the denominator for multiple-testing correction.
   **The Experiment Registry can be built before real-data ingestion, but no edge
   hypothesis may be tested until real PIT/provenance ingestion is available.** Building the
   registry is neutral infrastructure; it does not open the edge-research gate. The gate is
   real contract-satisfying data, not the registry.
3. **This protocol — locked.** Splits, metric, threshold, hypothesis budget, holdout range
   all frozen in writing. (This document, ratified.)
4. **Real-data ingestion (Form B / 4F-2)** with a true PIT universe including delisted
   names from a non-Alpaca source — the network gate, decided separately.
5. **First baseline model** — the first sprint that computes real features and asks whether
   anything predicts out-of-sample, under all the rules above. This is the first time the
   word "edge" is allowed in code.

The edge is not *defined* in a build phase. It is *discovered — or not — in a test phase*,
and that test phase is the only part of this entire project whose success cannot be
promised, because no one can promise it. This document is what makes the test honest.

---

## 10. Boundary note

This document is a research-governance design only. It is not an alpha, signal, strategy,
model, trading recommendation, or execution component. It introduces no code and authorizes
none. It defines the conditions under which future edge research may proceed honestly.
