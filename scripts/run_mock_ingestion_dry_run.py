"""Run the local mocked ingestion pipeline from the repository checkout."""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from alpaca_quant.data.dry_run import DryRunError, run_mock_ingestion_dry_run  # noqa: E402
from alpaca_quant.data.duckdb_query import DuckDBQueryError  # noqa: E402
from alpaca_quant.data.parquet_writer import ParquetWriteError  # noqa: E402

DEFAULT_OUTPUT = Path("data/runs/mock_ingestion_dry_run")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local mocked bars ingestion dry run.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output directory (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_mock_ingestion_dry_run(args.output)
    except (DryRunError, DuckDBQueryError, ParquetWriteError, OSError) as exc:
        print(f"Mock ingestion dry run failed: {exc}", file=sys.stderr)
        return 1

    print("Mock ingestion dry run passed")
    print(f"output_dir: {result.output_dir}")
    print(f"parquet_path: {result.parquet_path}")
    print(f"manifest_path: {result.manifest_path}")
    print(f"rows_written: {result.rows_written}")
    print(f"symbols: {', '.join(result.symbols)}")
    print(f"verification_passed: {result.verification_passed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
