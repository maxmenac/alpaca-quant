"""Tests for fail-closed Alpaca environment configuration."""

import pytest

from alpaca_quant.config import (
    MARKET_DATA_URL,
    PAPER_BASE_URL,
    ConfigError,
    load_alpaca_config,
)


def test_valid_config_from_env():
    config = load_alpaca_config(
        {
            "ALPACA_API_KEY_ID": "test-key",
            "ALPACA_API_SECRET_KEY": "test-secret",
            "APCA_API_BASE_URL": "https://paper.example.test",
            "APCA_API_DATA_URL": "https://data.example.test",
            "ALPACA_DATA_FEED": "sip-historical",
        }
    )

    assert config.api_key_id.get_secret_value() == "test-key"
    assert config.api_secret_key.get_secret_value() == "test-secret"
    assert config.base_url == "https://paper.example.test"
    assert config.data_url == "https://data.example.test"
    assert config.data_feed == "sip-historical"
    assert config.mode == "paper"


def test_defaults_applied():
    config = load_alpaca_config(
        {
            "ALPACA_API_KEY_ID": "test-key",
            "ALPACA_API_SECRET_KEY": "test-secret",
        }
    )

    assert config.base_url == PAPER_BASE_URL
    assert config.data_url == MARKET_DATA_URL
    assert config.data_feed == "iex"
    assert config.mode == "paper"


def test_missing_key_rejected():
    with pytest.raises(ConfigError, match="ALPACA_API_KEY_ID is required"):
        load_alpaca_config({"ALPACA_API_SECRET_KEY": "test-secret"})


def test_missing_secret_rejected():
    with pytest.raises(ConfigError, match="ALPACA_API_SECRET_KEY is required"):
        load_alpaca_config({"ALPACA_API_KEY_ID": "test-key"})


def test_invalid_feed_rejected():
    with pytest.raises(ConfigError, match="ALPACA_DATA_FEED must be one of"):
        load_alpaca_config(
            {
                "ALPACA_API_KEY_ID": "test-key",
                "ALPACA_API_SECRET_KEY": "test-secret",
                "ALPACA_DATA_FEED": "invalid",
            }
        )


def test_repr_and_string_redact_secrets():
    config = load_alpaca_config(
        {
            "ALPACA_API_KEY_ID": "visible-key-must-not-leak",
            "ALPACA_API_SECRET_KEY": "visible-secret-must-not-leak",
        }
    )

    rendered = f"{config!r} {config}"
    assert "visible-key-must-not-leak" not in rendered
    assert "visible-secret-must-not-leak" not in rendered
    assert rendered.count("**********") == 4
