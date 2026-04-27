"""Step D tests:

* Item 1 — per-symbol ``min_profit_threshold_percent`` overrides.
* Item 2 — recovery cooldown lift via consecutive wins.
* Item 3 — slippage-aware position sizing.
* Item 4 — per-symbol trailing TP overrides.
* Item 5 — daily digest cause-attribution section.
"""
from __future__ import annotations

import csv
import io
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from analytics.slippage import compute_slippage_size_factor
from config.settings import settings
from risk.manager import RiskManager
from risk.position_sizer import PositionSizer
from strategies.grid import GridConfig, GridStrategy


# --------------------------------------------------------------------------- #
# Item 1 — per-symbol min_profit_threshold_percent                            #
# --------------------------------------------------------------------------- #
class TestPerSymbolMinProfit:
    def test_default_falls_back_to_global(self):
        assert settings.grid.get_min_profit_threshold_percent("UNKNOWN/USDT") == \
            settings.grid.min_profit_threshold_percent

    def test_override_returned_for_known_symbol(self, monkeypatch):
        monkeypatch.setattr(
            settings.grid, "min_profit_threshold_percent_overrides",
            {"DOGE/USDT": 0.6, "BTC/USDT": 0.2},
        )
        assert settings.grid.get_min_profit_threshold_percent("DOGE/USDT") == \
            pytest.approx(0.6)
        assert settings.grid.get_min_profit_threshold_percent("BTC/USDT") == \
            pytest.approx(0.2)
        assert settings.grid.get_min_profit_threshold_percent("XRP/USDT") == \
            settings.grid.min_profit_threshold_percent

    def test_can_rebalance_uses_per_symbol_threshold(self, monkeypatch):
        # Total investment = $1000, override DOGE to 0.6% → needs >= $6 profit.
        monkeypatch.setattr(
            settings.grid, "min_profit_threshold_percent_overrides",
            {"DOGE/USDT": 0.6},
        )
        monkeypatch.setattr(settings.grid, "min_profit_threshold", 0.0)
        cfg = GridConfig(
            symbol="DOGE/USDT",
            lower_price=0.10,
            upper_price=0.20,
            num_grids=4,
            total_investment=1000.0,
        )
        strat = GridStrategy("DOGE/USDT", cfg)
        # Synthesize one filled BUY directly (skip initialize_grid, which
        # needs ATR + total_investment + a price-history feed we don't
        # bother stubbing here — this test targets only the threshold
        # branch in can_rebalance_positions_profitable).
        from strategies.grid import GridLevel
        strat.grid_levels = [
            GridLevel(price=0.15, side="buy", amount=100.0,
                      filled=True, level_id=1),
        ]
        # current_price=0.20 → unrealized = (0.20-0.15)*100 = $5 < $6.
        ok, _ = strat.can_rebalance_positions_profitable(0.20)
        assert ok is False
        # current_price=0.22 → unrealized = $7 > $6.
        ok, _ = strat.can_rebalance_positions_profitable(0.22)
        assert ok is True


