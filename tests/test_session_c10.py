"""Regression tests for Session C10 — partial implementation of the
profit-increase plan.

Covers four pure additive helpers (no live-path wiring changes):
    * ``compute_adaptive_num_grids``  — execution/portfolio_protection.py
    * ``RiskManager.record_api_error`` / ``record_api_success`` — risk/manager.py
    * ``analytics.pnl_attribution.attribute_pnl``
    * ``analytics.slippage.compute_slippage_bps`` / ``summarize_slippage``
"""
from datetime import date, datetime

import pytest

from analytics.pnl_attribution import (
    CAUSE_REBALANCE,
    CAUSE_STOP_LOSS,
    CAUSE_TAKE_PROFIT,
    CAUSE_TRADE,
    attribute_pnl,
)
from analytics.slippage import compute_slippage_bps, summarize_slippage
from execution.portfolio_protection import compute_adaptive_num_grids
from risk.manager import RiskManager


# --------------------------------------------------------------------------- #
# Item 6 — adaptive num_grids                                                 #
# --------------------------------------------------------------------------- #
class TestComputeAdaptiveNumGrids:
    def test_extreme_regime_shrinks_to_lower_bound(self):
        # midpoint(8,10)=9, * 0.6 = 5.4 → rounds to 5, clamped up to 8.
        assert compute_adaptive_num_grids(
            min_grids=8, max_grids=10, volatility_regime="extreme",
        ) == 8

    def test_high_regime_pulls_below_midpoint(self):
        # midpoint(8,10)=9, * 0.8 = 7.2 → rounds to 7, clamped to 8.
        assert compute_adaptive_num_grids(
            min_grids=8, max_grids=10, volatility_regime="high",
        ) == 8

    def test_normal_regime_returns_midpoint(self):
        assert compute_adaptive_num_grids(
            min_grids=8, max_grids=10, volatility_regime="normal",
        ) == 9

    def test_low_regime_pushes_to_upper_bound(self):
        # midpoint(8,10)=9, * 1.25 = 11.25 → rounds to 11, clamped to 10.
        assert compute_adaptive_num_grids(
            min_grids=8, max_grids=10, volatility_regime="low",
        ) == 10

    def test_low_regime_with_wider_band_increases_density(self):
        # midpoint(4,20)=12, * 1.25 = 15.
        assert compute_adaptive_num_grids(
            min_grids=4, max_grids=20, volatility_regime="low",
        ) == 15

    def test_unknown_regime_returns_midpoint(self):
        assert compute_adaptive_num_grids(
            min_grids=8, max_grids=10, volatility_regime="weirdness",
        ) == 9

    def test_none_regime_returns_midpoint(self):
        assert compute_adaptive_num_grids(
            min_grids=8, max_grids=12, volatility_regime=None,
        ) == 10

    def test_factors_override_table(self):
        v = compute_adaptive_num_grids(
            min_grids=4, max_grids=20, volatility_regime="extreme",
            factors={"extreme": 0.25},
        )
        # midpoint=12, *0.25=3 → clamp to 4 (lo).
        assert v == 4

    def test_swapped_bounds_silently_corrected(self):
        # User passes (max=8, min=10) by mistake — must not crash.
        v = compute_adaptive_num_grids(
            min_grids=10, max_grids=8, volatility_regime="normal",
        )
        assert 8 <= v <= 10

    def test_degenerate_equal_bounds_returns_bound(self):
        assert compute_adaptive_num_grids(
            min_grids=10, max_grids=10, volatility_regime="extreme",
        ) == 10

    def test_zero_or_negative_multiplier_falls_back_to_one(self):
        # A misconfigured factor of 0 would zero out the grid; helper
        # treats it as "no scaling" rather than crashing the live path.
        v = compute_adaptive_num_grids(
            min_grids=8, max_grids=10, volatility_regime="extreme",
            factors={"extreme": 0.0},
        )
        assert v == 9  # midpoint, unscaled

    def test_clamps_to_minimum_one(self):
        # If both bounds are 0/negative, must still return >= 1.
        assert compute_adaptive_num_grids(
            min_grids=0, max_grids=0, volatility_regime="normal",
        ) >= 1


