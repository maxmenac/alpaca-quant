"""Controlled real fetch for a small historical daily bars dataset."""

import json
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import ValidationError

from alpaca_quant.config import load_alpaca_config
from alpaca_quant.data.alpaca_bars import (
    HistoricalBarsClient,
    HistoricalBarsClientError,
    HistoricalBarsRequest,
    HTTPResponse,
    HTTPTransport,
)
from alpaca_quant.data.duckdb_query import available_symbols, count_bars, query_bars
from alpaca_quant.data.manifest import DataDeclaration
from alpaca_quant.data.parquet_writer import write_bars_parquet
from alpaca_quant.data.run_registry import (
    FetchRunRecord,
    append_fetch_run_record,
    create_fetch_run_id,
)

DEFAULT_SYMBOLS = ["AAPL", "MSFT"]
DEFAULT_START = "2024-01-02"
DEFAULT_END = "2024-01-08"
MAX_SYMBOLS = 5
MAX_CALENDAR_DAYS = 31
DEFAULT_MAX_PAGES = 5


class ControlledFetchError(RuntimeError):
    """Raised when a controlled historical fetch violates limits or verification."""


@dataclass(frozen=True)
class ControlledFetchResult:
    """Artifacts and verification summary from a controlled historical fetch."""

    output_dir: Path
    parquet_path: Path
    manifest_path: Path
    rows_written: int
    symbols: list[str]
    start: str
    end: str
    feed: str
    verification_passed: bool
    run_id: str
    registry_path: Path


