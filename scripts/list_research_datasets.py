"""CLI: list research dataset manifests in a local directory.

Usage:
    python scripts/list_research_datasets.py --run alpaca_controlled_002
    python scripts/list_research_datasets.py --dir /abs/path/to/dir

Output:
    A non-secret summary of every research_dataset_*_manifest.yaml found.

No Alpaca API calls. No .env reads. No network. No trading. No backtesting. No model training.
"""

import argparse
import sys
from pathlib import Path

import yaml  # type: ignore[import]

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data" / "runs"

MANIFEST_GLOB = "research_dataset_*_manifest.yaml"
REQUIRED_KEYS = {
    "dataset_id",
    "symbols",
    "start",
    "end",
    "row_count",
    "feature_count",
    "created_at",
}


def load_manifest(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except Exception as exc:
        raise ValueError(f"cannot parse manifest {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"manifest {path.name} is not a mapping")
    missing = REQUIRED_KEYS - data.keys()
    if missing:
        raise ValueError(f"manifest {path.name} missing keys: {', '.join(sorted(missing))}")
    return data


def summarize(data: dict) -> None:
    symbols = data.get("symbols", [])
    symbols_str = ", ".join(symbols) if isinstance(symbols, list) else str(symbols)
    print(f"  dataset_id   : {data['dataset_id']}")
    print(f"  symbols      : {symbols_str}")
    print(f"  date_range   : {data.get('start')} → {data.get('end')}")
    if data.get("as_of"):
        print(f"  as_of        : {data['as_of']}")
    print(f"  row_count    : {data['row_count']}")
    print(f"  feature_count: {data['feature_count']}")
    print(f"  created_at   : {data['created_at']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="List local research dataset manifests.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", help="Run directory name under data/runs/")
    group.add_argument("--dir", help="Absolute or relative path to a directory")
    args = parser.parse_args()

    target_dir = DATA_ROOT / args.run if args.run else Path(args.dir)

    if not target_dir.is_dir():
        print(f"ERROR: directory not found: {target_dir}", file=sys.stderr)
        sys.exit(1)

    manifests = sorted(target_dir.glob(MANIFEST_GLOB))
    if not manifests:
        print(f"No research datasets found in {target_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Research datasets in {target_dir.name} ({len(manifests)} found):\n")
    errors: list[str] = []
    for i, manifest_path in enumerate(manifests, 1):
        print(f"[{i}]")
        try:
            summarize(load_manifest(manifest_path))
        except ValueError as exc:
            errors.append(str(exc))
            print(f"  ERROR: {exc}")
        print()

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
