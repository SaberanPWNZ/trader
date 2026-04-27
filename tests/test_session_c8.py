"""
Regression tests for Session C8 — adaptive cooldown + inventory hedge.

Both helpers live in ``execution/portfolio_protection.py`` and are pure
math/lookup, so no live trader fixture is needed.
"""
import pytest

from execution.portfolio_protection import (
    compute_adaptive_cooldown,
    compute_inventory_hedge,
)


class TestComputeAdaptiveCooldown:
    def test_extreme_regime_shrinks_cooldown(self):
        assert compute_adaptive_cooldown(
            base_minutes=60, volatility_regime="extreme",
        ) == pytest.approx(15.0)  # 60 * 0.25

    def test_high_regime_halves_cooldown(self):
        assert compute_adaptive_cooldown(
            base_minutes=60, volatility_regime="high",
        ) == pytest.approx(30.0)

    def test_normal_regime_returns_base(self):
        assert compute_adaptive_cooldown(
            base_minutes=30, volatility_regime="normal",
        ) == pytest.approx(30.0)

    def test_low_regime_stretches_cooldown(self):
        assert compute_adaptive_cooldown(
            base_minutes=30, volatility_regime="low",
        ) == pytest.approx(45.0)  # 30 * 1.5

    def test_unknown_regime_returns_base(self):
        assert compute_adaptive_cooldown(
            base_minutes=30, volatility_regime="weirdness",
        ) == pytest.approx(30.0)

    def test_none_regime_returns_base(self):
        assert compute_adaptive_cooldown(
            base_minutes=30, volatility_regime=None,
        ) == pytest.approx(30.0)

    def test_factors_override_table(self):
        # Caller supplies aggressive overrides.
        v = compute_adaptive_cooldown(
            base_minutes=60, volatility_regime="extreme",
            factors={"extreme": 0.1, "high": 0.2},
        )
        assert v == pytest.approx(6.0)

    def test_min_minutes_floor_protects_against_thrash(self):
        v = compute_adaptive_cooldown(
            base_minutes=2, volatility_regime="extreme",  # -> 0.5
            min_minutes=1.0,
        )
        assert v == pytest.approx(1.0)

    def test_zero_base_returns_zero(self):
        assert compute_adaptive_cooldown(
            base_minutes=0, volatility_regime="extreme",
        ) == 0.0

    def test_negative_multiplier_falls_back_to_one(self):
        v = compute_adaptive_cooldown(
            base_minutes=30, volatility_regime="weird",
            factors={"weird": -1.0},
        )
        assert v == pytest.approx(30.0)


class TestComputeInventoryHedge:
    def test_basic_symmetric_grid(self):
        # 5 buys + 5 sells, $1000 budget, no existing inventory.
        # usdt_per_buy = 200; needed = 5 * 200 = $1000; cap = 0.5 * 1000 = $500.
        # → capped to $500.
        v = compute_inventory_hedge(
            investment_per_symbol=1000.0,
            num_buy_levels=5, num_sell_levels=5,
            current_base_value_usdt=0.0,
        )
        assert v == pytest.approx(500.0)

    def test_existing_inventory_reduces_hedge(self):
        # Same grid but $300 of base already held → deficit = 1000 - 300 = 700,
        # cap still 500 → capped.
        v = compute_inventory_hedge(
            investment_per_symbol=1000.0,
            num_buy_levels=5, num_sell_levels=5,
            current_base_value_usdt=300.0,
        )
        assert v == pytest.approx(500.0)

    def test_existing_inventory_above_need_returns_zero(self):
        v = compute_inventory_hedge(
            investment_per_symbol=1000.0,
            num_buy_levels=5, num_sell_levels=5,
            current_base_value_usdt=1500.0,
        )
        assert v == 0.0

    def test_no_sell_levels_returns_zero(self):
        v = compute_inventory_hedge(
            investment_per_symbol=1000.0,
            num_buy_levels=10, num_sell_levels=0,
            current_base_value_usdt=0.0,
        )
        assert v == 0.0

    def test_no_buy_levels_returns_zero(self):
        # Avoid div-by-zero when grid happens to be all SELLs.
        v = compute_inventory_hedge(
            investment_per_symbol=1000.0,
            num_buy_levels=0, num_sell_levels=5,
            current_base_value_usdt=0.0,
        )
        assert v == 0.0

    def test_zero_budget_returns_zero(self):
        v = compute_inventory_hedge(
            investment_per_symbol=0.0,
            num_buy_levels=5, num_sell_levels=5,
            current_base_value_usdt=0.0,
        )
        assert v == 0.0

    def test_asymmetric_grid_more_buys_than_sells(self):
        # Price near top → many BUYs, few SELLs.
        # usdt_per_buy = 1000/8 = 125; needed = 2 * 125 = 250; cap = 500.
        v = compute_inventory_hedge(
            investment_per_symbol=1000.0,
            num_buy_levels=8, num_sell_levels=2,
            current_base_value_usdt=0.0,
        )
        assert v == pytest.approx(250.0)

    def test_asymmetric_grid_more_sells_than_buys(self):
        # Price near bottom → few BUYs, many SELLs. Need a *lot* of base
        # to back the SELLs but cap protects the BUY budget.
        # usdt_per_buy = 1000/2 = 500; needed = 8 * 500 = 4000; cap = 500.
        v = compute_inventory_hedge(
            investment_per_symbol=1000.0,
            num_buy_levels=2, num_sell_levels=8,
            current_base_value_usdt=0.0,
        )
        assert v == pytest.approx(500.0)

    def test_custom_max_fraction(self):
        # 30% cap on a $1000 budget → at most $300 hedge.
        v = compute_inventory_hedge(
            investment_per_symbol=1000.0,
            num_buy_levels=5, num_sell_levels=5,
            current_base_value_usdt=0.0,
            max_hedge_fraction=0.3,
        )
        assert v == pytest.approx(300.0)

    def test_negative_max_fraction_clamped(self):
        v = compute_inventory_hedge(
            investment_per_symbol=1000.0,
            num_buy_levels=5, num_sell_levels=5,
            current_base_value_usdt=0.0,
            max_hedge_fraction=-0.5,
        )
        # cap clamped to 0 → no hedge
        assert v == 0.0
