# signals_out

Where the Python research pipeline **writes validated target-weight signals** for the Go
execution layer to consume. This is the producing side of the Python → Go boundary.

**Status: not implemented yet (Sprint 0).**

## Future behavior

- Serialize a signal conforming to [`docs/SIGNAL_CONTRACT.md`](../../../docs/SIGNAL_CONTRACT.md)
  (schema **v1.1.0**) and write it to `data/signals/latest_signal.json`.
- Signals carry **target weights**, never raw orders. Go transforms weights → orders behind
  the risk gate (see ADR-002).
- Every signal references its `backtest_run_id` (experiment registry) and
  `data_declaration_id` (proves the data tier), sets `mode`, `rebalance_type`,
  `approval_required`/`approval_status`, and a `valid_until` after which the signal is rejected.
- Python **never executes** and never reaches the broker (SAFETY_POLICY.md invariant #3).
