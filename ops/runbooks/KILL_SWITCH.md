# Runbook — Kill Switch

> The kill switch is the system's top-priority safety control (SAFETY_POLICY.md invariant #8).
> Once triggered, **no new exposure-increasing order** is accepted until manual re-arm.

**Status: procedure placeholder (Sprint 0).** No live execution exists yet; this documents the
intended procedure.

## When to trigger

- Suspected runaway behavior, bad data, or any loss of confidence in the system.
- Reconciliation failure (see [RECONCILIATION_FAILURE.md](RECONCILIATION_FAILURE.md)).
- Broker/API anomaly (see [BROKER_OUTAGE.md](BROKER_OUTAGE.md)).

## Trigger

1. Set `kill_switch_armed: true` in `configs/app.yaml` (fail-closed default).
2. The risk gate refuses all exposure-increasing orders.
3. Reducing risk is still permitted: `reduce_only` / `close_only` / `rebalance_to_zero`
   (flatten) remain allowed — reducing risk never waits for a human.

## Re-arm (manual only)

1. Establish root cause and confirm it is resolved.
2. Confirm reconciliation is clean.
3. Manually re-arm. Re-arming is a deliberate human action — never automatic.
