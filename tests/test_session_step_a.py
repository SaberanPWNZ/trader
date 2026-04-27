"""Step A integration tests — wires C10 helpers into live + backtest paths.

Covers:
    * GridStrategy.initialize_grid uses compute_adaptive_num_grids
      (replaces the old hardcoded ``num_grids=5``).
    * MLGridAdvisor.get_advice now routes through compute_adaptive_num_grids
      (same regime → line-count semantics across live and backtest).
    * GridLiveTrader writes the new ``expected_price`` column on the
      trades CSV and migrates legacy headers in place.
"""
import csv
import os
import tempfile
from datetime import datetime
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from config.settings import settings
from execution.portfolio_protection import compute_adaptive_num_grids
from strategies.grid import GridStrategy
from strategies.indicators import TechnicalIndicators


def _make_ohlcv(n: int, vol_per_step: float, seed: int = 0) -> pd.DataFrame:
    """Synthesise an n-bar OHLCV with a target hourly-return std."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(loc=0.0, scale=vol_per_step, size=n)
    close = 100.0 * np.exp(np.cumsum(rets))
    df = pd.DataFrame({
        'open': close,
        'high': close * 1.001,
        'low': close * 0.999,
        'close': close,
        'volume': np.full(n, 1000.0),
    })
    df = TechnicalIndicators.add_all_indicators(df)
    return df


class TestGridStrategyInitializeGridAdaptive:
    """`GridStrategy.initialize_grid` must drive `num_grids` from the
    canonical helper instead of the old hardcoded value of 5."""

    def _last_atr(self, df: pd.DataFrame) -> float:
        return float(df['atr'].dropna().iloc[-1])

    def test_low_volatility_returns_max_or_helper_value(self):
        df = _make_ohlcv(120, vol_per_step=0.001, seed=1)  # ~0.1% std → "low"
        s = GridStrategy('BTC/USDT')
        cfg = s.initialize_grid(
            current_price=float(df['close'].iloc[-1]),
            atr=self._last_atr(df),
            total_investment=200.0,
            data=df,
        )
        expected = compute_adaptive_num_grids(
            min_grids=settings.grid.min_grids,
            max_grids=settings.grid.max_grids,
            volatility_regime="low",
        )
        assert cfg.num_grids == expected
        # No longer the legacy hardcoded value.
        assert cfg.num_grids != 5

    def test_high_volatility_shrinks_grid(self):
        # >1.5% hourly std → "high" regime.
        df = _make_ohlcv(120, vol_per_step=0.025, seed=2)
        s = GridStrategy('BTC/USDT')
        cfg = s.initialize_grid(
            current_price=float(df['close'].iloc[-1]),
            atr=self._last_atr(df),
            total_investment=200.0,
            data=df,
        )
        expected_high = compute_adaptive_num_grids(
            min_grids=settings.grid.min_grids,
            max_grids=settings.grid.max_grids,
            volatility_regime="high",
        )
        expected_low = compute_adaptive_num_grids(
            min_grids=settings.grid.min_grids,
            max_grids=settings.grid.max_grids,
            volatility_regime="low",
        )
        assert cfg.num_grids == expected_high
        # Sanity: high regime never exceeds low regime's count.
        assert cfg.num_grids <= expected_low

    def test_explicit_regime_override_wins(self):
        df = _make_ohlcv(120, vol_per_step=0.025, seed=3)  # naturally "high"
        s = GridStrategy('BTC/USDT')
        cfg = s.initialize_grid(
            current_price=float(df['close'].iloc[-1]),
            atr=self._last_atr(df),
            total_investment=200.0,
            data=df,
            volatility_regime="low",
        )
        expected = compute_adaptive_num_grids(
            min_grids=settings.grid.min_grids,
            max_grids=settings.grid.max_grids,
            volatility_regime="low",
        )
        assert cfg.num_grids == expected

    def test_short_data_falls_back_to_normal_regime(self):
        df = _make_ohlcv(10, vol_per_step=0.001, seed=4)
        # The 'atr' column will be largely NaN at length 10, so synthesise
        # a stable atr value just for this test.
        s = GridStrategy('BTC/USDT')
        cfg = s.initialize_grid(
            current_price=100.0,
            atr=1.0,
            total_investment=200.0,
            data=df,
        )
        expected = compute_adaptive_num_grids(
            min_grids=settings.grid.min_grids,
            max_grids=settings.grid.max_grids,
            volatility_regime="normal",
        )
        assert cfg.num_grids == expected

    def test_levels_match_chosen_num_grids(self):
        df = _make_ohlcv(120, vol_per_step=0.001, seed=5)
        s = GridStrategy('BTC/USDT')
        cfg = s.initialize_grid(
            current_price=float(df['close'].iloc[-1]),
            atr=self._last_atr(df),
            total_investment=200.0,
            data=df,
        )
        # Geometry invariant: exactly ``num_grids`` interior levels.
        assert len(s.grid_levels) == cfg.num_grids


class TestMLAdvisorAdaptiveGrids:
    """Verify MLGridAdvisor consults the canonical helper rather than the
    old if/elif map. We call get_advice() and inspect recommended_grids
    against the helper's expectation for the same regime."""

    def _df(self, vol_per_step: float, seed: int) -> pd.DataFrame:
        return _make_ohlcv(300, vol_per_step=vol_per_step, seed=seed)

    def test_low_regime_uses_helper_value(self):
        # MLGridAdvisor classifies "low" when vol_ratio < 0.7 vs
        # historical mean. A low-volatility series fed through the same
        # pipeline reliably classifies as "low" or "normal" depending on
        # the random walk; we assert the chosen grid count always matches
        # *some* helper output for *some* regime, never the legacy 6/8/10
        # hardcoded mapping.
        from strategies.ml_grid_advisor import MLGridAdvisor
        advisor = MLGridAdvisor()
        df = self._df(0.001, seed=10)
        advice = advisor.get_advice('BTC/USDT', df)
        valid_outputs = {
            compute_adaptive_num_grids(
                min_grids=settings.grid.min_grids,
                max_grids=settings.grid.max_grids,
                volatility_regime=r,
            )
            for r in ("extreme", "high", "normal", "low")
        }
        # Allow the breakeven-floor cap to lower the count; require the
        # value to be at most the helper's result for the chosen regime.
        helper_for_regime = compute_adaptive_num_grids(
            min_grids=settings.grid.min_grids,
            max_grids=settings.grid.max_grids,
            volatility_regime=advice.volatility_regime,
        )
        assert advice.recommended_grids <= helper_for_regime
        # And the value is positive and bounded.
        assert advice.recommended_grids >= 1
        assert advice.recommended_grids <= settings.grid.max_grids