class _UrllibResponse:
    def __init__(
        self,
        status_code: int,
        body: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = dict(headers or {})

    def json(self) -> Any:
        return json.loads(self._body)

    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")


class UrllibHTTPTransport:
    """Small standard-library transport for the Alpaca market data endpoint."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout_seconds = timeout_seconds

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str | int],
    ) -> HTTPResponse:
        request = Request(
            f"{url}?{urlencode(params)}",
            headers=dict(headers),
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                return _UrllibResponse(response.status, response.read(), response.headers)
        except HTTPError as exc:
            return _UrllibResponse(exc.code, exc.read(), exc.headers)
        except (URLError, TimeoutError, OSError) as exc:
            cause_type, hint = _transport_diagnostics(exc)
            raise HistoricalBarsClientError(
                "historical bars transport failed before receiving a response",
                cause_type=cause_type,
                hint=hint,
            ) from exc


def run_controlled_historical_fetch(
    output_dir: Path,
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    feed: str = "iex",
    limit: int = 1000,
    *,
    timeframe: str = "1Day",
    adjustment: str = "raw",
    max_pages: int = DEFAULT_MAX_PAGES,
    registry_path: Path | None = None,
    transport: HTTPTransport | None = None,
    environ: Mapping[str, str] | None = None,
) -> ControlledFetchResult:
    """Fetch, persist, and verify one tightly bounded historical bars dataset."""
    normalized_symbols = _normalize_symbols(DEFAULT_SYMBOLS if symbols is None else symbols)
    start_date = _parse_date(start or DEFAULT_START, "start")
    end_date = _parse_date(end or DEFAULT_END, "end")
    normalized_feed = feed.strip().lower()
    _validate_limits(
        symbols=normalized_symbols,
        start=start_date,
        end=end_date,
        feed=normalized_feed,
        timeframe=timeframe,
        max_pages=max_pages,
    )

    output_dir = Path(output_dir)
    parquet_path = output_dir / "historical_bars.parquet"
    manifest_path = output_dir / "data_declaration.yaml"
    _ensure_outputs_absent(parquet_path, manifest_path)

    config = load_alpaca_config(environ)
    try:
        bars_request = HistoricalBarsRequest(
            symbols=normalized_symbols,
            timeframe=timeframe,
            start=start_date,
            end=end_date,
            limit=limit,
            adjustment=adjustment,
            feed=normalized_feed,
        )
    except ValidationError as exc:
        raise ControlledFetchError("historical bars request is invalid") from exc

    client = HistoricalBarsClient(config, transport or UrllibHTTPTransport())
    bars = list(client.fetch_all(bars_request, max_pages=max_pages))
    if not bars:
        raise ControlledFetchError("controlled historical fetch returned no bars")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _build_manifest(normalized_symbols, start_date, end_date, normalized_feed)
    write_bars_parquet(bars, parquet_path)
    manifest_path.write_text(manifest.to_yaml(), encoding="utf-8")

    rows_written = count_bars(parquet_path)
    available = available_symbols(parquet_path)
    queried_rows = query_bars(parquet_path).height
    requested = set(normalized_symbols)
    checks = {
        "positive row count": rows_written > 0,
        "symbols subset": set(available).issubset(requested),
        "query row count": queried_rows == rows_written,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    if failed_checks:
        raise ControlledFetchError(
            f"controlled historical fetch verification failed: {', '.join(failed_checks)}"
        )

    created_at = datetime.now(UTC)
    run_id = create_fetch_run_id(created_at)
    resolved_registry_path = Path(registry_path or output_dir.parent / "fetch_registry.jsonl")
    record = FetchRunRecord(
        run_id=run_id,
        created_at=created_at,
        symbols=available,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        feed=normalized_feed,
        rows_written=rows_written,
        output_dir=str(output_dir),
        parquet_path=str(parquet_path),
        manifest_path=str(manifest_path),
        data_declaration_id=manifest.data_declaration_id,
        verification_passed=True,
        known_gaps=manifest.known_gaps,
        status="success",
    )
    append_fetch_run_record(
        resolved_registry_path,
        record,
        sensitive_values=(
            config.api_key_id.get_secret_value(),
            config.api_secret_key.get_secret_value(),
        ),
    )

    return ControlledFetchResult(
        output_dir=output_dir,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        rows_written=rows_written,
        symbols=available,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        feed=normalized_feed,
        verification_passed=True,
        run_id=run_id,
        registry_path=resolved_registry_path,
    )


def _normalize_symbols(symbols: list[str]) -> list[str]:
    normalized = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    if not normalized:
        raise ControlledFetchError("symbols must contain at least one symbol")
    return normalized


def _parse_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ControlledFetchError(f"{field_name} must be an ISO date") from exc


def _validate_limits(
    *,
    symbols: list[str],
    start: date,
    end: date,
    feed: str,
    timeframe: str,
    max_pages: int,
) -> None:
    if len(symbols) > MAX_SYMBOLS:
        raise ControlledFetchError(f"at most {MAX_SYMBOLS} symbols are allowed")
    if end < start:
        raise ControlledFetchError("end date must be on or after start date")
    if (end - start).days + 1 > MAX_CALENDAR_DAYS:
        raise ControlledFetchError(f"date range cannot exceed {MAX_CALENDAR_DAYS} calendar days")
    if timeframe != "1Day":
        raise ControlledFetchError("timeframe must be exactly 1Day")
    if feed == "sip-realtime":
        raise ControlledFetchError("sip-realtime is not allowed for controlled historical fetches")
    if feed not in {"iex", "sip-historical"}:
        raise ControlledFetchError("feed must be iex or sip-historical")
    if max_pages < 1 or max_pages > DEFAULT_MAX_PAGES:
        raise ControlledFetchError(f"max_pages must be between 1 and {DEFAULT_MAX_PAGES}")


def _ensure_outputs_absent(parquet_path: Path, manifest_path: Path) -> None:
    existing = [path for path in (parquet_path, manifest_path) if path.exists()]
    if existing:
        raise ControlledFetchError(f"output already exists: {existing[0]}")


def _build_manifest(
    symbols: list[str],
    start: date,
    end: date,
    feed: str,
) -> DataDeclaration:
    tier = 1 if feed == "sip-historical" else 0
    known_gaps = [
        "Alpaca does not provide delisted symbols; survivorship bias is not controlled",
        "corporate actions are best-effort and not point-in-time guaranteed",
    ]
    if feed == "iex":
        known_gaps.append("IEX covers only a subset of US market volume")

    return DataDeclaration(
        data_declaration_id=(
            f"dq-tier{tier}-alpaca-{feed}-{start.isoformat()}-{end.isoformat()}"
        ),
        tier=tier,
        universe_source="alpaca-requested-symbols",
        universe_id="-".join(symbols).lower(),
        survivorship_bias_status="partial",
        corporate_actions_status="partial",
        pit_status="best_effort",
        data_feed=feed,
        date_range=(start, end),
        known_gaps=known_gaps,
    )


def _transport_diagnostics(exc: BaseException) -> tuple[str, str | None]:
    causes: list[BaseException] = [exc]
    reason = getattr(exc, "reason", None)
    if isinstance(reason, BaseException):
        causes.append(reason)

    current = exc.__cause__ or exc.__context__
    while current is not None and current not in causes:
        causes.append(current)
        current = current.__cause__ or current.__context__

    for cause in causes:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return (
                "SSLCertVerificationError",
                "On macOS python.org installs, run Install Certificates.command",
            )
    for cause in causes:
        if isinstance(cause, TimeoutError):
            return "TimeoutError", None
    return type(exc).__name__, None
