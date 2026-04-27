"""
Regression tests for Session C5 (rebalance safety + sanity) and
Session C6 (Tier-2 profitability features).

C5:
- ``initialize_grid`` stamps ``last_rebalance_time`` so the first
  ``should_rebalance_hybrid`` call honours the cooldown.
- ``rebalance`` preserves filled BUYs (history) so realized / unrealized
  PnL stay correct after rebalance.
- ``_calculate_dynamic_multiplier`` thresholds are calibrated for hourly
  bars and trigger high-volatility on plausible hourly returns.
- ``_create_opposite_order`` no longer creates near-duplicate active
  levels at almost the same price.

C6:
- ``MLGridAdvisor`` exposes ``pause_trading=True`` for the ``extreme``
  volatility regime.
- ``execution.portfolio_protection.check_trailing_take_profit`` arms at
  the configured peak gain and triggers on the configured drawdown.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from strategies.grid import GridStrategy, GridConfig, GridLevel
from execution.portfolio_protection import (
    TrailingTPState,
    check_trailing_take_profit,
)


def _make_strategy(num_grids=4, lower=90.0, upper=110.0, current=100.0,
                   total_investment=100.0):
    s = GridStrategy("SOL/USDT")
    s.config = GridConfig(
        symbol="SOL/USDT",
        upper_price=upper,
        lower_price=lower,
        num_grids=num_grids,
        total_investment=total_investment,
    )
    s.center_price = current
    s.initialized = True
    s._create_grid_levels(current)
    return s


class TestCooldownOnInit:
    def test_initialize_grid_stamps_last_rebalance_time(self):
        s = GridStrategy("SOL/USDT")
        atr = 1.0
        # No data → multiplier defaults to 7.0; that's fine for the timer test.
        s.initialize_grid(current_price=100.0, atr=atr, total_investment=100.0)
        assert s.last_rebalance_time is not None

    def test_first_should_rebalance_hybrid_respects_cooldown(self):
        from config.settings import settings as _settings

        s = GridStrategy("SOL/USDT")
        s.initialize_grid(current_price=100.0, atr=1.0, total_investment=100.0)
        # Cooldown should still be active immediately after init.
        ok, reason = s.should_rebalance_hybrid(current_price=100.0)
        # If it's not "Cooldown" then we either passed the schedule, or the
        # bug is back. With default cooldown_minutes (30) we should still be
        # inside the cooldown right after init.
        assert _settings.grid.rebalance_cooldown_minutes > 0
        # Either the cooldown blocks us, or we are inside the next-rebalance
        # window — both are *not* the "FORCED / SCHEDULED / EMERGENCY"
        # branches that would have fired pre-fix.
        assert "Cooldown" in reason or "Next rebalance" in reason
        # Importantly, the function must not return True on the first tick.
        assert ok is False


class TestRebalancePreservesHistory:
    def test_rebalance_keeps_filled_levels_for_pnl(self):
        s = _make_strategy(num_grids=4, lower=90.0, upper=110.0, current=100.0)
        # Fill a BUY at $94 and have it produce a SELL at $94+spacing.
        buy = next(l for l in s.grid_levels if l.side == "buy")
        buy.filled = True
        buy.filled_at = datetime.utcnow()
        # Manually attach a paired SELL one spacing higher (we don't go
        # through ``_create_opposite_order`` here because the half-spacing
        # duplicate-detection tolerance correctly suppresses spawns that
        # collide with an existing nearby unfilled level).
        sell = GridLevel(
            price=buy.price + s.config.grid_spacing,
            side="sell",
            amount=buy.amount,
            level_id=s._new_level_id(),
            pair_id=buy.level_id,
        )
        s.grid_levels.append(sell)
        # Then fill that SELL.
        sell.filled = True
        sell.filled_at = datetime.utcnow() + timedelta(seconds=1)

        realized_before = s.calculate_realized_pnl()
        assert realized_before > 0  # closed cycle should be profitable

        # Now rebalance. Pre-fix: history wiped, realized PnL → 0.
        # Post-fix: history retained.
        s.rebalance(current_price=105.0, atr=1.0, reason="test")
        realized_after = s.calculate_realized_pnl()
        assert realized_after == pytest.approx(realized_before)

    def test_rebalance_carries_open_buy_into_unrealized(self):
        s = _make_strategy(num_grids=4, lower=90.0, upper=110.0, current=100.0)
        buy = next(l for l in s.grid_levels if l.side == "buy")
        buy.filled = True
        buy.filled_at = datetime.utcnow()
        # Don't create / fill the opposite SELL — BUY remains open.
        unreal_before = s.calculate_unrealized_pnl(current_price=105.0)
        assert unreal_before > 0

        s.rebalance(current_price=105.0, atr=1.0, reason="test")
        # Same MTM price, the open BUY should still contribute.
        unreal_after = s.calculate_unrealized_pnl(current_price=105.0)
        assert unreal_after == pytest.approx(unreal_before)


class TestDynamicMultiplierHourlyThresholds:
    def _make_data(self, hourly_sigma: float, n: int = 40, seed: int = 0):
        # Build close prices whose pct_change std equals roughly hourly_sigma.
        rng = np.random.default_rng(seed)
        rets = rng.normal(0, hourly_sigma, size=n)
        prices = 100.0 * np.cumprod(1 + rets)
        df = pd.DataFrame({
            "close": prices,
            "high": prices * 1.001,
            "low": prices * 0.999,
            "open": prices,
            "volume": np.full(n, 1.0),
        })
        return df

    def test_high_hourly_volatility_triggers_high_multiplier(self):
        s = GridStrategy("SOL/USDT")
        # Hourly std of ~2% — classic shock — should get the 10x branch.
        df = self._make_data(hourly_sigma=0.02, seed=1)
        m = s._calculate_dynamic_multiplier(df)
        assert m == 10.0

    def test_calm_hourly_volatility_uses_low_multiplier(self):
        s = GridStrategy("SOL/USDT")
        df = self._make_data(hourly_sigma=0.001, seed=2)
        m = s._calculate_dynamic_multiplier(df)
        assert m == 5.0


class TestOppositeOrderTolerance:
    def test_no_duplicate_when_existing_unfilled_level_is_close(self):
        # 4 grids in [90, 110]: spacing = 4. Levels at 94, 98, 102, 106.
        s = _make_strategy(num_grids=4, lower=90.0, upper=110.0, current=100.0)
        spacing = s.config.grid_spacing
        buy_94 = next(l for l in s.grid_levels if abs(l.price - 94.0) < 1e-6)
        buy_98 = next(l for l in s.grid_levels if abs(l.price - 98.0) < 1e-6)

        # Fill 94 → spawned SELL targets 94 + spacing == 98. The unfilled
        # SELL at 98 is exactly one spacing away, so the opposite-order
        # spawn should NOT add a duplicate (the new tolerance covers full
        # half-spacing exclusion radius).
        # We need an unfilled SELL at 98 first. Fill the BUY at 98 to
        # mutate its side via spawn — no, simpler: make level at 98 a SELL
        # by directly inserting.
        s.grid_levels.append(GridLevel(
            price=98.0, side="sell", amount=1.0, level_id=s._new_level_id()
        ))
        existing_count = len(s.grid_levels)

        buy_94.filled = True
        buy_94.filled_at = datetime.utcnow()
        s._create_opposite_order(buy_94)

        # The spawn at price 94 + spacing == 98 must collide with the
        # already-present unfilled SELL at 98 and be skipped.
        new_levels_added = len(s.grid_levels) - existing_count
        assert new_levels_added == 0


class TestExtremeRegimePause:
    def test_extreme_vol_sets_pause_trading(self):
        from strategies.ml_grid_advisor import MLGridAdvisor

        adv = MLGridAdvisor()
        # vol_ratio > 2.0 in features → "extreme" regime.
        vol = {
            'recent_vol': 0.04, 'medium_vol': 0.01, 'long_vol': 0.01,
            'atr_pct': 0.03, 'bb_width': 0.06, 'vol_ratio': 4.0,
            'vol_expansion': True, 'price_range_24h': 0.10,
        }
        trend = {
            'ema_ratio': 1.0, 'price_vs_ema20': 1.0, 'rsi': 50.0,
            'macd_hist': 0.0, 'macd_momentum': 0, 'trend_score': 0.0,
        }
        advice = adv._compute_grid_params(vol, trend, ml_confidence=0.5,
                                          ml_direction=0.0)
        assert advice.volatility_regime == "extreme"
        assert advice.pause_trading is True

    def test_normal_vol_does_not_pause(self):
        from strategies.ml_grid_advisor import MLGridAdvisor

        adv = MLGridAdvisor()
        vol = {
            'recent_vol': 0.01, 'medium_vol': 0.01, 'long_vol': 0.01,
            'atr_pct': 0.02, 'bb_width': 0.04, 'vol_ratio': 1.0,
            'vol_expansion': False, 'price_range_24h': 0.04,
        }
        trend = {
            'ema_ratio': 1.0, 'price_vs_ema20': 1.0, 'rsi': 50.0,
            'macd_hist': 0.0, 'macd_momentum': 0, 'trend_score': 0.0,
        }
        advice = adv._compute_grid_params(vol, trend, ml_confidence=0.5,
                                          ml_direction=0.0)
        assert advice.volatility_regime == "normal"
        assert advice.pause_trading is False


class TestTrailingPortfolioTP:
    def test_does_not_arm_below_threshold(self):
        state = TrailingTPState()
        # Peak only 5% above initial; arming threshold is 10%.
        triggered = check_trailing_take_profit(
            state=state, current_value=10_500.0, initial_balance=10_000.0,
            arm_percent=10.0, drawdown_percent=3.0,
        )
        assert not triggered
        assert state.peak_value == 10_500.0

    def test_arms_then_triggers_on_drawdown(self):
        state = TrailingTPState()
        # Climb to +20%
        check_trailing_take_profit(
            state=state, current_value=12_000.0, initial_balance=10_000.0,
            arm_percent=10.0, drawdown_percent=3.0,
        )
        assert state.peak_value == 12_000.0
        # Pullback < drawdown threshold → no trigger.
        out1 = check_trailing_take_profit(
            state=state, current_value=11_800.0, initial_balance=10_000.0,
            arm_percent=10.0, drawdown_percent=3.0,
        )
        assert not out1
        # Pullback > 3% from peak (12_000 * 0.97 = 11_640) → trigger.
        out2 = check_trailing_take_profit(
            state=state, current_value=11_600.0, initial_balance=10_000.0,
            arm_percent=10.0, drawdown_percent=3.0,
        )
        assert out2

    def test_zero_or_negative_balances_no_op(self):
        state = TrailingTPState()
        assert not check_trailing_take_profit(
            state=state, current_value=0.0, initial_balance=10_000.0,
            arm_percent=10.0, drawdown_percent=3.0,
        )
        assert not check_trailing_take_profit(
            state=state, current_value=10_000.0, initial_balance=0.0,
            arm_percent=10.0, drawdown_percent=3.0,
        )

    def test_peak_only_climbs(self):
        state = TrailingTPState()
        check_trailing_take_profit(
            state=state, current_value=12_000.0, initial_balance=10_000.0,
            arm_percent=10.0, drawdown_percent=3.0,
        )
        check_trailing_take_profit(
            state=state, current_value=11_500.0, initial_balance=10_000.0,
            arm_percent=10.0, drawdown_percent=3.0,
        )
        # Peak retained even if current value pulled back.
        assert state.peak_value == 12_000.0
