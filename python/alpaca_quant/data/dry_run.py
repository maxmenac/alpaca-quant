"""Local end-to-end dry run for the mocked bar ingestion pipeline."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from alpaca_quant.data.alpaca_bars import Bar
from alpaca_quant.data.duckdb_query import available_symbols, count_bars, query_bars
from alpaca_quant.data.manifest import DataDeclaration
from alpaca_quant.data.parquet_writer import write_bars_parquet

EXPECTED_ROWS = 4
EXPECTED_SYMBOLS = ["AAPL", "MSFT"]


class DryRunError(RuntimeError):
    """Raised when the mocked local ingestion pipeline fails verification."""


@dataclass(frozen=True)
class DryRunResult:
    """Artifacts and verification summary from a successful dry run."""

    output_dir: Path
    parquet_path: Path
    manifest_path: Path
    rows_written: int
    symbols: list[str]
    verification_passed: bool


def run_mock_ingestion_dry_run(output_dir: Path) -> DryRunResult:
    """Run the manifest-to-Parquet-to-DuckDB pipeline with deterministic toy bars."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bars = _mock_bars()
    manifest = _mock_manifest()
    parquet_path = write_bars_parquet(bars, output_dir / "mock_bars.parquet")
    manifest_path = output_dir / "data_declaration.yaml"
    manifest_path.write_text(manifest.to_yaml(), encoding="utf-8")

    rows_written = count_bars(parquet_path)
    symbols = available_symbols(parquet_path)
    aapl_rows = query_bars(parquet_path, symbols=["AAPL"])
    second_day_rows = query_bars(parquet_path, start="2024-01-03", end=date(2024, 1, 3))

    checks = {
        "row count": rows_written == EXPECTED_ROWS,
        "symbols": symbols == EXPECTED_SYMBOLS,
        "selected symbol": aapl_rows.shape[0] == 2
        and aapl_rows["symbol"].unique().to_list() == ["AAPL"],
        "selected date range": second_day_rows.shape[0] == 2
        and second_day_rows["timestamp"].dt.date().unique().to_list() == [date(2024, 1, 3)],
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    if failed_checks:
        raise DryRunError(f"mock ingestion verification failed: {', '.join(failed_checks)}")

    return DryRunResult(
        output_dir=output_dir,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        rows_written=rows_written,
        symbols=symbols,
        verification_passed=True,
    )


def _mock_bars() -> list[Bar]:
    return [
        _bar("AAPL", 2, 185.5),
        _bar("MSFT", 2, 374.2),
        _bar("AAPL", 3, 186.1),
        _bar("MSFT", 3, 376.0),
    ]


def _bar(symbol: str, day: int, close: float) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=datetime(2024, 1, day, 5, tzinfo=UTC),
        open=close - 1.0,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
        volume=1_000_000 * day,
        trade_count=10_000 * day,
        vwap=close - 0.25,
    )


def _mock_manifest() -> DataDeclaration:
    return DataDeclaration(
        data_declaration_id="dq-tier0-mock-dry-run",
        tier=0,
        universe_source="local-mocked-bars",
        universe_id="mock-aapl-msft-v001",
        survivorship_bias_status="unknown",
        corporate_actions_status="none",
        pit_status="none",
        data_feed="iex",
        date_range=(date(2024, 1, 2), date(2024, 1, 3)),
        known_gaps=["synthetic toy data; not suitable for edge validation"],
    )
