"""Forward returns = EVALUATION OUTCOMES. NOT input features. NOT alpha labels.

These are realized *future* returns used only to score positions inside the backtester. They are
the dependent variable of evaluation, computed after the fact, and they live strictly on the
scoring side of the engine.

HARD RULE: forward returns must NEVER be fed into feature generation, joined into a research
dataset, or used as a model input. Doing so is lookahead — the exact self-deception this project
exists to prevent. The feature factory computes inputs from data known at/Before time t; this
module computes what happened *after* t, for scoring only.
"""

import polars as pl

SYMBOL_COL = "symbol"
TIMESTAMP_COL = "timestamp"


class OutcomeError(RuntimeError):
    """Raised when forward-return outcomes cannot be computed safely."""


def forward_returns(
    df: pl.DataFrame,
    *,
    horizon: int = 1,
    price_col: str = "close",
    out_col: str | None = None,
) -> pl.DataFrame:
    """Add a forward-return outcome column: (price[t+h] / price[t]) - 1, per symbol.

    - Sorted by (symbol, timestamp); uses `.over("symbol")` so symbols never bleed together.
    - The last `horizon` rows of each symbol are null: the future is unknown and is never
      fabricated. The backtester excludes these rows from PnL.
    - This is an *outcome*, not a feature. See module docstring.
    """
    if horizon < 1:
        raise OutcomeError("horizon must be at least 1")
    for required in (SYMBOL_COL, TIMESTAMP_COL, price_col):
        if required not in df.columns:
            raise OutcomeError(f"forward_returns requires column {required!r}")

    name = out_col or f"forward_return_{horizon}d"
    return df.sort([SYMBOL_COL, TIMESTAMP_COL]).with_columns(
        (
            (pl.col(price_col).shift(-horizon).over(SYMBOL_COL) / pl.col(price_col)) - 1.0
        ).alias(name)
    )