# --------------------------------------------------------------------------- #
# Item 12 — API-error kill-switch                                             #
# --------------------------------------------------------------------------- #
class TestApiErrorKillSwitch:
    def test_initial_counter_is_zero(self):
        rm = RiskManager(initial_balance=1000.0)
        assert rm.state.consecutive_api_errors == 0
        assert rm.state.kill_switch_active is False

    def test_record_api_error_increments_counter(self):
        rm = RiskManager(initial_balance=1000.0)
        rm.record_api_error("HTTP 500")
        rm.record_api_error("HTTP 503")
        assert rm.state.consecutive_api_errors == 2
        assert rm.state.kill_switch_active is False

    def test_record_api_success_resets_counter(self):
        rm = RiskManager(initial_balance=1000.0)
        rm.record_api_error("rate-limit")
        rm.record_api_error("rate-limit")
        rm.record_api_success()
        assert rm.state.consecutive_api_errors == 0

    def test_threshold_activates_kill_switch(self):
        rm = RiskManager(initial_balance=1000.0)
        rm.config.max_consecutive_api_errors = 3
        # Two errors: not yet.
        assert rm.record_api_error("x") is False
        assert rm.record_api_error("x") is False
        assert rm.state.kill_switch_active is False
        # Third trips it.
        assert rm.record_api_error("HTTP 503") is True
        assert rm.state.kill_switch_active is True

    def test_threshold_zero_disables_kill_switch_path(self):
        rm = RiskManager(initial_balance=1000.0)
        rm.config.max_consecutive_api_errors = 0
        for _ in range(50):
            rm.record_api_error("noise")
        assert rm.state.consecutive_api_errors == 50
        assert rm.state.kill_switch_active is False

    def test_kill_switch_does_not_double_fire(self):
        # Once the switch is active, further errors do NOT call
        # activate_kill_switch again (state already set, no duplicate
        # risk events).
        rm = RiskManager(initial_balance=1000.0)
        rm.config.max_consecutive_api_errors = 2
        rm.record_api_error("first")
        rm.record_api_error("trip")  # → activates
        assert rm.state.kill_switch_active is True
        # Subsequent error returns False because the switch is
        # already active.
        assert rm.record_api_error("after") is False

    def test_api_error_path_independent_of_consecutive_losses(self):
        rm = RiskManager(initial_balance=1000.0)
        # Bookkeeping the API counter must NOT touch the trade loss
        # counter (separate failure modes).
        for _ in range(5):
            rm.record_api_error("net")
        assert rm.state.consecutive_losses == 0


