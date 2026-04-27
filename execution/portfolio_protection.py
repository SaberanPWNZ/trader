"""
Pure helpers for portfolio-level protection logic (trailing TP, etc).

Kept free of I/O so unit tests can exercise the math without spinning up
a live trader.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional


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


@dataclass
class InvestmentBudget:
    """Mutable cache for the per-symbol investment budget.

    ``initial_pot`` is the total free USDT observed *the first time*
    ``compute_target_investment`` is called for any symbol. ``per_symbol``
    holds the resolved budget for each symbol so subsequent reinits reuse
    it verbatim.
    """

    initial_pot: Optional[float] = None
    per_symbol: Dict[str, float] = field(default_factory=dict)


def compute_target_investment(
    *,
    budget: "InvestmentBudget",
    symbol: str,
    usdt_free: float,
    investment_ratio: float,
    num_symbols: int,
) -> float:
    """Resolve the USDT budget for a single symbol.

    On the **very first call** (regardless of symbol) the function
    snapshots ``usdt_free`` into ``budget.initial_pot``; this is the
    portfolio's starting capital before *any* grid has locked USDT into
    orders. Per-symbol budgets are then derived from that pot:
    ``budget.initial_pot * investment_ratio / num_symbols``.

    On subsequent calls for the **same symbol** the cached value is
    returned. On first calls for *new* symbols, the previously-snapshotted
    ``initial_pot`` is reused (so all symbols receive an equal slice even
    when initialized sequentially after capital is locked).

    This avoids two production bugs:

    1. **Startup under-allocation.** When several grids initialize
       sequentially, each ``fetch_balance()`` returns the residual USDT
       *after* prior symbols have locked capital in BUY orders, so later
       symbols would receive progressively smaller slices.
    2. **Reinit shrinkage.** When one symbol reinitializes mid-life,
       most USDT is parked in other symbols' open BUY orders. Recomputing
       from the live ``usdt_free`` would silently shrink the grid every
       rebalance.

    The pot is only snapshotted once it is **positive**; if the very
    first call sees ``usdt_free <= 0`` the cache is left empty so the
    next funded call can establish the baseline.

    Args:
        budget: Mutable cache shared across all symbols.
        symbol: Trading pair to resolve.
        usdt_free: Currently free USDT (used only when no pot is cached).
        investment_ratio: Fraction of the pot to deploy across the
            portfolio (e.g. ``0.85``).
        num_symbols: Total number of symbols sharing the budget.

    Returns:
        The (possibly cached) USDT investment budget for ``symbol``.
    """
    cached = budget.per_symbol.get(symbol)
    if cached is not None and cached > 0:
        return cached

    n = max(1, num_symbols)
    ratio = max(0.0, investment_ratio)

    if budget.initial_pot is None or budget.initial_pot <= 0:
        # Establish the baseline from the first funded observation.
        if usdt_free > 0:
            budget.initial_pot = float(usdt_free)
        else:
            return 0.0

    per_symbol_budget = budget.initial_pot * ratio / n
    budget.per_symbol[symbol] = per_symbol_budget
    return per_symbol_budget
