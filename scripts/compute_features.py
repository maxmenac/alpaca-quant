"""CLI: compute a point-in-time feature set for one symbol from a local controlled fetch run.

Usage:
    python scripts/compute_features.py --run alpaca_controlled_002 --symbol AAPL --as-of 2024-01-05

`--as-of` is required: features are built from bars known at that knowledge cutoff (no lookahead),
via the PIT read layer. This CLI never uses the legacy raw `build_feature_set` path.

Output:
    - Prints summary table of computed features.
    - Writes data/runs/<run>/features_<SYMBOL>.parquet  (local, not committed).
    - Writes data/runs/<run>/features_<SYMBOL>_manifest.yaml  (local, not committed).

No Alpaca API calls. No .env reads. No network. No trading. No model training.
"""

import argparse
import sys
from pathlib import Path

import yaml  # type: ignore[import]

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data" / "runs"
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.data.pit.reader import PITReadError  # noqa: E402
from alpaca_quant.features.pipeline import (  # noqa: E402
    build_feature_manifest,
    build_pit_feature_set,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute a point-in-time feature set from a local Parquet run."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", help="Run directory name under data/runs/")
    group.add_argument("--run-dir", help="Absolute or relative path to a run directory")
    parser.add_argument("--symbol", required=True, help="Symbol to compute features for")
    parser.add_argument(
        "--as-of",
        required=True,
        help="Knowledge cutoff (inclusive ISO date, e.g. 2024-01-05). No lookahead past this.",
    )
    args = parser.parse_args()

    run_dir = DATA_ROOT / args.run if args.run else Path(args.run_dir)
    parquet_path = run_dir / "historical_bars.parquet"

    if not parquet_path.is_file():
        print(f"ERROR: Parquet file not found: {parquet_path}", file=sys.stderr)
        sys.exit(1)

    symbol = args.symbol.strip().upper()
    print(f"Computing PIT features for {symbol} from {parquet_path} (as_of={args.as_of}) ...")

    try:
        df = build_pit_feature_set(parquet_path, symbol, as_of=args.as_of)
    except PITReadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    manifest = build_feature_manifest(parquet_path, symbol, df, as_of=args.as_of)

    out_parquet = run_dir / f"features_{symbol}.parquet"
    out_manifest = run_dir / f"features_{symbol}_manifest.yaml"

    df.write_parquet(out_parquet)
    out_manifest.write_text(yaml.dump(manifest, allow_unicode=True, sort_keys=False))

    print(f"\nfeature_set_id : {manifest['feature_set_id']}")
    print(f"as_of          : {manifest['as_of']}")
    print(f"rows           : {manifest['row_count']}")
    print(f"date_range     : {manifest['date_range']['start']} → {manifest['date_range']['end']}")
    print(f"output parquet : {out_parquet}")
    print(f"manifest       : {out_manifest}")
    print()
    print(df.select(["timestamp", "symbol", "close", "daily_return", "log_return"]))


if __name__ == "__main__":
    main()