# --------------------------------------------------------------------------- #
# Item 10 — PnL attribution                                                   #
# --------------------------------------------------------------------------- #
class TestAttributePnl:
    def _row(self, ts, symbol, realized_pnl, **kwargs):
        row = {"timestamp": ts, "symbol": symbol, "realized_pnl": realized_pnl}
        row.update(kwargs)
        return row

    def test_groups_by_symbol_date_cause(self):
        # Cumulative realized_pnl per symbol — attribution should
        # difference within each symbol independently.
        rows = [
            self._row("2026-04-01T10:00:00", "BTC/USDT", 0.0),
            self._row("2026-04-01T11:00:00", "BTC/USDT", 5.0),
            self._row("2026-04-01T12:00:00", "BTC/USDT", 12.0),
            self._row("2026-04-01T10:30:00", "SOL/USDT", 0.0),
            self._row("2026-04-01T13:00:00", "SOL/USDT", -2.0),
        ]
        result = attribute_pnl(rows)
        per_symbol = result.by_symbol()
        assert per_symbol["BTC/USDT"] == pytest.approx(12.0)
        assert per_symbol["SOL/USDT"] == pytest.approx(-2.0)
        # All bucketed under the trade cause (no event tags supplied).
        assert set(result.by_cause().keys()) == {CAUSE_TRADE}

    def test_per_trade_mode_takes_field_directly(self):
        rows = [
            self._row("2026-04-01T10:00:00", "BTC/USDT", 5.0),
            self._row("2026-04-01T11:00:00", "BTC/USDT", 7.0),
        ]
        result = attribute_pnl(rows, cumulative=False)
        # 5 + 7 = 12, no differencing.
        assert result.by_symbol()["BTC/USDT"] == pytest.approx(12.0)

    def test_event_tag_routes_to_known_cause(self):
        rows = [
            self._row("2026-04-01T10:00:00", "BTC/USDT", 0.0),
            self._row("2026-04-01T11:00:00", "BTC/USDT", 10.0, event="rebalance"),
            self._row("2026-04-01T12:00:00", "BTC/USDT", 15.0, event="trade"),
            self._row("2026-04-02T10:00:00", "BTC/USDT", 5.0, event="portfolio_stop_loss"),
            self._row("2026-04-02T11:00:00", "BTC/USDT", 25.0, event="trailing_tp"),
        ]
        result = attribute_pnl(rows)
        per_cause = result.by_cause()
        assert per_cause[CAUSE_REBALANCE] == pytest.approx(10.0)
        assert per_cause[CAUSE_TRADE] == pytest.approx(5.0)  # 15 - 10
        # 5 - 15 = -10 (loss) attributed to stop loss
        assert per_cause[CAUSE_STOP_LOSS] == pytest.approx(-10.0)
        # 25 - 5 = 20 attributed to trailing TP
        assert per_cause[CAUSE_TAKE_PROFIT] == pytest.approx(20.0)

    def test_cause_field_takes_precedence_over_event(self):
        rows = [
            self._row("2026-04-01T10:00:00", "BTC/USDT", 0.0),
            self._row(
                "2026-04-01T11:00:00", "BTC/USDT", 8.0,
                cause="rebalance", event="trade",
            ),
        ]
        result = attribute_pnl(rows)
        assert CAUSE_REBALANCE in result.by_cause()
        assert CAUSE_TRADE not in result.by_cause()

    def test_unparseable_timestamp_skipped(self):
        rows = [
            self._row("not-a-date", "BTC/USDT", 0.0),
            self._row("2026-04-01T10:00:00", "BTC/USDT", 5.0),
        ]
        result = attribute_pnl(rows)
        # Only the second row contributes — but its delta is computed
        # against the *initial* state since the first was dropped.
        assert result.by_symbol()["BTC/USDT"] == pytest.approx(5.0)

    def test_accepts_datetime_instances(self):
        rows = [
            self._row(datetime(2026, 4, 1, 10), "BTC/USDT", 0.0),
            self._row(datetime(2026, 4, 1, 11), "BTC/USDT", 5.0),
        ]
        result = attribute_pnl(rows)
        assert result.by_date()[date(2026, 4, 1)] == pytest.approx(5.0)

    def test_zero_delta_trade_rows_skipped(self):
        # Carry-over snapshots (no realized PnL change, no event tag)
        # should not add empty buckets.
        rows = [
            self._row("2026-04-01T10:00:00", "BTC/USDT", 5.0),
            self._row("2026-04-01T11:00:00", "BTC/USDT", 5.0),
            self._row("2026-04-01T12:00:00", "BTC/USDT", 5.0),
        ]
        result = attribute_pnl(rows)
        # First row delta = 5 (vs 0). Subsequent rows: delta=0, no tag
        # → skipped. So exactly one bucket with 5.0.
        assert len(result.buckets) == 1
        assert result.buckets[0].realized_pnl == pytest.approx(5.0)
        assert result.buckets[0].trades == 1

    def test_zero_delta_with_event_tag_kept(self):
        # An event-tagged row with no PnL movement is still informative
        # (counts a rebalance even if it broke even).
        rows = [
            self._row("2026-04-01T10:00:00", "BTC/USDT", 5.0, event="rebalance"),
            self._row("2026-04-01T11:00:00", "BTC/USDT", 5.0, event="rebalance"),
        ]
        result = attribute_pnl(rows)
        # Both rows kept (one with delta=5, one with delta=0).
        assert len(result.buckets) == 1  # same (date, symbol, cause) merges
        assert result.buckets[0].trades == 2

    def test_multi_symbol_independent_running_totals(self):
        # Cumulative differencing is per-symbol — interleaved rows must
        # not pollute each other's running total.
        rows = [
            self._row("2026-04-01T10:00:00", "BTC/USDT", 100.0),
            self._row("2026-04-01T10:01:00", "SOL/USDT", 50.0),
            self._row("2026-04-01T10:02:00", "BTC/USDT", 110.0),
            self._row("2026-04-01T10:03:00", "SOL/USDT", 55.0),
        ]
        result = attribute_pnl(rows)
        per_symbol = result.by_symbol()
        # BTC: 100 (vs 0) + 10 (vs 100) = 110. SOL: 50 + 5 = 55.
        assert per_symbol["BTC/USDT"] == pytest.approx(110.0)
        assert per_symbol["SOL/USDT"] == pytest.approx(55.0)

    def test_buckets_sorted_stably(self):
        rows = [
            self._row("2026-04-02T10:00:00", "SOL/USDT", 1.0),
            self._row("2026-04-01T10:00:00", "BTC/USDT", 1.0),
            self._row("2026-04-01T10:00:00", "ETH/USDT", 1.0),
        ]
        result = attribute_pnl(rows)
        keys = [(b.date, b.symbol) for b in result.buckets]
        assert keys == sorted(keys)

    def test_empty_input_returns_empty_result(self):
        result = attribute_pnl([])
        assert result.buckets == []
        assert result.by_symbol() == {}
        assert result.by_cause() == {}
        assert result.by_date() == {}

    def test_missing_symbol_skipped(self):
        rows = [
            self._row("2026-04-01T10:00:00", "", 5.0),
            self._row("2026-04-01T10:00:00", None, 5.0),
        ]
        result = attribute_pnl(rows)
        assert result.buckets == []


