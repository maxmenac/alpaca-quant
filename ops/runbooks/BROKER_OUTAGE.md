# Runbook — Broker / Alpaca API Outage

**Status: procedure placeholder (Sprint 0).** No live execution exists yet.

## Symptoms

- Alpaca REST/data endpoints time out, return 5xx, or rate-limit persistently.
- Order placement or status polling fails.

## Response

1. **Do not retry blindly.** Idempotency via `client_order_id` (= `signal_id` + symbol) prevents
   duplicate orders on retry (SIGNAL_CONTRACT.md §4), but during an outage stop submitting new
   exposure-increasing orders.
2. Treat order state as **unknown** until the API recovers. Never assume fill or no-fill.
3. If the outage overlaps open risk you want to reduce, reducing actions
   (`reduce_only` / `close_only` / flatten) are permitted once connectivity returns.
4. On recovery, reconcile before resuming (see [RECONCILIATION_FAILURE.md](RECONCILIATION_FAILURE.md)).
5. If in doubt, trigger the [kill switch](KILL_SWITCH.md).
