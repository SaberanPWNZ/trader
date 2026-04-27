"""
Pure helpers for portfolio-level protection logic (trailing TP, etc).

Kept free of I/O so unit tests can exercise the math without spinning up
a live trader.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class TrailingTPState:
    """Mutable state required by ``check_trailing_take_profit``."""

    peak_value: float = 0.0


def check_trailing_take_profit(
    *,
    state: TrailingTPState,
    current_value: float,
    initial_balance: float,
    arm_percent: float,
    drawdown_percent: float,
) -> bool:
    """Return True when a trailing take-profit should fire.

    Tracks the high-water mark in ``state.peak_value``. The trail "arms"
    once the peak is at least ``arm_percent`` above ``initial_balance``;
    after that, the function returns True the first time
    ``current_value`` drops more than ``drawdown_percent`` below the peak.

    The function is a pure (state-mutating) helper — it does not raise on
    bad inputs; instead it gracefully no-ops when balances are zero/negative
    or thresholds are non-positive.

    Args:
        state: Mutable peak-tracking state. ``peak_value`` is updated
            in-place to ``max(peak_value, current_value)``.
        current_value: Latest portfolio total value.
        initial_balance: Reference balance used to decide when the trail
            arms. Use the trader's startup balance.
        arm_percent: Percentage gain (e.g. ``10.0`` for +10%) that the
            peak must reach above ``initial_balance`` before the trail can
            trigger.
        drawdown_percent: Percentage drop from the peak (e.g. ``3.0`` for
            -3%) that triggers the take-profit.

    Returns:
        True if the trailing take-profit has triggered. False otherwise.
    """
    if current_value <= 0 or initial_balance <= 0:
        return False
    if arm_percent <= 0 or drawdown_percent <= 0:
        return False

    if current_value > state.peak_value:
        state.peak_value = current_value

    arm_threshold = initial_balance * (1 + arm_percent / 100.0)
    if state.peak_value < arm_threshold:
        return False

    drop_pct = (state.peak_value - current_value) / state.peak_value * 100.0
    return drop_pct >= drawdown_percent