# --------------------------------------------------------------------------- #
# Item 11 — slippage helper                                                   #
# --------------------------------------------------------------------------- #
class TestSlippage:
    def test_buy_filled_higher_is_adverse_positive_bps(self):
        # 100 → 100.10 = +10 bps adverse on a BUY.
        v = compute_slippage_bps(
            expected_price=100.0, actual_price=100.10, side="buy",
        )
        assert v == pytest.approx(10.0)

    def test_buy_filled_lower_is_favourable_negative_bps(self):
        v = compute_slippage_bps(
            expected_price=100.0, actual_price=99.90, side="buy",
        )
        assert v == pytest.approx(-10.0)

    def test_sell_filled_lower_is_adverse_positive_bps(self):
        v = compute_slippage_bps(
            expected_price=100.0, actual_price=99.90, side="sell",
        )
        assert v == pytest.approx(10.0)

    def test_sell_filled_higher_is_favourable_negative_bps(self):
        v = compute_slippage_bps(
            expected_price=100.0, actual_price=100.10, side="sell",
        )
        assert v == pytest.approx(-10.0)

    def test_case_insensitive_side(self):
        assert compute_slippage_bps(
            expected_price=100.0, actual_price=99.90, side="SELL",
        ) == pytest.approx(10.0)

    def test_zero_expected_price_returns_none(self):
        assert compute_slippage_bps(
            expected_price=0.0, actual_price=100.0, side="buy",
        ) is None

    def test_negative_expected_price_returns_none(self):
        assert compute_slippage_bps(
            expected_price=-1.0, actual_price=100.0, side="buy",
        ) is None

    def test_summarize_empty_returns_zero_stats(self):
        s = summarize_slippage([])
        assert s.count == 0
        assert s.mean_bps == 0.0
        assert s.max_adverse_bps == 0.0
        assert s.max_favourable_bps == 0.0

    def test_summarize_filters_none_entries(self):
        s = summarize_slippage([10.0, None, -5.0, None, 2.5])
        assert s.count == 3
        assert s.mean_bps == pytest.approx((10.0 - 5.0 + 2.5) / 3)
        assert s.max_adverse_bps == pytest.approx(10.0)
        assert s.max_favourable_bps == pytest.approx(5.0)

    def test_summarize_all_favourable_zero_adverse(self):
        s = summarize_slippage([-3.0, -2.0, -1.0])
        assert s.max_adverse_bps == 0.0
        assert s.max_favourable_bps == pytest.approx(3.0)

    def test_summarize_all_adverse_zero_favourable(self):
        s = summarize_slippage([3.0, 2.0, 1.0])
        assert s.max_favourable_bps == 0.0
        assert s.max_adverse_bps == pytest.approx(3.0)
