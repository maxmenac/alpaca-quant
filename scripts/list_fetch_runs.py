"""Print a non-secret summary of all controlled fetch runs in the local JSONL registry."""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.data.run_registry import RunRegistryError, read_fetch_run_records  # noqa: E402

DEFAULT_REGISTRY = Path("data/runs/fetch_registry.jsonl")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List controlled historical fetch runs from the local registry.",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Path to the JSONL registry file (default: data/runs/fetch_registry.jsonl).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        records = read_fetch_run_records(args.registry)
    except RunRegistryError as exc:
        print(f"Error reading registry: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("No fetch runs found.")
        return 0

    header = (
        f"{'run_id':<42}  {'created_at':<25}  {'symbols':<12}  "
        f"{'date_range':<24}  {'feed':<14}  {'rows':>4}  {'verified':<8}  status"
    )
    print(header)
    print("-" * len(header))

    for rec in records:
        symbols_str = ",".join(rec.symbols)
        date_range = f"{rec.start} to {rec.end}"
        verified = "yes" if rec.verification_passed else "NO"
        print(
            f"{rec.run_id:<42}  "
            f"{rec.created_at.strftime('%Y-%m-%dT%H:%M:%SZ'):<25}  "
            f"{symbols_str:<12}  "
            f"{date_range:<24}  "
            f"{rec.feed:<14}  "
            f"{rec.rows_written:>4}  "
            f"{verified:<8}  "
            f"{rec.status}"
        )

    print(f"\n{len(records)} run(s) total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