# --------------------------------------------------------------------------- #
# Item 2 — recovery cooldown lift                                             #
# --------------------------------------------------------------------------- #
class TestRecoveryCooldownLift:
    def _trip_cooldown(self, rm: RiskManager) -> None:
        for _ in range(rm.config.max_consecutive_losses):
            rm.close_position("BTC/USDT", -1.0)
        assert rm.state.cooldown_until is not None

    def test_threshold_zero_disables_lift(self, monkeypatch):
        rm = RiskManager()
        monkeypatch.setattr(rm.config, "recovery_wins_to_lift_cooldown", 0)
        self._trip_cooldown(rm)
        # Many wins, but threshold=0 → cooldown stays.
        for _ in range(10):
            rm.close_position("BTC/USDT", 1.0)
        assert rm.state.cooldown_until is not None

    def test_lifts_after_threshold_wins(self, monkeypatch):
        rm = RiskManager()
        monkeypatch.setattr(rm.config, "recovery_wins_to_lift_cooldown", 3)
        self._trip_cooldown(rm)
        # Two wins not enough.
        rm.close_position("BTC/USDT", 1.0)
        rm.close_position("BTC/USDT", 1.0)
        assert rm.state.cooldown_until is not None
        # Third win → lift.
        rm.close_position("BTC/USDT", 1.0)
        assert rm.state.cooldown_until is None
        assert rm.state.consecutive_wins == 3

    def test_loss_resets_recovery_streak(self, monkeypatch):
        rm = RiskManager()
        monkeypatch.setattr(rm.config, "recovery_wins_to_lift_cooldown", 3)
        self._trip_cooldown(rm)
        rm.close_position("BTC/USDT", 1.0)
        rm.close_position("BTC/USDT", 1.0)
        rm.close_position("BTC/USDT", -1.0)  # Resets wins to 0.
        assert rm.state.consecutive_wins == 0
        # Now 3 wins from scratch.
        rm.close_position("BTC/USDT", 1.0)
        rm.close_position("BTC/USDT", 1.0)
        assert rm.state.cooldown_until is not None
        rm.close_position("BTC/USDT", 1.0)
        assert rm.state.cooldown_until is None

    def test_no_lift_when_cooldown_already_expired(self, monkeypatch):
        rm = RiskManager()
        monkeypatch.setattr(rm.config, "recovery_wins_to_lift_cooldown", 1)
        self._trip_cooldown(rm)
        # Force cooldown timestamp into the past — already expired, so
        # the lift path should leave it alone (it's harmless).
        rm.state.cooldown_until = datetime.utcnow() - timedelta(minutes=1)
        prev = rm.state.cooldown_until
        rm.close_position("BTC/USDT", 1.0)
        assert rm.state.cooldown_until == prev


# --------------------------------------------------------------------------- #
# Item 3 — slippage-aware position sizing                                     #
# --------------------------------------------------------------------------- #
class TestSlippageAwareSizing:
    def test_factor_returns_one_for_none_or_negative(self):
        assert compute_slippage_size_factor(None) == 1.0
        assert compute_slippage_size_factor(0.0) == 1.0
        assert compute_slippage_size_factor(-5.0) == 1.0

    def test_factor_decays_linearly(self):
        # max_bps=20, min_factor=0.5 → at 10bps factor=0.75.
        f = compute_slippage_size_factor(10.0, max_bps=20.0, min_factor=0.5)
        assert f == pytest.approx(0.75)
        # Beyond max_bps saturates at min_factor.
        assert compute_slippage_size_factor(
            100.0, max_bps=20.0, min_factor=0.5
        ) == pytest.approx(0.5)

    def test_factor_min_factor_clamped(self):
        # Negative min_factor clamped to 0.
        assert compute_slippage_size_factor(
            100.0, max_bps=20.0, min_factor=-0.5
        ) == pytest.approx(0.0)
        # >1 clamped to 1.
        assert compute_slippage_size_factor(
            100.0, max_bps=20.0, min_factor=2.0
        ) == pytest.approx(1.0)

    def test_position_sizer_disabled_no_op(self, monkeypatch):
        ps = PositionSizer()
        monkeypatch.setattr(ps.config, "slippage_size_adjust_enabled", False)
        sized = ps.slippage_adjusted(
            account_balance=10_000.0, entry_price=100.0, atr=2.0,
            slippage_ema_bps=50.0,
        )
        baseline = ps.volatility_adjusted(
            account_balance=10_000.0, entry_price=100.0, atr=2.0,
        )
        assert sized == pytest.approx(baseline)

    def test_position_sizer_enabled_scales_down(self, monkeypatch):
        ps = PositionSizer()
        monkeypatch.setattr(ps.config, "slippage_size_adjust_enabled", True)
        monkeypatch.setattr(ps.config, "slippage_size_max_bps", 20.0)
        monkeypatch.setattr(ps.config, "slippage_size_min_factor", 0.5)
        baseline = ps.volatility_adjusted(
            account_balance=10_000.0, entry_price=100.0, atr=2.0,
        )
        # 10bps adverse → factor=0.75
        sized = ps.slippage_adjusted(
            account_balance=10_000.0, entry_price=100.0, atr=2.0,
            slippage_ema_bps=10.0,
        )
        assert sized == pytest.approx(baseline * 0.75)


