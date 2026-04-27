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


def compute_slippage_size_factor(
    slippage_ema_bps: Optional[float],
    *,
    max_bps: float = 30.0,
    min_factor: float = 0.5,
) -> float:
    """Return a multiplicative position-size factor in ``[min_factor, 1.0]``.

    When recent fills have shown adverse slippage, the trader is
    paying more on each round-trip and should size down. The factor
    decays linearly from ``1.0`` at zero adverse slippage to
    ``min_factor`` at ``max_bps``. Favourable (negative) or unknown
    slippage returns ``1.0``.

    Args:
        slippage_ema_bps: Recent adverse slippage exponential moving
            average in bps (positive = adverse). ``None`` or negative
            values return ``1.0``.
        max_bps: Adverse-slippage level at which the factor saturates
            to ``min_factor`` (e.g. ``30.0`` = 0.30%).
        min_factor: Floor for the factor (e.g. ``0.5`` halves position
            size in the worst case).

    Returns:
        A multiplier in ``[min_factor, 1.0]``.
    """
    if slippage_ema_bps is None or slippage_ema_bps <= 0:
        return 1.0
    if max_bps <= 0:
        return 1.0
    min_factor = max(0.0, min(min_factor, 1.0))
    ratio = min(1.0, slippage_ema_bps / max_bps)
    return 1.0 - ratio * (1.0 - min_factor)
