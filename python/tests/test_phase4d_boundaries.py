"""Phase 4D safety greps: the 4D source must contain no training/trading/leakage primitives."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE_4D_SOURCES = [
    REPO_ROOT / "python" / "alpaca_quant" / "research" / "feature_registry.py",
    REPO_ROOT / "python" / "alpaca_quant" / "research" / "dataset_report.py",
    REPO_ROOT / "python" / "alpaca_quant" / "research" / "dataset_manifest.py",
    REPO_ROOT / "python" / "alpaca_quant" / "research" / "ml_dataset.py",
    REPO_ROOT / "scripts" / "inspect_dataset.py",
]

# Patterns that must never appear in 4D code (model training / trading / leakage primitives).
FORBIDDEN_PATTERNS = [
    r"\.fit\(",
    r"\bStandardScaler\b",
    r"\bMinMaxScaler\b",
    r"\bsklearn\b",
    r"\bfillna\b",
    r"\.interpolate\(",
    r"\bcross_val\w*\(",
    r"\brequests\.",
    r"\burllib\b",
    r"\bsocket\b",
    r"\bos\.environ\b",
    r"\bdotenv\b",
    r"submit_order",
    r"place_order",
    r"alpaca_trade_api",
    # 4D-1 doctrine: detect timezones, never convert/normalize them.
    r"convert_time_zone",
    r"replace_time_zone",
    r"tz_convert",
    r"tz_localize",
]


@pytest.mark.parametrize("source", PHASE_4D_SOURCES, ids=lambda p: p.name)
def test_phase_4d_source_exists(source: Path) -> None:
    assert source.is_file(), f"missing 4D source: {source}"


@pytest.mark.parametrize("source", PHASE_4D_SOURCES, ids=lambda p: p.name)
@pytest.mark.parametrize("pattern", FORBIDDEN_PATTERNS)
def test_phase_4d_source_has_no_forbidden_pattern(source: Path, pattern: str) -> None:
    text = source.read_text()
    assert re.search(pattern, text) is None, f"{pattern!r} found in {source.name}"


def test_phase_4d_modules_do_not_import_network_or_alpaca() -> None:
    for source in PHASE_4D_SOURCES:
        text = source.read_text()
        assert "import requests" not in text
        assert "alpaca" not in text.lower() or "alpaca_quant" in text