# --------------------------------------------------------------------------- #
# Item 4 — per-symbol trailing TP overrides                                   #
# --------------------------------------------------------------------------- #
class TestPerSymbolTrailingTP:
    def test_default_returns_global(self):
        arm, dd = settings.grid.get_trailing_tp_params(None)
        assert arm == settings.grid.trailing_portfolio_tp_arm_percent
        assert dd == settings.grid.trailing_portfolio_tp_drawdown_percent

    def test_unknown_symbol_returns_global(self, monkeypatch):
        monkeypatch.setattr(
            settings.grid, "trailing_portfolio_tp_overrides",
            {"BTC/USDT": {"arm_percent": 20.0, "drawdown_percent": 5.0}},
        )
        arm, dd = settings.grid.get_trailing_tp_params("ETH/USDT")
        assert arm == settings.grid.trailing_portfolio_tp_arm_percent
        assert dd == settings.grid.trailing_portfolio_tp_drawdown_percent

    def test_override_applied(self, monkeypatch):
        monkeypatch.setattr(
            settings.grid, "trailing_portfolio_tp_overrides",
            {"DOGE/USDT": {"arm_percent": 15.0, "drawdown_percent": 5.0}},
        )
        arm, dd = settings.grid.get_trailing_tp_params("DOGE/USDT")
        assert arm == 15.0
        assert dd == 5.0

    def test_partial_override_falls_back_per_field(self, monkeypatch):
        # Only arm_percent overridden — drawdown stays global.
        monkeypatch.setattr(
            settings.grid, "trailing_portfolio_tp_overrides",
            {"DOGE/USDT": {"arm_percent": 15.0}},
        )
        arm, dd = settings.grid.get_trailing_tp_params("DOGE/USDT")
        assert arm == 15.0
        assert dd == settings.grid.trailing_portfolio_tp_drawdown_percent


# --------------------------------------------------------------------------- #
# Item 5 — daily digest cause-attribution section                             #
# --------------------------------------------------------------------------- #
class TestDailyDigestCauseSection:
    def _write_live_csv(self, path, rows):
        header = [
            "timestamp", "symbol", "side", "price", "amount", "value",
            "order_id", "status", "fee", "trading_pnl", "holding_pnl",
            "realized_pnl", "balance", "total_value", "base_held",
            "expected_price", "cause",
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for r in rows:
                w.writerow([r.get(c, "") for c in header])

    def test_section_skipped_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import importlib
        import daily_profit_report as dpr
        importlib.reload(dpr)
        buf = io.StringIO()
        with redirect_stdout(buf):
            dpr.printCauseAttributionSection()
        assert buf.getvalue() == ""

    def test_section_renders_per_cause_breakdown(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import importlib
        import daily_profit_report as dpr
        importlib.reload(dpr)
        # Two trades on the same symbol with different causes.
        # Cumulative realized_pnl: 0 (BUY), 5 (SELL rebalance), 3 (SELL stop_loss)
        # → deltas: +5 rebalance, -2 stop_loss.
        rows = [
            {"timestamp": "2026-04-01T00:00:00", "symbol": "BTC/USDT",
             "side": "buy", "realized_pnl": "0", "cause": ""},
            {"timestamp": "2026-04-01T01:00:00", "symbol": "BTC/USDT",
             "side": "sell", "realized_pnl": "5", "cause": "rebalance"},
            {"timestamp": "2026-04-01T02:00:00", "symbol": "BTC/USDT",
             "side": "sell", "realized_pnl": "3", "cause": "stop_loss"},
        ]
        self._write_live_csv(tmp_path / "data" / "grid_live_trades.csv", rows)
        buf = io.StringIO()
        with redirect_stdout(buf):
            dpr.printCauseAttributionSection()
        out = buf.getvalue()
        assert "РЕАЛІЗОВАНИЙ PnL ЗА ПРИЧИНОЮ" in out
        assert "rebalance" in out
        assert "stop_loss" in out
