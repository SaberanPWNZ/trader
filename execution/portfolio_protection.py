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


# Mapping from MLGridAdvisor's ``volatility_regime`` strings to default
# cooldown scaling factors. Rationale:
#   - "extreme" (vol_ratio > 2.0): a fast-moving market may break out of
#     the grid range minutes after init; a 4× shorter cooldown lets us
#     re-center quickly. Combined with ``pause_trading`` this still
#     refuses to *place* orders during the shock — it only allows the
#     grid geometry to be redrawn.
#   - "high" (vol_ratio > 1.3): meaningful moves but not panic — halve.
#   - "normal": no change (use the configured cooldown).
#   - "low" (vol_ratio < 0.6): boring market — stretch the cooldown 1.5×
#     so small wiggles don't cause grid churn that just pays fees.
# Multipliers can be overridden per-deployment via the ``factors`` arg
# (see ``settings.grid.cooldown_factor_*``).
_DEFAULT_COOLDOWN_FACTORS: Dict[str, float] = {
    "extreme": 0.25,
    "high": 0.5,
    "normal": 1.0,
    "low": 1.5,
}


def compute_adaptive_cooldown(
    *,
    base_minutes: float,
    volatility_regime: Optional[str],
    factors: Optional[Dict[str, float]] = None,
    min_minutes: float = 1.0,
) -> float:
    """Scale the rebalance cooldown by the current volatility regime.

    Args:
        base_minutes: Configured cooldown (``settings.grid.rebalance_cooldown_minutes``).
        volatility_regime: One of ``"extreme"``, ``"high"``, ``"normal"``,
            ``"low"`` (or ``None``/unknown — falls back to ``base_minutes``).
        factors: Optional override for the regime → multiplier mapping.
            Missing regimes fall through to the default table; unknown
            regimes use multiplier ``1.0``.
        min_minutes: Lower bound applied after scaling so the cooldown
            never collapses to ~0 (protects against thrash on a single
            extreme regime classification).

    Returns:
        The scaled cooldown, in minutes, clamped to at least ``min_minutes``.
    """
    if base_minutes <= 0:
        return max(0.0, base_minutes)
    table = dict(_DEFAULT_COOLDOWN_FACTORS)
    if factors:
        table.update(factors)
    multiplier = table.get(volatility_regime or "", 1.0)
    if multiplier <= 0:
        multiplier = 1.0
    scaled = base_minutes * multiplier
    return max(min_minutes, scaled)


def compute_inventory_hedge(
    *,
    investment_per_symbol: float,
    num_buy_levels: int,
    num_sell_levels: int,
    current_base_value_usdt: float,
    max_hedge_fraction: float = 0.5,
) -> float:
    """USDT amount to market-buy at init to seed base inventory for SELLs.

    A grid's SELL legs need pre-existing base inventory; without it, the
    SELL side can't fill until enough BUYs round-trip into base. This
    helper computes a conservative one-time seed amount in USDT so the
    SELL side becomes immediately tradeable.

    Math:
        - ``usdt_per_buy = investment_per_symbol / num_buy_levels``
        - Total USDT-equivalent base needed for all SELLs (priced at
          their own grid prices) ≈ ``num_sell_levels * usdt_per_buy``
          (each SELL mirrors one BUY's notional). At grid construction we
          don't yet know the per-level prices, so we work in USDT.
        - Subtract whatever base inventory the account already holds
          (``current_base_value_usdt``) — no point double-buying.
        - Cap the hedge at ``max_hedge_fraction * investment_per_symbol``
          so we don't blow the per-symbol budget on the seed alone (the
          BUY legs still need USDT free).

    Args:
        investment_per_symbol: USDT budget allocated to this symbol
            (from ``compute_target_investment``).
        num_buy_levels: Number of BUY legs in the freshly-built grid.
        num_sell_levels: Number of SELL legs in the freshly-built grid.
        current_base_value_usdt: USDT-equivalent of base inventory the
            account already holds for this symbol (``free_base * price``).
        max_hedge_fraction: Upper bound on the seed as a fraction of
            ``investment_per_symbol`` (default ``0.5``).

    Returns:
        Non-negative USDT amount to spend on the seed market BUY. Zero
        when no hedge is needed (already fully stocked, no SELL legs, or
        budget is empty).
    """
    if investment_per_symbol <= 0 or num_sell_levels <= 0 or num_buy_levels <= 0:
        return 0.0

    usdt_per_buy = investment_per_symbol / num_buy_levels
    needed = num_sell_levels * usdt_per_buy
    deficit = needed - max(0.0, current_base_value_usdt)
    if deficit <= 0:
        return 0.0

    cap = max(0.0, max_hedge_fraction) * investment_per_symbol
    return min(deficit, cap)
