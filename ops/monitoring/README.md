# Monitoring

Operational monitoring for Alpaca Quant.

**Status: placeholder (Sprint 0).** No real-time monitoring stack exists yet — and per
[`docs/ROADMAP.md`](../../docs/ROADMAP.md), Grafana/Prometheus/Timescale are **not** added
until they are earned (Phase 9). The MVP relies on structured logs and the experiment registry.

## What will live here (later)

- Decay monitoring (RESEARCH_PROTOCOL.md §4): rolling Sharpe vs validated baseline, alpha-level
  drawdown triggers, automatic demotion notifications (risk reduction, no approval needed).
- Reconciliation alerts: any positions/cash divergence vs the broker is a **blocking** alert
  (SAFETY_POLICY.md invariant #5).
- Kill-switch and risk-gate state visibility.

See the runbooks in [`../runbooks/`](../runbooks/) for the response procedures.
