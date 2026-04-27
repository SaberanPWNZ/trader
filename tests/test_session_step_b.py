"""Regression tests for the live-path wiring delivered in Step B
(alongside the Session C10 pure helpers):

* ``ExchangeApiGuard`` — execution/exchange_guard.py
* ``RiskConfig.portfolio_stop_loss_pct`` / ``portfolio_emergency_stop_pct``
* ``GridConfig.min_profit_threshold_percent`` default

These all sit at the boundary between the live trader and the existing
pure helpers — the helpers have full coverage in
``test_session_c10.py``, so we only test the wiring here.
"""
from __future__ import annotations

from typing import List

import pytest

from config.settings import settings
from execution.exchange_guard import ExchangeApiGuard
from risk.manager import RiskManager


class _FakeExchange:
    """Stand-in for ExchangeClient: minimal async API surface."""

    def __init__(self) -> None:
        self.calls: List[str] = []
        self.fail_next: int = 0
        self.markets = {"BTC/USDT": {}}

    async def fetch_ticker(self, symbol):
        self.calls.append(f"ticker:{symbol}")
        if self.fail_next > 0:
            self.fail_next -= 1
            raise RuntimeError("boom")
        return {"last": 100.0}

    async def fetch_balance(self):
        self.calls.append("balance")
        if self.fail_next > 0:
            self.fail_next -= 1
            raise RuntimeError("balance failed")
        return {"USDT": {"free": 1000.0, "total": 1000.0}}

    async def create_order(self, **kwargs):
        self.calls.append(f"order:{kwargs.get('side')}")
        if self.fail_next > 0:
            self.fail_next -= 1
            raise RuntimeError("order rejected")
        return {"id": "1", "status": "open"}

    # Non-API attribute — must NOT be intercepted.
    def some_local_helper(self):
        return "local"


def _make_rm(threshold: int = 3) -> RiskManager:
    rm = RiskManager()
    rm.config.max_consecutive_api_errors = threshold
    rm.config.kill_switch_enabled = True
    return rm


# --------------------------------------------------------------------------- #
# Item 1 — ExchangeApiGuard                                                   #
# --------------------------------------------------------------------------- #
class TestExchangeApiGuard:
    @pytest.mark.asyncio
    async def test_success_resets_counter(self):
        rm = _make_rm()
        rm.state.consecutive_api_errors = 2
        ex = _FakeExchange()
        guard = ExchangeApiGuard(ex, risk_manager=rm)

        result = await guard.fetch_ticker("BTC/USDT")

        assert result == {"last": 100.0}
        assert rm.state.consecutive_api_errors == 0
        assert ex.calls == ["ticker:BTC/USDT"]

    @pytest.mark.asyncio
    async def test_failure_increments_and_reraises(self):
        rm = _make_rm(threshold=10)
        ex = _FakeExchange()
        ex.fail_next = 1
        guard = ExchangeApiGuard(ex, risk_manager=rm)

        with pytest.raises(RuntimeError, match="boom"):
            await guard.fetch_ticker("BTC/USDT")

        assert rm.state.consecutive_api_errors == 1
        assert not rm.state.kill_switch_active

    @pytest.mark.asyncio
    async def test_threshold_activates_kill_switch_and_callback(self):
        rm = _make_rm(threshold=2)
        ex = _FakeExchange()
        callback_calls: List[int] = []
        guard = ExchangeApiGuard(
            ex,
            risk_manager=rm,
            on_kill_switch=lambda: callback_calls.append(1),
        )

        ex.fail_next = 5
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await guard.fetch_balance()

        assert rm.state.kill_switch_active is True
        assert callback_calls == [1]

        # Subsequent failure must NOT re-trigger the callback.
        with pytest.raises(RuntimeError):
            await guard.fetch_balance()
        assert callback_calls == [1]

    @pytest.mark.asyncio
    async def test_non_api_attributes_pass_through(self):
        rm = _make_rm()
        ex = _FakeExchange()
        guard = ExchangeApiGuard(ex, risk_manager=rm)

        # Non-async, non-API helper — wrapper must forward unmodified.
        assert guard.some_local_helper() == "local"
        # Plain attribute access.
        assert guard.markets == {"BTC/USDT": {}}
        # Counter unchanged by attribute reads.
        assert rm.state.consecutive_api_errors == 0

    @pytest.mark.asyncio
    async def test_create_order_is_guarded(self):
        rm = _make_rm(threshold=2)
        ex = _FakeExchange()
        ex.fail_next = 2
        guard = ExchangeApiGuard(ex, risk_manager=rm)

        with pytest.raises(RuntimeError):
            await guard.create_order(symbol="BTC/USDT", side="buy",
                                     type="limit", amount=0.01, price=100)
        with pytest.raises(RuntimeError):
            await guard.create_order(symbol="BTC/USDT", side="buy",
                                     type="limit", amount=0.01, price=100)

        assert rm.state.kill_switch_active is True

    @pytest.mark.asyncio
    async def test_disabled_threshold_never_kills(self):
        rm = _make_rm(threshold=0)  # disabled per RiskConfig contract
        ex = _FakeExchange()
        ex.fail_next = 50
        guard = ExchangeApiGuard(ex, risk_manager=rm)

        for _ in range(20):
            with pytest.raises(RuntimeError):
                await guard.fetch_ticker("BTC/USDT")

        assert rm.state.consecutive_api_errors == 20
        assert rm.state.kill_switch_active is False


# --------------------------------------------------------------------------- #
# Item 2 — min_profit_threshold_percent default                               #
# --------------------------------------------------------------------------- #
class TestMinProfitThresholdDefault:
    def test_default_covers_round_trip(self):
        # 2 * (trading_fee + slippage) = 2 * (0.001 + 0.0005) = 0.003 = 0.3%
        round_trip = 2 * (settings.backtest.trading_fee + settings.backtest.slippage) * 100
        assert settings.grid.min_profit_threshold_percent >= round_trip - 1e-9, (
            "min_profit_threshold_percent default must cover one round-trip "
            f"of fees+slippage ({round_trip:.4f}%); got "
            f"{settings.grid.min_profit_threshold_percent}"
        )


# --------------------------------------------------------------------------- #
# Item 3 — portfolio loss thresholds in RiskConfig                            #
# --------------------------------------------------------------------------- #
class TestRiskConfigPortfolioThresholds:
    def test_defaults_present_and_ordered(self):
        rc = settings.risk
        assert hasattr(rc, "portfolio_stop_loss_pct")
        assert hasattr(rc, "portfolio_emergency_stop_pct")
        assert 0 < rc.portfolio_stop_loss_pct < rc.portfolio_emergency_stop_pct < 1.0

    def test_grid_live_trader_reads_from_config(self, monkeypatch):
        # Patch the config and make sure GridLiveTrader reflects it.
        monkeypatch.setattr(settings.risk, "portfolio_stop_loss_pct", 0.07)
        monkeypatch.setattr(settings.risk, "portfolio_emergency_stop_pct", 0.12)

        from execution.grid_live import GridLiveTrader

        trader = GridLiveTrader(symbols=["BTC/USDT"], testnet=True)
        assert trader._stop_loss_pct == 0.07
        assert trader._max_loss_pct == 0.12
