"""Tests for the tightly controlled real historical fetch pipeline."""

import ssl
from typing import Any
from urllib.error import URLError

import polars as pl
import pytest
import yaml

from alpaca_quant.config import ConfigError
from alpaca_quant.data.alpaca_bars import HistoricalBarsClientError
from alpaca_quant.data.real_fetch import (
    ControlledFetchError,
    UrllibHTTPTransport,
    run_controlled_historical_fetch,
)


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    def get(self, url, *, headers, params):  # noqa: ANN001
        self.calls.append({"url": url, "headers": headers, "params": params})
        return FakeResponse(self._payload)


def credentials() -> dict[str, str]:
    return {
        "ALPACA_API_KEY_ID": "test-key-never-print",
        "ALPACA_API_SECRET_KEY": "test-secret-never-print",
        "APCA_API_DATA_URL": "https://data.example.test",
        "ALPACA_DATA_FEED": "iex",
    }


def bars_payload() -> dict[str, Any]:
    return {
        "bars": {
            "AAPL": [
                {
                    "t": "2024-01-02T05:00:00Z",
                    "o": 185.0,
                    "h": 187.0,
                    "l": 184.0,
                    "c": 186.0,
                    "v": 1000,
                    "n": 10,
                    "vw": 185.5,
                }
            ],
            "MSFT": [
                {
                    "t": "2024-01-02T05:00:00Z",
                    "o": 374.0,
                    "h": 376.0,
                    "l": 373.0,
                    "c": 375.0,
                    "v": 2000,
                    "n": 20,
                    "vw": 374.8,
                }
            ],
        },
        "next_page_token": None,
    }


def test_default_scope_is_small_daily_aapl_msft(tmp_path):
    transport = FakeTransport(bars_payload())

    result = run_controlled_historical_fetch(
        tmp_path,
        transport=transport,
        environ=credentials(),
    )

    call = transport.calls[0]
    assert call["params"] == {
        "symbols": "AAPL,MSFT",
        "timeframe": "1Day",
        "start": "2024-01-02",
        "end": "2024-01-08",
        "limit": 1000,
        "adjustment": "raw",
        "feed": "iex",
    }
    assert result.start == "2024-01-02"
    assert result.end == "2024-01-08"
    assert result.feed == "iex"


def test_rejects_more_than_five_symbols(tmp_path):
    with pytest.raises(ControlledFetchError, match="at most 5 symbols"):
        run_controlled_historical_fetch(
            tmp_path,
            symbols=["A", "B", "C", "D", "E", "F"],
            transport=FakeTransport(bars_payload()),
            environ=credentials(),
        )


def test_rejects_explicitly_empty_symbols(tmp_path):
    with pytest.raises(ControlledFetchError, match="at least one symbol"):
        run_controlled_historical_fetch(
            tmp_path,
            symbols=[],
            transport=FakeTransport(bars_payload()),
            environ=credentials(),
        )


def test_rejects_date_range_longer_than_31_days(tmp_path):
    with pytest.raises(ControlledFetchError, match="31 calendar days"):
        run_controlled_historical_fetch(
            tmp_path,
            start="2024-01-01",
            end="2024-02-01",
            transport=FakeTransport(bars_payload()),
            environ=credentials(),
        )


def test_rejects_non_daily_timeframe(tmp_path):
    with pytest.raises(ControlledFetchError, match="exactly 1Day"):
        run_controlled_historical_fetch(
            tmp_path,
            timeframe="1Hour",
            transport=FakeTransport(bars_payload()),
            environ=credentials(),
        )


def test_rejects_sip_realtime(tmp_path):
    with pytest.raises(ControlledFetchError, match="sip-realtime"):
        run_controlled_historical_fetch(
            tmp_path,
            feed="sip-realtime",
            transport=FakeTransport(bars_payload()),
            environ=credentials(),
        )


def test_mocked_fetch_writes_and_verifies_artifacts(tmp_path):
    result = run_controlled_historical_fetch(
        tmp_path,
        transport=FakeTransport(bars_payload()),
        environ=credentials(),
    )

    assert result.parquet_path.is_file()
    assert result.manifest_path.is_file()
    assert result.rows_written == 2
    assert result.symbols == ["AAPL", "MSFT"]
    assert result.verification_passed is True
    assert pl.read_parquet(result.parquet_path).height == 2

    manifest = yaml.safe_load(result.manifest_path.read_text(encoding="utf-8"))
    declaration = manifest["data_declaration"]
    assert declaration["tier"] == 0
    assert declaration["data_feed"] == "iex"
    assert declaration["known_gaps"]


def test_sip_historical_maps_to_api_sip_and_tier_one(tmp_path):
    transport = FakeTransport(bars_payload())

    result = run_controlled_historical_fetch(
        tmp_path,
        feed="sip-historical",
        transport=transport,
        environ=credentials(),
    )

    assert transport.calls[0]["params"]["feed"] == "sip"
    assert result.feed == "sip-historical"
    manifest = yaml.safe_load(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["data_declaration"]["tier"] == 1


def test_missing_credentials_rejected_without_secret_leak(tmp_path, capsys):
    secret_value = "key-that-must-not-appear"

    with pytest.raises(ConfigError, match="ALPACA_API_SECRET_KEY is required") as exc_info:
        run_controlled_historical_fetch(
            tmp_path,
            transport=FakeTransport(bars_payload()),
            environ={"ALPACA_API_KEY_ID": secret_value},
        )

    captured = capsys.readouterr()
    rendered = f"{exc_info.value} {captured.out} {captured.err}"
    assert secret_value not in rendered


def test_ssl_certificate_failure_has_safe_helpful_diagnostics(monkeypatch):
    certificate_error = ssl.SSLCertVerificationError(
        1,
        "certificate verify failed: unable to get local issuer certificate",
    )

    def fail_urlopen(*args, **kwargs):  # noqa: ANN002, ANN003
        raise URLError(certificate_error)

    monkeypatch.setattr("alpaca_quant.data.real_fetch.urlopen", fail_urlopen)

    with pytest.raises(HistoricalBarsClientError) as exc_info:
        UrllibHTTPTransport().get(
            "https://data.example.test/v2/stocks/bars",
            headers={
                "APCA-API-KEY-ID": "key-must-not-leak",
                "APCA-API-SECRET-KEY": "secret-must-not-leak",
            },
            params={"symbols": "AAPL", "timeframe": "1Day"},
        )

    error = exc_info.value
    rendered = str(error)
    assert error.cause_type == "SSLCertVerificationError"
    assert "Install Certificates.command" in rendered
    assert "key-must-not-leak" not in rendered
    assert "secret-must-not-leak" not in rendered
