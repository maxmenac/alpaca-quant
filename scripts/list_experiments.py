"""Print a non-secret summary of all research experiments in the local JSONL registry.

No network. No Alpaca API calls. No .env reads. No secrets in output.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.research.experiment_registry import (  # noqa: E402
    ExperimentRegistryError,
    read_experiment_records,
)

DEFAULT_REGISTRY = Path("data/runs/experiment_registry.jsonl")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List research experiments from the local registry.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Path to the JSONL registry file (default: data/runs/experiment_registry.jsonl).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        records = read_experiment_records(args.registry)
    except ExperimentRegistryError as exc:
        print(f"Error reading registry: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("No experiments found.")
        return 0

    header = (
        f"{'run_id':<30}  {'created_at':<21}  {'git_sha':<10}  "
        f"{'dataset_id':<14}  {'feature_set_id':<22}  {'seed':>5}  "
        f"{'decision':<16}  decided_by"
    )
    print(header)
    print("-" * len(header))

    for rec in records:
        git_sha = (rec.git_sha or "-")[:8]
        dataset_id = rec.dataset_id or "-"
        feature_set_id = rec.feature_set_id or "-"
        seed = "-" if rec.seed is None else str(rec.seed)
        decided_by = rec.decided_by or "-"
        print(
            f"{rec.run_id:<30}  "
            f"{rec.created_at.strftime('%Y-%m-%dT%H:%M:%SZ'):<21}  "
            f"{git_sha:<10}  "
            f"{dataset_id:<14}  "
            f"{feature_set_id:<22}  "
            f"{seed:>5}  "
            f"{rec.decision:<16}  "
            f"{decided_by}"
        )

    print(f"\n{len(records)} experiment(s) total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
