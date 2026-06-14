"""Tests for the mockable Alpaca historical bars client."""

import json
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from alpaca_quant.config import AlpacaConfig
from alpaca_quant.data.alpaca_bars import (
    HistoricalBarsClient,
    HistoricalBarsClientError,
    HistoricalBarsRequest,
)


class FakeResponse:
    def __init__(
        self,
        payload: Any,
        status_code: int = 200,
        *,
        headers: dict[str, str] | None = None,
        body: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._body = body

    def json(self) -> Any:
        return self._payload

    def text(self) -> str:
        if self._body is not None:
            return self._body
        return json.dumps(self._payload)


class FakeTransport:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url, *, headers, params):  # noqa: ANN001
        self.calls.append({"url": url, "headers": headers, "params": params})
        return next(self._responses)


@pytest.fixture
def config() -> AlpacaConfig:
    return AlpacaConfig(
        api_key_id="test-key",
        api_secret_key="test-secret",
        data_url="https://data.example.test/",
        data_feed="iex",
    )


def request(**overrides) -> HistoricalBarsRequest:
    values = {
        "symbols": ["AAPL"],
        "start": date(2024, 1, 1),
        "end": date(2024, 1, 31),
    }
    values.update(overrides)
    return HistoricalBarsRequest(**values)


def bar_payload(timestamp: str = "2024-01-02T05:00:00Z") -> dict[str, Any]:
    return {
        "t": timestamp,
        "o": 1.0,
        "h": 2.0,
        "l": 0.5,
        "c": 1.5,
        "v": 1000,
        "n": 10,
        "vw": 1.2,
    }


def test_empty_symbols_rejected():
    with pytest.raises(ValidationError, match="at least one symbol"):
        request(symbols=[])


def test_lowercase_symbols_normalized():
    bars_request = request(symbols=["aapl", " msft "])

    assert bars_request.symbols == ("AAPL", "MSFT")


def test_non_daily_timeframe_rejected():
    with pytest.raises(ValidationError):
        request(timeframe="1Hour")


def test_invalid_date_range_rejected():
    with pytest.raises(ValidationError, match="end date"):
        request(start=date(2024, 2, 1), end=date(2024, 1, 1))


def test_first_page_params_and_headers(config):
    transport = FakeTransport([FakeResponse({"bars": {}, "next_page_token": None})])
    client = HistoricalBarsClient(config, transport)

    client.fetch_page(
        request(
            symbols=["aapl", "msft"],
            limit=500,
            adjustment="split",
        )
    )

    call = transport.calls[0]
    assert call["url"] == "https://data.example.test/v2/stocks/bars"
    assert call["params"] == {
        "symbols": "AAPL,MSFT",
        "timeframe": "1Day",
        "start": "2024-01-01",
        "end": "2024-01-31",
        "limit": 500,
        "adjustment": "split",
        "feed": "iex",
    }
    assert set(call["headers"]) == {"APCA-API-KEY-ID", "APCA-API-SECRET-KEY"}


def test_request_feed_overrides_config(config):
    transport = FakeTransport([FakeResponse({"bars": {}, "next_page_token": None})])

    HistoricalBarsClient(config, transport).fetch_page(request(feed="sip-historical"))

    assert transport.calls[0]["params"]["feed"] == "sip"


def test_sip_realtime_rejected_for_historical_bars(config):
    transport = FakeTransport([FakeResponse({"bars": {}, "next_page_token": None})])

    with pytest.raises(HistoricalBarsClientError, match="sip-realtime"):
        HistoricalBarsClient(config, transport).fetch_page(request(feed="sip-realtime"))


def test_parse_one_page_response(config):
    transport = FakeTransport(
        [FakeResponse({"bars": {"AAPL": [bar_payload()]}, "next_page_token": None})]
    )

    page = HistoricalBarsClient(config, transport).fetch_page(request())

    assert page.next_page_token is None
    assert len(page.bars) == 1
    bar = page.bars[0]
    assert bar.symbol == "AAPL"
    assert bar.timestamp.isoformat() == "2024-01-02T05:00:00+00:00"
    assert bar.open == 1.0
    assert bar.high == 2.0
    assert bar.low == 0.5
    assert bar.close == 1.5
    assert bar.volume == 1000
    assert bar.trade_count == 10
    assert bar.vwap == 1.2


def test_fetch_all_follows_next_page_token(config):
    transport = FakeTransport(
        [
            FakeResponse({"bars": {"AAPL": [bar_payload()]}, "next_page_token": "page-2"}),
            FakeResponse(
                {
                    "bars": {"AAPL": [bar_payload("2024-01-03T05:00:00Z")]},
                    "next_page_token": None,
                }
            ),
        ]
    )

    bars = list(HistoricalBarsClient(config, transport).fetch_all(request()))

    assert len(bars) == 2
    assert "page_token" not in transport.calls[0]["params"]
    assert transport.calls[1]["params"]["page_token"] == "page-2"


def test_max_pages_protects_against_endless_pagination(config):
    transport = FakeTransport(
        [
            FakeResponse({"bars": {}, "next_page_token": "repeat"}),
            FakeResponse({"bars": {}, "next_page_token": "repeat"}),
        ]
    )

    with pytest.raises(HistoricalBarsClientError, match="exceeded 2 pages"):
        list(HistoricalBarsClient(config, transport).fetch_all(request(), max_pages=2))

    assert len(transport.calls) == 2


def test_non_200_response_includes_safe_diagnostics(config):
    long_body = (
        '{"message":"unauthorized","key":"test-key","secret":"test-secret","detail":"'
        + "x" * 600
        + '"}'
    )
    transport = FakeTransport(
        [
            FakeResponse(
                {"message": "unauthorized"},
                status_code=401,
                headers={"X-Request-ID": "request-123"},
                body=long_body,
            )
        ]
    )

    with pytest.raises(HistoricalBarsClientError) as exc_info:
        HistoricalBarsClient(config, transport).fetch_page(request())

    error = exc_info.value
    rendered = str(error)
    assert error.status_code == 401
    assert error.request_id == "request-123"
    assert error.safe_body is not None
    assert error.safe_body.endswith("...")
    assert len(error.safe_body) == 503
    assert "status_code=401" in rendered
    assert "request_id=request-123" in rendered
    assert "safe_body=" in rendered
    assert "test-key" not in rendered
    assert "test-secret" not in rendered
    assert "[REDACTED]" in rendered


def test_malformed_response_raises_clear_error(config):
    transport = FakeTransport([FakeResponse({"bars": {"AAPL": [{"t": "missing fields"}]}})])

    with pytest.raises(HistoricalBarsClientError, match="response is malformed"):
        HistoricalBarsClient(config, transport).fetch_page(request())
