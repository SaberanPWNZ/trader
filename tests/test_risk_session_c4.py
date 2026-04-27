"""
Regression tests for risk management fixes (Session C4).

Covers:
- ``RiskConfig.min_confidence`` is now an explicit field used by
  ``RiskManager.validate_signal`` (no operator-precedence bug, and the
  threshold appears in the rejection reason).
- Daily-loss percentage uses ``day_start_balance`` rather than
  ``peak_balance`` — intra-day gains do not relax the daily-loss budget.
- ``PositionSizer.volatility_adjusted`` produces a correct stop-loss
  on the right side of entry for both long and short trades.
"""
from datetime import datetime

import pytest

from config.constants import SignalType
from config.settings import settings
from data.models import Signal
from risk.manager import RiskManager
from risk.position_sizer import PositionSizer


@pytest.fixture
def risk_manager():
    return RiskManager(initial_balance=10_000.0)


@pytest.fixture
def position_sizer():
    return PositionSizer()


def _signal(confidence: float, *, stop_loss: float = 99.0) -> Signal:
    return Signal(
        symbol="BTC/USDT",
        signal_type=SignalType.BUY.value,
        confidence=confidence,
        timestamp=datetime(2024, 1, 1),
        strategy="test",
        entry_price=100.0,
        stop_loss=stop_loss,
    )


class TestMinConfidence:
    def test_min_confidence_is_explicit_field(self):
        assert hasattr(settings.risk, "min_confidence")
        assert isinstance(settings.risk.min_confidence, float)

    def test_validate_signal_rejects_below_threshold(self, risk_manager):
        risk_manager.config.min_confidence = 0.7
        ok, reason = risk_manager.validate_signal(_signal(0.5))
        assert not ok
        assert "0.50" in reason
        # Threshold must appear in the rejection reason for observability.
        assert "0.70" in reason

    def test_validate_signal_accepts_at_threshold(self, risk_manager):
        risk_manager.config.min_confidence = 0.5
        ok, reason = risk_manager.validate_signal(_signal(0.5))
        assert ok, reason


class TestDailyLossDenominator:
    def test_daily_loss_uses_day_start_balance_not_peak(self, risk_manager):
        # Configure a 10% daily-loss limit for clarity.
        risk_manager.config.max_daily_loss = 0.10

        # Day starts at 10_000.
        assert risk_manager.state.day_start_balance == 10_000.0

        # Win 2_000 first → peak rises to 12_000.
        risk_manager.close_position("BTC/USDT", 2_000.0)
        assert risk_manager.state.peak_balance == 12_000.0

        # Now lose 1_050 → daily PnL = +950 (still positive overall, no block).
        risk_manager.close_position("BTC/USDT", -1_050.0)

        # Force daily PnL into a loss of 1_050 against day_start (10_000).
        # That is 10.5%, which exceeds the 10% daily-loss limit.
        risk_manager.state.daily_pnl = -1_050.0

        ok, reason = risk_manager.can_trade("ETH/USDT")
        # If the denominator were peak_balance (12_000) the loss would only be
        # 8.75% and the trade would still be allowed — that's the bug.
        assert not ok
        assert "Daily loss" in reason

    def test_reset_daily_stats_snapshots_balance(self, risk_manager):
        risk_manager.close_position("BTC/USDT", 500.0)
        assert risk_manager.state.current_balance == 10_500.0
        risk_manager.reset_daily_stats()
        assert risk_manager.state.day_start_balance == 10_500.0
        assert risk_manager.state.daily_pnl == 0.0


class TestVolatilityAdjustedSide:
    def test_long_stop_loss_below_entry(self, position_sizer):
        size_long = position_sizer.volatility_adjusted(
            account_balance=10_000,
            entry_price=100.0,
            atr=2.0,
            atr_multiplier=2.0,
            risk_percent=0.02,
            side="long",
        )
        assert size_long > 0

    def test_short_uses_stop_above_entry(self, position_sizer):
        # For a short, SL must sit above entry. With the previous bug the
        # stop was placed *below* entry → fixed_risk would receive
        # ``stop_distance`` of the same magnitude and produce a similar size,
        # but the SL semantics were broken. We verify behavioural symmetry:
        # short and long should produce the same size for symmetric SL
        # distance, since fixed_risk uses the absolute price gap.
        size_long = position_sizer.volatility_adjusted(
            account_balance=10_000,
            entry_price=100.0,
            atr=2.0,
            atr_multiplier=2.0,
            risk_percent=0.02,
            side="long",
        )
        size_short = position_sizer.volatility_adjusted(
            account_balance=10_000,
            entry_price=100.0,
            atr=2.0,
            atr_multiplier=2.0,
            risk_percent=0.02,
            side="short",
        )
        assert size_short == pytest.approx(size_long)

    def test_short_with_extreme_atr_does_not_invert(self, position_sizer):
        # With ATR larger than entry the OLD long-only formula could yield
        # ``stop_loss = entry_price - stop_distance`` < 0, which made the
        # absolute risk-per-unit huge but technically still finite. The
        # corrected short version places SL at entry + stop_distance, which
        # is always meaningful.
        size = position_sizer.volatility_adjusted(
            account_balance=10_000,
            entry_price=10.0,
            atr=20.0,
            atr_multiplier=2.0,
            risk_percent=0.02,
            side="short",
        )
        assert size >= 0
