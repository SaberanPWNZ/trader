"""Execution slippage measurement helpers.

The backtest engine assumes a fixed ``slippage = 0.0005`` (5 bps), but
live fills on thin symbols can be 2-3× worse. This module owns the
math for offline slippage analysis. It is intentionally pure (no CSV /
exchange dependencies) so the live path can adopt it later without a
second source of truth.

Sign convention: positive = adverse (worse than expected), negative =
favourable (better than expected). Side-aware:

- ``BUY`` filled higher than expected → adverse → positive bps
- ``BUY`` filled lower than expected → favourable → negative bps
- ``SELL`` filled lower than expected → adverse → positive bps
- ``SELL`` filled higher than expected → favourable → negative bps
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Iterable, List, Optional


@dataclass
class SlippageStats:
    """Summary statistics for a batch of slippage measurements (bps)."""

    count: int = 0
    mean_bps: float = 0.0
    max_adverse_bps: float = 0.0
    max_favourable_bps: float = 0.0


def compute_slippage_bps(
    *,
    expected_price: float,
    actual_price: float,
    side: str,
) -> Optional[float]:
    """Return signed slippage in basis points (1 bp = 0.01%).

    Args:
        expected_price: The intended price (e.g. limit price, or
            mid-price snapshot at the moment the order was submitted).
        actual_price: The realised fill price reported by the exchange.
        side: ``"buy"`` or ``"sell"`` (case-insensitive).

    Returns:
        Signed bps (positive = adverse for the trader, negative =
        favourable). ``None`` if ``expected_price`` is non-positive
        (degenerate input — caller probably has corrupt data and
        should be told rather than silently fed a 0).
    """
    if expected_price <= 0:
        return None
    raw = (actual_price - expected_price) / expected_price
    side_lower = side.strip().lower() if isinstance(side, str) else ""
    if side_lower == "sell":
        # SELL adverse = filled lower than expected → raw is negative,
        # so flip the sign so adverse remains positive.
        raw = -raw
    # BUY: raw already positive when filled higher than expected = adverse.
    return raw * 10_000.0


def summarize_slippage(values_bps: Iterable[float]) -> SlippageStats:
    """Aggregate a batch of bps values into mean / max-adverse / max-favourable.

    Adverse and favourable extremes are reported as positive magnitudes
    so dashboard rendering doesn't have to wrangle signs. ``count`` is
    the number of *finite, non-None* inputs actually consumed.
    """
    finite: List[float] = [v for v in values_bps if v is not None]
    if not finite:
        return SlippageStats()
    return SlippageStats(
        count=len(finite),
        mean_bps=float(mean(finite)),
        max_adverse_bps=max(0.0, max(finite)),
        max_favourable_bps=max(0.0, -min(finite)),
    )
