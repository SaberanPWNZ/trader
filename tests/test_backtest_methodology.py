"""
Regression tests for backtest methodology fixes (Session C3).

Covers:
- Stop-loss / take-profit fill prices model intra-bar gap behaviour
  (worst-of(open, level) for SL, best-of(open, level) for TP).
- Position-size fallback when ``signal.stop_loss`` is missing respects
  ``max_risk_per_trade`` instead of silently using 10% of equity.
- Sharpe / Sortino annualization uses the configured ``bars_per_year``.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backtesting.engine import BacktestEngine, BacktestTrade
from backtesting.metrics import PerformanceMetrics
from config.constants import SignalType
from data.models import Signal


class _DummyStrategy:
    name = "dummy"

    def __init__(self, signal_factory=None):
        self._signal_factory = signal_factory

    def calculate_features(self, data):
        return data

    def generate_signal(self, data):
        if self._signal_factory is not None:
            return self._signal_factory(data)
        return Signal(
            symbol="BTC/USDT",
            signal_type=SignalType.HOLD.value,
            confidence=0.0,
            timestamp=data.index[-1],
            strategy="dummy",
        )


def _make_bar(open_, high, low, close, ts=None):
    bar = pd.Series({"open": open_, "high": high, "low": low, "close": close})
    bar.name = ts or datetime(2024, 1, 1)
    return bar


def _make_engine():
    eng = BacktestEngine(
        strategy=_DummyStrategy(),
        initial_balance=10_000,
        fee_rate=0.0,
        slippage=0.0,
    )
    eng._reset()
    return eng


class TestStopLossGapFill:
    def test_long_sl_intrabar_no_gap_fills_at_sl(self):
        eng = _make_engine()
        eng._position = {
            "entry_time": datetime(2024, 1, 1),
            "symbol": "BTC/USDT",
            "side": "long",
            "entry_price": 100.0,
            "amount": 1.0,
            "stop_loss": 95.0,
            "take_profit": None,
            "fees": 0.0,
        }
        # open above SL, low touches SL, close back near open
        bar = _make_bar(open_=100.0, high=101.0, low=94.0, close=99.5)
        eng._close_position(bar, "Stop-loss", trigger_price=95.0)
        trade = eng._trades[-1]
        assert trade.exit_price == pytest.approx(95.0)
        assert trade.pnl == pytest.approx(-5.0)

    def test_long_sl_gap_down_fills_at_open(self):
        eng = _make_engine()
        eng._position = {
            "entry_time": datetime(2024, 1, 1),
            "symbol": "BTC/USDT",
            "side": "long",
            "entry_price": 100.0,
            "amount": 1.0,
            "stop_loss": 95.0,
            "take_profit": None,
            "fees": 0.0,
        }
        # gap-down: open already below SL → fill at the worse open
        bar = _make_bar(open_=90.0, high=92.0, low=89.0, close=91.0)
        eng._close_position(bar, "Stop-loss", trigger_price=95.0)
        trade = eng._trades[-1]
        assert trade.exit_price == pytest.approx(90.0)
        assert trade.pnl == pytest.approx(-10.0)

    def test_short_sl_gap_up_fills_at_open(self):
        eng = _make_engine()
        eng._position = {
            "entry_time": datetime(2024, 1, 1),
            "symbol": "BTC/USDT",
            "side": "short",
            "entry_price": 100.0,
            "amount": 1.0,
            "stop_loss": 105.0,
            "take_profit": None,
            "fees": 0.0,
        }
        bar = _make_bar(open_=110.0, high=111.0, low=109.0, close=109.5)
        eng._close_position(bar, "Stop-loss", trigger_price=105.0)
        trade = eng._trades[-1]
        assert trade.exit_price == pytest.approx(110.0)
        assert trade.pnl == pytest.approx(-10.0)

    def test_long_tp_gap_up_fills_at_open(self):
        eng = _make_engine()
        eng._position = {
            "entry_time": datetime(2024, 1, 1),
            "symbol": "BTC/USDT",
            "side": "long",
            "entry_price": 100.0,
            "amount": 1.0,
            "stop_loss": None,
            "take_profit": 105.0,
            "fees": 0.0,
        }
        bar = _make_bar(open_=110.0, high=112.0, low=109.0, close=109.5)
        eng._close_position(bar, "Take-profit", trigger_price=105.0)
        trade = eng._trades[-1]
        # Best of (open, TP) for long → open=110 (gap-up benefits us)
        assert trade.exit_price == pytest.approx(110.0)
        assert trade.pnl == pytest.approx(10.0)

    def test_long_tp_intrabar_fills_at_tp(self):
        eng = _make_engine()
        eng._position = {
            "entry_time": datetime(2024, 1, 1),
            "symbol": "BTC/USDT",
            "side": "long",
            "entry_price": 100.0,
            "amount": 1.0,
            "stop_loss": None,
            "take_profit": 105.0,
            "fees": 0.0,
        }
        # Open below TP, high reaches it, close drops back
        bar = _make_bar(open_=101.0, high=105.5, low=100.5, close=99.0)
        eng._close_position(bar, "Take-profit", trigger_price=105.0)
        trade = eng._trades[-1]
        assert trade.exit_price == pytest.approx(105.0)
        # The pre-fix close-based behaviour would have shown a LOSS here.
        assert trade.pnl == pytest.approx(5.0)

    def test_signal_reversal_still_uses_close(self):
        eng = _make_engine()
        eng._position = {
            "entry_time": datetime(2024, 1, 1),
            "symbol": "BTC/USDT",
            "side": "long",
            "entry_price": 100.0,
            "amount": 1.0,
            "stop_loss": 90.0,
            "take_profit": 110.0,
            "fees": 0.0,
        }
        bar = _make_bar(open_=101.0, high=103.0, low=100.5, close=102.0)
        eng._close_position(bar, "Signal reversal")
        trade = eng._trades[-1]
        assert trade.exit_price == pytest.approx(102.0)


class TestPositionSizingFallback:
    def test_missing_stop_loss_respects_max_risk_per_trade(self):
        eng = _make_engine()
        signal = Signal(
            symbol="BTC/USDT",
            signal_type=SignalType.BUY.value,
            confidence=0.9,
            timestamp=datetime(2024, 1, 1),
            strategy="dummy",
            stop_loss=None,
            take_profit=None,
        )
        bar = _make_bar(open_=100.0, high=101.0, low=99.0, close=100.0)
        eng._open_position(signal, bar, "BTC/USDT")

        max_risk = eng.risk_config.max_risk_per_trade
        max_position_size = eng.risk_config.max_position_size
        # Without slippage: notional == amount * entry_price.
        notional = eng._position["amount"] * eng._position["entry_price"]
        # Old behaviour was 10% of balance; new behaviour is bounded by
        # max_risk_per_trade (and additionally capped by max_position_size).
        cap = min(max_risk, max_position_size)
        assert notional <= eng.initial_balance * cap + 1e-6
        assert notional == pytest.approx(eng.initial_balance * cap, rel=1e-6)


class TestSharpeAnnualization:
    def _make_curve(self, n=500, freq_per_year=8760, sigma=0.01, seed=42):
        rng = np.random.default_rng(seed)
        rets = rng.normal(0.0, sigma, size=n)
        equity = 10_000 * np.cumprod(1 + rets)
        return pd.Series(equity)

    def test_hourly_sharpe_uses_8760_bars(self):
        equity = self._make_curve()
        trades = [
            BacktestTrade(
                entry_time=datetime(2024, 1, 1),
                exit_time=datetime(2024, 1, 2),
                symbol="BTC/USDT",
                side="long",
                entry_price=100.0,
                exit_price=101.0,
                amount=1.0,
                pnl=1.0,
            )
        ]
        m_hourly = PerformanceMetrics(
            trades, equity, 10_000, bars_per_year=24 * 365
        ).calculate_all()
        m_daily = PerformanceMetrics(
            trades, equity, 10_000, bars_per_year=365
        ).calculate_all()

        ratio = m_hourly["sharpe_ratio"] / m_daily["sharpe_ratio"]
        # Sharpe scales with sqrt(bars_per_year).
        assert ratio == pytest.approx(np.sqrt(24), rel=1e-6)

    def test_default_bars_per_year_is_365(self):
        equity = self._make_curve(seed=7)
        trades = [
            BacktestTrade(
                entry_time=datetime(2024, 1, 1),
                exit_time=datetime(2024, 1, 2),
                symbol="BTC/USDT",
                side="long",
                entry_price=100.0,
                exit_price=101.0,
                amount=1.0,
                pnl=1.0,
            )
        ]
        m_default = PerformanceMetrics(trades, equity, 10_000).calculate_all()
        m_explicit = PerformanceMetrics(
            trades, equity, 10_000, bars_per_year=365
        ).calculate_all()
        assert m_default["sharpe_ratio"] == pytest.approx(
            m_explicit["sharpe_ratio"]
        )
