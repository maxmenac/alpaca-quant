"""Point-in-time / as-of layer: guarantees zero lookahead.

The only sanctioned way to read bars for feature computation. Features read through this layer,
never from raw Parquet directly (ARCHITECTURE.md P2 / §3.1).
"""

from alpaca_quant.data.pit.reader import (
    PITReadError,
    assert_no_lookahead,
    load_pit_bars,
)

__all__ = ["PITReadError", "assert_no_lookahead", "load_pit_bars"]