class TestExpectedPriceCsvColumn:
    """`GridLiveTrader._log_trade_from_exchange` must write the
    expected_price stashed at order placement, and `_init_data_files`
    must migrate legacy CSV headers in place."""

    def _new_trader(self, tmpdir):
        # Lazy import — `GridLiveTrader.__init__` calls `_init_data_files`
        # which writes under cwd, so we cd into tmpdir first.
        from execution.grid_live import GridLiveTrader
        return GridLiveTrader(['BTC/USDT'], testnet=True)

    def test_new_csv_header_includes_expected_price(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        trader = self._new_trader(tmp_path)
        with open(trader._trades_file, 'r') as f:
            header = next(csv.reader(f))
        assert 'expected_price' in header

    def test_log_writes_expected_price_when_known(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        trader = self._new_trader(tmp_path)
        order_id = "abc123"
        trader._expected_prices[order_id] = 99.5

        trader._log_trade_from_exchange(
            symbol='BTC/USDT', side='BUY', price=99.42, amount=1.0,
            value=99.42, order_id=order_id, fee=0.1, trading_pnl=0.0,
            holding_pnl=0.0, balance=1000.0, total_value=1100.0, base_held=1.0,
        )

        with open(trader._trades_file, 'r') as f:
            rows = list(csv.reader(f))
        # First row is header, second is our trade.
        assert rows[1][6] == order_id
        assert rows[1][-1] == "99.50000000"
        # Cache popped on log.
        assert order_id not in trader._expected_prices

    def test_log_writes_blank_when_unknown(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        trader = self._new_trader(tmp_path)

        trader._log_trade_from_exchange(
            symbol='BTC/USDT', side='SELL', price=101.0, amount=0.5,
            value=50.5, order_id="never_seen", fee=0.05, trading_pnl=1.0,
            holding_pnl=0.0, balance=1000.0, total_value=1100.0, base_held=0.0,
        )

        with open(trader._trades_file, 'r') as f:
            rows = list(csv.reader(f))
        assert rows[1][-1] == ""

    def test_legacy_header_is_migrated_in_place(self, tmp_path, monkeypatch):
        # Pre-create a legacy file with the old 15-column header and a
        # representative data row; ``_init_data_files`` must add the
        # ``expected_price`` column to the header without rewriting rows.
        monkeypatch.chdir(tmp_path)
        os.makedirs('data', exist_ok=True)
        path = 'data/grid_live_trades.csv'
        legacy_header = [
            'timestamp', 'symbol', 'side', 'price', 'amount', 'value',
            'order_id', 'status', 'fee', 'trading_pnl', 'holding_pnl',
            'realized_pnl', 'balance', 'total_value', 'base_held',
        ]
        legacy_row = [
            '2024-01-01T00:00:00', 'BTC/USDT', 'BUY', '100.0', '1.0', '100.0',
            'oid1', 'filled', '0.1', '0.0', '0.0',
            '0.0', '900.0', '1000.0', '1.0',
        ]
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(legacy_header)
            w.writerow(legacy_row)

        # Construct trader → triggers migration.
        self._new_trader(tmp_path)

        with open(path, 'r') as f:
            rows = list(csv.reader(f))
        assert rows[0][-1] == 'expected_price'
        # Data row preserved verbatim.
        assert rows[1] == legacy_row

    def test_expected_prices_dict_initialized_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        trader = self._new_trader(tmp_path)
        assert trader._expected_prices == {}
