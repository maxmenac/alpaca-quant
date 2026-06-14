"""Mockable client models for Alpaca historical daily stock bars."""

from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from alpaca_quant.config import AlpacaConfig


class HistoricalBarsClientError(RuntimeError):
    """Raised when an Alpaca bars request or response cannot be handled safely."""


class HistoricalBarsRequest(BaseModel):
    """Validated request for Alpaca's multi-symbol historical bars endpoint."""

    model_config = ConfigDict(extra="forbid")

    symbols: tuple[str, ...]
    timeframe: Literal["1Day"] = "1Day"
    start: date
    end: date
    limit: int = Field(default=1000, ge=1, le=10_000)
    adjustment: Literal["raw", "split", "dividend", "all"] = "raw"
    feed: Literal["iex", "sip-historical", "sip-realtime"] | None = None

    @field_validator("symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value: Sequence[str]) -> tuple[str, ...]:
        if isinstance(value, str):
            value = [value]
        symbols = tuple(symbol.strip().upper() for symbol in value if symbol.strip())
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        return symbols

    @model_validator(mode="after")
    def validate_date_range(self) -> "HistoricalBarsRequest":
        if self.end < self.start:
            raise ValueError("end date must be on or after start date")
        return self


class Bar(BaseModel):
    """Normalized historical stock bar."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_count: int
    vwap: float


class HistoricalBarsPage(BaseModel):
    """One normalized page from the historical bars endpoint."""

    model_config = ConfigDict(extra="forbid")

    bars: list[Bar]
    next_page_token: str | None = None


class HTTPResponse(Protocol):
    """Minimal response surface required from an injected HTTP transport."""

    status_code: int

    def json(self) -> Any: ...


class HTTPTransport(Protocol):
    """Minimal transport surface required by HistoricalBarsClient."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str | int],
    ) -> HTTPResponse: ...


class HistoricalBarsClient:
    """Build and parse historical daily bars requests using an injected transport."""

    def __init__(self, config: AlpacaConfig, transport: HTTPTransport) -> None:
        self._config = config
        self._transport = transport

    def fetch_page(
        self,
        request: HistoricalBarsRequest,
        page_token: str | None = None,
    ) -> HistoricalBarsPage:
        response = self._transport.get(
            f"{self._config.data_url.rstrip('/')}/v2/stocks/bars",
            headers=self._headers(),
            params=self._params(request, page_token),
        )
        if response.status_code != 200:
            raise HistoricalBarsClientError(
                f"historical bars request failed with status {response.status_code}"
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise HistoricalBarsClientError("historical bars response is not valid JSON") from exc

        return self._parse_page(payload)

    def fetch_all(
        self,
        request: HistoricalBarsRequest,
        *,
        max_pages: int = 100,
    ) -> Iterator[Bar]:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        page_token = None
        for _ in range(max_pages):
            page = self.fetch_page(request, page_token)
            yield from page.bars
            page_token = page.next_page_token
            if not page_token:
                return

        raise HistoricalBarsClientError(f"historical bars pagination exceeded {max_pages} pages")

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self._config.api_key_id.get_secret_value(),
            "APCA-API-SECRET-KEY": self._config.api_secret_key.get_secret_value(),
        }

    def _params(
        self,
        request: HistoricalBarsRequest,
        page_token: str | None,
    ) -> dict[str, str | int]:
        params: dict[str, str | int] = {
            "symbols": ",".join(request.symbols),
            "timeframe": request.timeframe,
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "limit": request.limit,
            "adjustment": request.adjustment,
            "feed": request.feed or self._config.data_feed,
        }
        if page_token:
            params["page_token"] = page_token
        return params

    @staticmethod
    def _parse_page(payload: Any) -> HistoricalBarsPage:
        if not isinstance(payload, dict):
            raise HistoricalBarsClientError("historical bars response must be an object")

        raw_bars = payload.get("bars")
        if not isinstance(raw_bars, dict):
            raise HistoricalBarsClientError("historical bars response must contain a bars object")

        bars: list[Bar] = []
        try:
            for symbol, symbol_bars in raw_bars.items():
                if not isinstance(symbol, str) or not isinstance(symbol_bars, list):
                    raise TypeError
                for raw_bar in symbol_bars:
                    if not isinstance(raw_bar, dict):
                        raise TypeError
                    bars.append(
                        Bar(
                            symbol=symbol.upper(),
                            timestamp=raw_bar["t"],
                            open=raw_bar["o"],
                            high=raw_bar["h"],
                            low=raw_bar["l"],
                            close=raw_bar["c"],
                            volume=raw_bar["v"],
                            trade_count=raw_bar["n"],
                            vwap=raw_bar["vw"],
                        )
                    )

            next_page_token = payload.get("next_page_token")
            if next_page_token is not None and not isinstance(next_page_token, str):
                raise TypeError
            return HistoricalBarsPage(bars=bars, next_page_token=next_page_token)
        except (KeyError, TypeError, ValidationError) as exc:
            raise HistoricalBarsClientError("historical bars response is malformed") from exc
