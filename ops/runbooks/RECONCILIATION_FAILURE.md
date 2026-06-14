# Runbook — Reconciliation Failure

> SAFETY_POLICY.md invariant #5: **never trade if broker reconciliation has failed.** A
> positions/cash desync is a stop, not a trade.

**Status: procedure placeholder (Sprint 0).** No live execution exists yet.

## Symptoms

- End-of-day positions/cash computed by the system diverge from the broker (Alpaca).
- Any unexplained quantity, cash, or position mismatch.

## Response

1. **Halt new trading immediately.** Trigger the [kill switch](KILL_SWITCH.md) — no
   exposure-increasing orders until resolved.
2. Snapshot both sides (system state and broker state) for the divergence investigation.
3. Identify the source: missed fill, partial fill, corporate action, manual broker change, or a
   bug. Corporate actions from Alpaca are best-effort (DATA_QUALITY.md), a common cause.
4. Reducing risk (`reduce_only` / flatten) remains allowed while investigating.
5. Resume only after reconciliation is clean and the root cause is understood. Re-arm the kill
   switch manually.
