"""CLI: inspect a local research dataset built from bars + computed features.

Usage:
    python scripts/inspect_research_dataset.py \
        --bars data/runs/alpaca_controlled_002/historical_bars.parquet \
        --features data/runs/alpaca_controlled_002/features_AAPL.parquet \
        --symbol AAPL

Multiple feature files and symbols are supported:
    python scripts/inspect_research_dataset.py \
        --bars data/runs/alpaca_controlled_002/historical_bars.parquet \
        --features features_AAPL.parquet features_MSFT.parquet \
        --symbol AAPL MSFT --as-of 2024-01-08 --write-manifest

Output (non-secret only):
    - rows
    - symbol(s)
    - date range
    - feature column count
    - per-feature null counts

No Alpaca API calls. No .env reads. No network. No trading. No backtesting. No model training.
"""

import argparse
import sys
from pathlib import Path

import yaml  # type: ignore[import]

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.research.dataset import (  # noqa: E402
    ResearchDatasetError,
    build_research_dataset_manifest,
    load_research_dataset,
    summarize_research_dataset,
)

MANIFEST_SUFFIX = "_manifest.yaml"
MANIFEST_PREFIX = "research_dataset_"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a local research dataset.")
    parser.add_argument("--bars", required=True, help="Path to bars Parquet file")
    parser.add_argument(
        "--features", required=True, nargs="+", help="One or more features Parquet files"
    )
    parser.add_argument("--symbol", default=None, nargs="+", help="Optional symbol filter(s)")
    parser.add_argument("--start", default=None, help="Optional ISO start date (inclusive)")
    parser.add_argument("--end", default=None, help="Optional ISO end date (inclusive)")
    parser.add_argument(
        "--as-of", default=None, help="Optional ISO as_of date (inclusive upper bound)"
    )
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Write a research dataset manifest next to the bars file (local, git-ignored)",
    )
    args = parser.parse_args()

    try:
        df = load_research_dataset(
            bars_path=args.bars,
            features_path=args.features,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            as_of=args.as_of,
        )
        summary = summarize_research_dataset(df)
    except ResearchDatasetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Research dataset:")
    print(f"  rows           : {summary.row_count}")
    print(f"  symbols        : {', '.join(summary.symbols)}")
    print(f"  date_range     : {summary.start} → {summary.end}")
    print(f"  feature columns: {summary.feature_column_count}")
    print("  null counts    :")
    for col, n in summary.null_counts.items():
        print(f"    {col:<24} {n}")

    if args.write_manifest:
        manifest = build_research_dataset_manifest(
            df, bars_path=args.bars, features_path=args.features, as_of=args.as_of
        )
        out_dir = Path(args.bars).resolve().parent
        out_path = out_dir / f"{MANIFEST_PREFIX}{manifest.dataset_id}{MANIFEST_SUFFIX}"
        out_path.write_text(yaml.dump(manifest.to_dict(), allow_unicode=True, sort_keys=False))
        print(f"\n  manifest       : {out_path}")
        print(f"  dataset_id     : {manifest.dataset_id}")


if __name__ == "__main__":
    main()
