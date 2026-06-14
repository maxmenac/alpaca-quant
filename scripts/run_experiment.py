"""CLI: run a backtest experiment on caller-provided weights and record it immutably.

Usage:
    python scripts/run_experiment.py \
        --bars data/runs/alpaca_controlled_002/historical_bars.parquet \
        --weights data/runs/alpaca_controlled_002/weights_AAPL.parquet \
        --as-of 2024-01-08 \
        --weight-source "caller: my_weights_v1"

Wires PIT read -> backtest engine -> null-model battery -> experiment registry + report.
`--as-of` is required (PIT, no lookahead). Weights are caller-provided (no strategy generated).

No Alpaca API calls. No .env reads. No network. No trading. No order logic. No model training.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.data.pit.reader import PITReadError  # noqa: E402
from alpaca_quant.research.experiment_registry import ExperimentRegistryError  # noqa: E402
from alpaca_quant.research.experiment_runner import (  # noqa: E402
    DEFAULT_REGISTRY,
    DEFAULT_REPORT_DIR,
    ExperimentRunError,
    run_backtest_experiment,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a backtest experiment and record it in the experiment registry."
    )
    parser.add_argument("--bars", required=True, help="Path to bars Parquet file")
    parser.add_argument("--weights", required=True, help="Path to caller-provided weights Parquet")
    parser.add_argument("--as-of", required=True, help="PIT knowledge cutoff (inclusive ISO date)")
    parser.add_argument(
        "--weight-source", required=True, help="Provenance label for the weights (no generation)"
    )
    parser.add_argument("--symbol", action="append", default=None, help="Optional symbol filter(s)")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument("--costs", default="configs/costs.yaml")
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--feature-set-id", default=None)
    parser.add_argument("--dataset-id", default=None)
    parser.add_argument("--decided-by", default=None)
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    try:
        result = run_backtest_experiment(
            bars_path=args.bars,
            weights_path=args.weights,
            as_of=args.as_of,
            weight_source=args.weight_source,
            seed=args.seed,
            horizon=args.horizon,
            symbols=args.symbol,
            costs_path=args.costs,
            registry_path=args.registry,
            report_dir=args.report_dir,
            feature_set_id=args.feature_set_id,
            dataset_id=args.dataset_id,
            decided_by=args.decided_by,
            notes=args.notes,
        )
    except (ExperimentRunError, PITReadError, ExperimentRegistryError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    rec = result.record
    m = result.backtest_result.metrics
    print(f"run_id              : {rec.run_id}")
    print(f"as_of               : {rec.as_of}")
    print(f"config_hash         : {rec.config_hash}")
    print(f"sharpe              : {m.sharpe:.4f}")
    print(f"total_return        : {m.total_return:.4f}")
    print(f"future_leak_detected: {result.battery_report.future_leak_detected}")
    print(f"report              : {result.report_paths.json_path}")
    print(f"registry            : {args.registry}")


if __name__ == "__main__":
    main()
