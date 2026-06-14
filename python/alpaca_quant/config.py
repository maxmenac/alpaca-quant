"""Fail-closed Alpaca environment configuration."""

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
MARKET_DATA_URL = "https://data.alpaca.markets"
SUPPORTED_DATA_FEEDS = {"iex", "sip-historical", "sip-realtime"}


class ConfigError(ValueError):
    """Raised when required Alpaca configuration is missing or invalid."""


class AlpacaConfig(BaseModel):
    """Resolved research-only Alpaca configuration with redacted credentials."""

    model_config = ConfigDict(extra="forbid")

    api_key_id: SecretStr
    api_secret_key: SecretStr
    base_url: str = PAPER_BASE_URL
    data_url: str = MARKET_DATA_URL
    data_feed: Literal["iex", "sip-historical", "sip-realtime"] = "iex"
    mode: Literal["paper"] = "paper"

    def __repr__(self) -> str:
        return (
            "AlpacaConfig("
            f"base_url={self.base_url!r}, "
            f"data_url={self.data_url!r}, "
            f"data_feed={self.data_feed!r}, "
            f"mode={self.mode!r}, "
            "api_key_id='**********', "
            "api_secret_key='**********'"
            ")"
        )

    def __str__(self) -> str:
        return repr(self)


def load_alpaca_config(environ: Mapping[str, str] | None = None) -> AlpacaConfig:
    """Load Alpaca research configuration from environment variables."""
    env = os.environ if environ is None else environ

    api_key_id = env.get("ALPACA_API_KEY_ID", "").strip()
    if not api_key_id:
        raise ConfigError("ALPACA_API_KEY_ID is required")

    api_secret_key = env.get("ALPACA_API_SECRET_KEY", "").strip()
    if not api_secret_key:
        raise ConfigError("ALPACA_API_SECRET_KEY is required")

    data_feed = env.get("ALPACA_DATA_FEED", "iex").strip().lower()
    if data_feed not in SUPPORTED_DATA_FEEDS:
        supported = ", ".join(sorted(SUPPORTED_DATA_FEEDS))
        raise ConfigError(f"ALPACA_DATA_FEED must be one of: {supported}")

    return AlpacaConfig(
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        base_url=env.get("APCA_API_BASE_URL", PAPER_BASE_URL).strip() or PAPER_BASE_URL,
        data_url=env.get("APCA_API_DATA_URL", MARKET_DATA_URL).strip() or MARKET_DATA_URL,
        data_feed=data_feed,
    )
