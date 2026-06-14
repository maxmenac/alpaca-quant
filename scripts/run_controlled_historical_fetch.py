"""Run one tightly bounded Alpaca historical daily bars fetch."""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.config import ConfigError  # noqa: E402
from alpaca_quant.data.alpaca_bars import HistoricalBarsClientError  # noqa: E402
from alpaca_quant.data.duckdb_query import DuckDBQueryError  # noqa: E402
from alpaca_quant.data.parquet_writer import ParquetWriteError  # noqa: E402
from alpaca_quant.data.real_fetch import (  # noqa: E402
    ControlledFetchError,
    run_controlled_historical_fetch,
)

DEFAULT_OUTPUT = Path("data/runs/alpaca_controlled_001")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a tightly bounded Alpaca historical daily bars dataset.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--symbols", default="AAPL,MSFT")
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2024-01-08")
    parser.add_argument("--feed", default="iex")
    parser.add_argument("--limit", type=int, default=1000)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    symbols = [symbol for symbol in args.symbols.split(",") if symbol.strip()]
    try:
        result = run_controlled_historical_fetch(
            output_dir=args.output,
            symbols=symbols,
            start=args.start,
            end=args.end,
            feed=args.feed,
            limit=args.limit,
        )
    except (
        ConfigError,
        ControlledFetchError,
        HistoricalBarsClientError,
        DuckDBQueryError,
        ParquetWriteError,
        OSError,
    ) as exc:
        print(f"Controlled historical fetch failed: {exc}", file=sys.stderr)
        return 1

    print("Controlled historical fetch passed")
    print(f"output_dir: {result.output_dir}")
    print(f"parquet_path: {result.parquet_path}")
    print(f"manifest_path: {result.manifest_path}")
    print(f"rows_written: {result.rows_written}")
    print(f"symbols: {', '.join(result.symbols)}")
    print(f"date_range: {result.start} to {result.end}")
    print(f"feed: {result.feed}")
    print(f"verification_passed: {result.verification_passed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
