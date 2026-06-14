"""CLI: list computed feature sets in a local run directory.

Usage:
    python scripts/list_feature_sets.py --run alpaca_controlled_002
    python scripts/list_feature_sets.py --run-dir /abs/path/to/run

Output:
    Prints a summary table of all features_<SYMBOL>_manifest.yaml files found.

No Alpaca API calls. No .env reads. No network. No trading. No model training.
"""

import argparse
import sys
from pathlib import Path

import yaml  # type: ignore[import]

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data" / "runs"
sys.path.insert(0, str(REPO_ROOT / "python"))

MANIFEST_GLOB = "features_*_manifest.yaml"
REQUIRED_KEYS = {
    "feature_set_id",
    "symbol",
    "row_count",
    "date_range",
    "feature_names",
    "no_trading",
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


def summarize(run_dir: Path, manifest_path: Path) -> None:
    data = load_manifest(manifest_path)
    parquet_name = manifest_path.name.replace("_manifest.yaml", ".parquet")
    parquet_path = run_dir / parquet_name
    parquet_exists = "yes" if parquet_path.is_file() else "MISSING"

    dr = data.get("date_range", {})
    date_range = f"{dr.get('start', '?')} → {dr.get('end', '?')}"
    feature_count = len(data.get("feature_names", []))

    print(f"  feature_set_id : {data['feature_set_id']}")
    print(f"  symbol         : {data['symbol']}")
    print(f"  row_count      : {data['row_count']}")
    print(f"  date_range     : {date_range}")
    print(f"  features       : {feature_count}")
    print(f"  no_trading     : {data.get('no_trading')}")
    print(f"  parquet        : {parquet_name} ({parquet_exists})")
    print(f"  manifest       : {manifest_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List computed feature sets in a local run directory."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", help="Run directory name under data/runs/")
    group.add_argument("--run-dir", help="Absolute or relative path to run directory")
    args = parser.parse_args()

    if args.run:
        run_dir = DATA_ROOT / args.run
    else:
        run_dir = Path(args.run_dir)

    if not run_dir.is_dir():
        print(f"ERROR: run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    manifests = sorted(run_dir.glob(MANIFEST_GLOB))
    if not manifests:
        print(f"No feature sets found in {run_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Feature sets in {run_dir.name} ({len(manifests)} found):\n")
    errors: list[str] = []
    for i, manifest_path in enumerate(manifests, 1):
        print(f"[{i}]")
        try:
            summarize(run_dir, manifest_path)
        except ValueError as exc:
            errors.append(str(exc))
            print(f"  ERROR: {exc}")
        print()

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
