"""Session 2 regressions: grid geometry, level placement, capital allocation,
and ML breakeven floor for `recommended_grids`.
"""
import numpy as np
import pandas as pd
import pytest

from strategies.grid import GridStrategy, GridConfig
from strategies.indicators import TechnicalIndicators


class TestGridGeometry:
    """The number of BUY+SELL levels must equal `num_grids` exactly, no
    off-by-one, and `total_investment` must be split only across BUY levels."""

    def _make(self, num_grids=10, lower=90.0, upper=110.0, current=100.0,
              total_investment=100.0):
        s = GridStrategy('SOL/USDT')
        s.config = GridConfig(
            symbol='SOL/USDT', upper_price=upper, lower_price=lower,
            num_grids=num_grids, total_investment=total_investment,
        )
        s.center_price = current
        s.initialized = True
        s._create_grid_levels(current)
        return s

    def test_level_count_equals_num_grids(self):
        for n in (4, 5, 8, 10, 13):
            s = self._make(num_grids=n)
            assert len(s.grid_levels) == n, f"expected {n} levels, got {len(s.grid_levels)}"

    def test_levels_strictly_inside_range(self):
        s = self._make(num_grids=10, lower=90.0, upper=110.0)
        for lvl in s.grid_levels:
            assert s.config.lower_price < lvl.price < s.config.upper_price

    def test_levels_evenly_spaced(self):
        s = self._make(num_grids=4, lower=90.0, upper=110.0)
        prices = sorted(l.price for l in s.grid_levels)
        gaps = [b - a for a, b in zip(prices, prices[1:])]
        for g in gaps:
            assert abs(g - s.config.grid_spacing) < 1e-9
        # Endpoint gaps to the configured boundaries also equal spacing.
        assert abs(prices[0] - s.config.lower_price - s.config.grid_spacing) < 1e-9
        assert abs(s.config.upper_price - prices[-1] - s.config.grid_spacing) < 1e-9

    def test_capital_split_only_across_buys(self):
        s = self._make(num_grids=10, lower=90.0, upper=110.0,
                       current=100.0, total_investment=100.0)
        buys = [l for l in s.grid_levels if l.side == 'buy']
        sells = [l for l in s.grid_levels if l.side == 'sell']
        assert len(buys) + len(sells) == 10

        # Total USDT committed across BUYs equals total_investment.
        usdt_in_buys = sum(l.amount * l.price for l in buys)
        assert abs(usdt_in_buys - 100.0) < 1e-6

        # Each BUY books an equal USDT slice (within float tolerance).
        slices = [l.amount * l.price for l in buys]
        assert max(slices) - min(slices) < 1e-6

    def test_skewed_center_still_yields_num_grids_levels(self):
        # Center close to upper edge → most levels are BUYs, but the total
        # must still be exactly `num_grids`.
        s = self._make(num_grids=8, lower=90.0, upper=110.0, current=108.0)
        assert len(s.grid_levels) == 8


class TestCheckGridFills:
    """Off-by-one symmetric inclusion + no mutation during iteration."""

    def _make(self):
        s = GridStrategy('SOL/USDT')
        s.config = GridConfig(
            symbol='SOL/USDT', upper_price=110.0, lower_price=90.0,
            num_grids=4, total_investment=100.0,
        )
        s.center_price = 100.0
        s.initialized = True
        s._create_grid_levels(100.0)
        return s

    def test_buy_inclusive_on_both_sides(self):
        s = self._make()
        # Move from above to exactly the BUY level → must trigger.
        buy = max([l for l in s.grid_levels if l.side == 'buy'], key=lambda l: l.price)
        s.last_price = buy.price + 1.0
        fills = s.check_grid_fills(buy.price)  # exact-touch on the down-tick
        assert any(f['side'] == 'buy' and f['price'] == buy.price for f in fills)

    def test_sell_inclusive_on_both_sides(self):
        s = self._make()
        sell = min([l for l in s.grid_levels if l.side == 'sell'], key=lambda l: l.price)
        s.last_price = sell.price - 1.0
        fills = s.check_grid_fills(sell.price)
        assert any(f['side'] == 'sell' and f['price'] == sell.price for f in fills)

    def test_no_double_fill_when_new_level_spawned_in_same_tick(self):
        """Phase-2 spawn must not re-enter the iteration loop."""
        s = self._make()
        # Sweep price sharply down so multiple BUYs cross at once.
        s.last_price = 110.0
        fills = s.check_grid_fills(91.0)
        # Each fill must correspond to a level that was NOT spawned in this tick.
        prices_filled = {(f['side'], round(f['price'], 6)) for f in fills}
        # Count BUY fills in returned `fills` — must equal the count of BUY
        # levels at-or-above 91.0 that existed before the call (i.e. all BUYs).
        # Without the fix, freshly spawned opposite SELLs could also appear.
        assert all(side == 'buy' for side, _ in prices_filled)


