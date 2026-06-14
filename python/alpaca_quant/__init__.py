"""Alpaca Quant — research package.

Alpaca Quant recommends, Max approves. This package is the research / ML / backtest
environment. It produces target-weight signals and **never touches capital**; all
execution lives in the Go layer behind a risk gate (see docs/ARCHITECTURE.md).

Submodules are imported lazily by callers to keep this top-level import light and to
avoid pulling heavy data dependencies at import time.
"""

__version__ = "0.0.0"
