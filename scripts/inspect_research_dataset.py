"""CLI: inspect a local research dataset built from bars + computed features.

Usage:
    python scripts/inspect_research_dataset.py \
        --bars data/runs/alpaca_controlled_002/historical_bars.parquet \
        --features data/runs/alpaca_controlled_002/features_AAPL.parquet \
        --symbol AAPL

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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.research.dataset import (  # noqa: E402
    ResearchDatasetError,
    load_research_dataset,
    summarize_research_dataset,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a local research dataset.")
    parser.add_argument("--bars", required=True, help="Path to bars Parquet file")
    parser.add_argument("--features", required=True, help="Path to features Parquet file")
    parser.add_argument("--symbol", default=None, help="Optional symbol filter")
    parser.add_argument("--start", default=None, help="Optional ISO start date (inclusive)")
    parser.add_argument("--end", default=None, help="Optional ISO end date (inclusive)")
    args = parser.parse_args()

    try:
        df = load_research_dataset(
            bars_path=args.bars,
            features_path=args.features,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
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


if __name__ == "__main__":
    main()