class TestWilderSmoothing:
    """ATR/RSI must use Wilder smoothing (alpha=1/period) by default; the
    legacy EMA variant must remain available for ML-feature compatibility."""

    @pytest.fixture
    def ohlc(self):
        np.random.seed(7)
        n = 200
        idx = pd.date_range('2024-01-01', periods=n, freq='1h')
        close = 100.0 + np.cumsum(np.random.normal(0, 0.5, n))
        high = close + np.abs(np.random.normal(0, 0.3, n))
        low = close - np.abs(np.random.normal(0, 0.3, n))
        return pd.DataFrame({'high': high, 'low': low, 'close': close}, index=idx)

    def test_atr_wilder_default_differs_from_ema(self, ohlc):
        wilder = TechnicalIndicators.atr(ohlc['high'], ohlc['low'], ohlc['close'], 14)
        ema = TechnicalIndicators.atr(ohlc['high'], ohlc['low'], ohlc['close'], 14, smoothing='ema')
        # Same length, both finite at the tail; values must differ meaningfully.
        assert len(wilder) == len(ohlc)
        assert not np.isclose(wilder.iloc[-1], ema.iloc[-1], rtol=1e-6)

    def test_atr_wilder_matches_recursive_definition(self, ohlc):
        period = 14
        atr = TechnicalIndicators.atr(ohlc['high'], ohlc['low'], ohlc['close'], period)

        # Recursive Wilder: ATR_t = ATR_{t-1} + (TR_t - ATR_{t-1}) / period
        tr = pd.concat([
            ohlc['high'] - ohlc['low'],
            (ohlc['high'] - ohlc['close'].shift(1)).abs(),
            (ohlc['low'] - ohlc['close'].shift(1)).abs(),
        ], axis=1).max(axis=1)

        # ewm(alpha=1/period, adjust=False) seeds on the first finite value.
        expected = tr.ewm(alpha=1.0 / period, adjust=False).mean()
        pd.testing.assert_series_equal(atr, expected, check_names=False)

    def test_rsi_wilder_default_differs_from_ema(self, ohlc):
        wilder = TechnicalIndicators.rsi(ohlc['close'], 14)
        ema = TechnicalIndicators.rsi(ohlc['close'], 14, smoothing='ema')
        assert not np.isclose(wilder.iloc[-1], ema.iloc[-1], rtol=1e-6)

    def test_rsi_in_range(self, ohlc):
        rsi = TechnicalIndicators.rsi(ohlc['close'], 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_invalid_smoothing_raises(self, ohlc):
        with pytest.raises(ValueError):
            TechnicalIndicators.atr(ohlc['high'], ohlc['low'], ohlc['close'], 14, smoothing='bogus')
        with pytest.raises(ValueError):
            TechnicalIndicators.rsi(ohlc['close'], 14, smoothing='bogus')

    def test_add_all_indicators_exposes_legacy_columns(self, ohlc):
        # Add a synthetic OHLCV frame.
        df = ohlc.copy()
        df['open'] = df['close']
        df['volume'] = 1000.0
        out = TechnicalIndicators.add_all_indicators(df)
        for col in ('rsi', 'rsi_ema', 'atr', 'atr_ema'):
            assert col in out.columns


class TestMLAdvisorBreakevenFloor:
    """`recommended_grids` must respect a `2*fee + slippage + edge` breakeven
    floor on per-grid spacing."""

    def test_breakeven_floor_caps_grids_in_tight_range(self):
        from strategies.ml_grid_advisor import MLGridAdvisor

        advisor = MLGridAdvisor()
        vol = {
            'atr_pct': 0.005, 'bb_width': 0.02, 'vol_ratio': 0.5,
            'price_range_24h': 0.01,
        }
        trend = {'trend_score': 0.0}
        advice = advisor._compute_grid_params(vol, trend, ml_confidence=0.0, ml_direction=0.0)

        # spacing = grid_range_pct / (recommended_grids + 1) must clear floor.
        from config.settings import settings
        fee = settings.backtest.trading_fee
        slippage = settings.backtest.slippage
        floor = 2 * fee + slippage + 0.001
        spacing = advice.grid_range_pct / (advice.recommended_grids + 1)
        assert spacing >= floor - 1e-12, (
            f"spacing {spacing:.5f} below floor {floor:.5f} "
            f"(range={advice.grid_range_pct:.4f}, grids={advice.recommended_grids})"
        )

    def test_recommended_grids_at_least_one(self):
        from strategies.ml_grid_advisor import MLGridAdvisor

        advisor = MLGridAdvisor()
        vol = {
            'atr_pct': 0.001, 'bb_width': 0.005, 'vol_ratio': 0.4,
            'price_range_24h': 0.002,
        }
        trend = {'trend_score': 0.0}
        advice = advisor._compute_grid_params(vol, trend, ml_confidence=0.0, ml_direction=0.0)
        assert advice.recommended_grids >= 1
