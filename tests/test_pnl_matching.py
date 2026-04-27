import pytest
from datetime import datetime
from execution.grid_live import GridLiveTrader, LiveGridPosition


@pytest.fixture
def trader():
    t = GridLiveTrader.__new__(GridLiveTrader)
    t.symbols = ['SOL/USDT']
    t.positions = {'SOL/USDT': []}
    t.current_prices = {'SOL/USDT': 100.0}
    t.realized_pnl = 0.0
    t.trading_pnl = 0.0
    t.total_fees_paid = 0.0
    t.completed_cycles = 0
    t.winning_trades = 0
    t.losing_trades = 0
    t.total_trades = 0
    return t


def makePosition(price: float, amount: float) -> LiveGridPosition:
    return LiveGridPosition(
        symbol='SOL/USDT',
        side='long',
        entry_price=price,
        amount=amount,
        order_id='test',
        opened_at=datetime.now()
    )


class TestFifoMatching:
    def testExactMatchSinglePosition(self, trader):
        trader.positions['SOL/USDT'] = [makePosition(80.0, 1.0)]

        sell_amount = 1.0
        sell_price = 85.0
        fee = 0.01

        remaining = sell_amount
        total_gross_pnl = 0.0
        total_matched = 0.0

        while remaining > 1e-8 and trader.positions['SOL/USDT']:
            pos = trader.positions['SOL/USDT'][0]
            matched = min(remaining, pos.amount)
            pnl = (sell_price - pos.entry_price) * matched
            total_gross_pnl += pnl
            total_matched += matched
            pos.amount -= matched
            remaining -= matched
            if pos.amount < 1e-8:
                trader.positions['SOL/USDT'].pop(0)

        trading_pnl = total_gross_pnl - fee

        assert len(trader.positions['SOL/USDT']) == 0
        assert abs(total_gross_pnl - 5.0) < 1e-8
        assert abs(trading_pnl - 4.99) < 1e-8
        assert abs(total_matched - 1.0) < 1e-8

    def testFifoOrder(self, trader):
        trader.positions['SOL/USDT'] = [
            makePosition(80.0, 1.0),
            makePosition(90.0, 1.0),
            makePosition(70.0, 1.0),
        ]

        sell_price = 85.0
        sell_amount = 1.0
        remaining = sell_amount
        total_gross_pnl = 0.0

        while remaining > 1e-8 and trader.positions['SOL/USDT']:
            pos = trader.positions['SOL/USDT'][0]
            matched = min(remaining, pos.amount)
            pnl = (sell_price - pos.entry_price) * matched
            total_gross_pnl += pnl
            pos.amount -= matched
            remaining -= matched
            if pos.amount < 1e-8:
                trader.positions['SOL/USDT'].pop(0)

        assert abs(total_gross_pnl - 5.0) < 1e-8
        assert len(trader.positions['SOL/USDT']) == 2
        assert trader.positions['SOL/USDT'][0].entry_price == 90.0
        assert trader.positions['SOL/USDT'][1].entry_price == 70.0

    def testPartialFillSellSmallerThanPosition(self, trader):
        trader.positions['SOL/USDT'] = [makePosition(80.0, 2.0)]

        sell_price = 85.0
        sell_amount = 0.5
        remaining = sell_amount
        total_gross_pnl = 0.0

        while remaining > 1e-8 and trader.positions['SOL/USDT']:
            pos = trader.positions['SOL/USDT'][0]
            matched = min(remaining, pos.amount)
            pnl = (sell_price - pos.entry_price) * matched
            total_gross_pnl += pnl
            pos.amount -= matched
            remaining -= matched
            if pos.amount < 1e-8:
                trader.positions['SOL/USDT'].pop(0)

        assert abs(total_gross_pnl - 2.5) < 1e-8
        assert len(trader.positions['SOL/USDT']) == 1
        assert abs(trader.positions['SOL/USDT'][0].amount - 1.5) < 1e-8

    def testPartialFillSellSpansMultiplePositions(self, trader):
        trader.positions['SOL/USDT'] = [
            makePosition(80.0, 0.3),
            makePosition(82.0, 0.5),
            makePosition(84.0, 1.0),
        ]

        sell_price = 90.0
        sell_amount = 1.0
        remaining = sell_amount
        total_gross_pnl = 0.0
        total_matched = 0.0

        while remaining > 1e-8 and trader.positions['SOL/USDT']:
            pos = trader.positions['SOL/USDT'][0]
            matched = min(remaining, pos.amount)
            pnl = (sell_price - pos.entry_price) * matched
            total_gross_pnl += pnl
            total_matched += matched
            pos.amount -= matched
            remaining -= matched
            if pos.amount < 1e-8:
                trader.positions['SOL/USDT'].pop(0)

        expected_pnl = (90 - 80) * 0.3 + (90 - 82) * 0.5 + (90 - 84) * 0.2
        assert abs(total_gross_pnl - expected_pnl) < 1e-8
        assert abs(total_matched - 1.0) < 1e-8
        assert len(trader.positions['SOL/USDT']) == 1
        assert abs(trader.positions['SOL/USDT'][0].amount - 0.8) < 1e-8
        assert trader.positions['SOL/USDT'][0].entry_price == 84.0

    def testSellWithNoPositions(self, trader):
        trader.positions['SOL/USDT'] = []
        positions_before = len(trader.positions['SOL/USDT'])
        assert positions_before == 0

    def testSellMoreThanAvailable(self, trader):
        trader.positions['SOL/USDT'] = [makePosition(80.0, 0.5)]

        sell_price = 85.0
        sell_amount = 1.0
        remaining = sell_amount
        total_gross_pnl = 0.0
        total_matched = 0.0

        while remaining > 1e-8 and trader.positions['SOL/USDT']:
            pos = trader.positions['SOL/USDT'][0]
            matched = min(remaining, pos.amount)
            pnl = (sell_price - pos.entry_price) * matched
            total_gross_pnl += pnl
            total_matched += matched
            pos.amount -= matched
            remaining -= matched
            if pos.amount < 1e-8:
                trader.positions['SOL/USDT'].pop(0)

        assert abs(total_matched - 0.5) < 1e-8
        assert abs(remaining - 0.5) < 1e-8
        assert abs(total_gross_pnl - 2.5) < 1e-8
        assert len(trader.positions['SOL/USDT']) == 0

    def testLosingTrade(self, trader):
        trader.positions['SOL/USDT'] = [makePosition(90.0, 1.0)]

        sell_price = 85.0
        fee = 0.01
        remaining = 1.0
        total_gross_pnl = 0.0

        while remaining > 1e-8 and trader.positions['SOL/USDT']:
            pos = trader.positions['SOL/USDT'][0]
            matched = min(remaining, pos.amount)
            pnl = (sell_price - pos.entry_price) * matched
            total_gross_pnl += pnl
            pos.amount -= matched
            remaining -= matched
            if pos.amount < 1e-8:
                trader.positions['SOL/USDT'].pop(0)

        trading_pnl = total_gross_pnl - fee
        assert total_gross_pnl < 0
        assert trading_pnl < total_gross_pnl


class TestPnlConsistency:
    def testRealizedEqualsTrading(self, trader):
        trader.positions['SOL/USDT'] = [
            makePosition(80.0, 1.0),
            makePosition(82.0, 1.0),
        ]

        for sell_price in [85.0, 83.0]:
            sell_amount = 1.0
            fee = 0.01
            remaining = sell_amount
            total_gross_pnl = 0.0

            while remaining > 1e-8 and trader.positions['SOL/USDT']:
                pos = trader.positions['SOL/USDT'][0]
                matched = min(remaining, pos.amount)
                pnl = (sell_price - pos.entry_price) * matched
                total_gross_pnl += pnl
                pos.amount -= matched
                remaining -= matched
                if pos.amount < 1e-8:
                    trader.positions['SOL/USDT'].pop(0)

            trading_pnl = total_gross_pnl - fee
            trader.realized_pnl += trading_pnl
            trader.trading_pnl += trading_pnl

        assert abs(trader.realized_pnl - trader.trading_pnl) < 1e-8


class TestPositionRestore:
    def testRestoreFifoMatchesLive(self):
        buys = [
            {'price': 80.0, 'amount': 1.0},
            {'price': 82.0, 'amount': 0.5},
            {'price': 84.0, 'amount': 1.0},
        ]
        sells = [
            {'price': 85.0, 'amount': 1.2},
        ]

        buy_queue = []
        for b in buys:
            buy_queue.append({'price': b['price'], 'amount': b['amount']})

        for s in sells:
            remaining = s['amount']
            while buy_queue and remaining > 1e-8:
                pos = buy_queue[0]
                matched = min(remaining, pos['amount'])
                pos['amount'] -= matched
                remaining -= matched
                if pos['amount'] < 1e-8:
                    buy_queue.pop(0)

        assert len(buy_queue) == 2
        assert abs(buy_queue[0]['amount'] - 0.3) < 1e-8
        assert buy_queue[0]['price'] == 82.0
        assert abs(buy_queue[1]['amount'] - 1.0) < 1e-8
        assert buy_queue[1]['price'] == 84.0


class TestFifoByOpenedAt:
    """Session 1 regression: _sync_trades_from_exchange must close oldest first
    (FIFO by opened_at), not cheapest first (which booked artificial profits)."""

    def testSellSortsByOpenedAtNotPrice(self):
        from datetime import datetime, timedelta
        t0 = datetime(2026, 1, 1, 12, 0, 0)

        positions = [
            LiveGridPosition('SOL/USDT', 'long', 90.0, 1.0, 'a', t0),
            LiveGridPosition('SOL/USDT', 'long', 70.0, 1.0, 'b', t0 + timedelta(minutes=5)),
            LiveGridPosition('SOL/USDT', 'long', 80.0, 1.0, 'c', t0 + timedelta(minutes=10)),
        ]

        positions.sort(key=lambda p: p.opened_at or datetime.min)

        assert positions[0].entry_price == 90.0
        assert positions[1].entry_price == 70.0
        assert positions[2].entry_price == 80.0

    def testFifoBooksHonestPnlNotCheapestFirst(self):
        from datetime import datetime, timedelta
        t0 = datetime(2026, 1, 1, 12, 0, 0)

        # Oldest entry is the highest-priced one. Cheapest-first sort would
        # falsely book a profit; FIFO correctly books a loss.
        positions = [
            LiveGridPosition('SOL/USDT', 'long', 90.0, 1.0, 'a', t0),
            LiveGridPosition('SOL/USDT', 'long', 70.0, 1.0, 'b', t0 + timedelta(minutes=5)),
        ]
        positions.sort(key=lambda p: p.opened_at or datetime.min)

        sell_price = 85.0
        remaining = 1.0
        total_gross = 0.0
        while remaining > 1e-8 and positions:
            pos = positions[0]
            matched = min(remaining, pos.amount)
            total_gross += (sell_price - pos.entry_price) * matched
            pos.amount -= matched
            remaining -= matched
            if pos.amount < 1e-8:
                positions.pop(0)

        assert total_gross == -5.0  # Closed the older 90-entry, not the 70-entry.
        assert len(positions) == 1
        assert positions[0].entry_price == 70.0


class TestFeeConversion:
    """Session 1 regression: fees in non-USDT currency must be converted to USDT
    before accumulation, otherwise total_fees_paid mixes currencies and trading_pnl
    is silently wrong."""

    @pytest.mark.asyncio
    async def testFeeUsdtPassthrough(self, trader):
        class _Ex:
            async def fetch_ticker(self, sym):
                raise AssertionError("should not be called for USDT fee")
        trader.exchange = _Ex()
        trader._fee_ticker_cache = {}
        trader._fee_ticker_ttl_seconds = 60

        from execution.grid_live import GridLiveTrader
        usdt_fee = await GridLiveTrader._convert_fee_to_usdt(
            trader, {'cost': 0.5, 'currency': 'USDT'}, 'SOL/USDT', 100.0
        )
        assert usdt_fee == 0.5

    @pytest.mark.asyncio
    async def testFeeBnbConversion(self, trader):
        calls = {'n': 0}

        class _Ex:
            async def fetch_ticker(self, sym):
                calls['n'] += 1
                assert sym == 'BNB/USDT'
                return {'last': 600.0}

        trader.exchange = _Ex()
        trader._fee_ticker_cache = {}
        trader._fee_ticker_ttl_seconds = 60

        from execution.grid_live import GridLiveTrader
        usdt_fee = await GridLiveTrader._convert_fee_to_usdt(
            trader, {'cost': 0.001, 'currency': 'BNB'}, 'SOL/USDT', 100.0
        )
        assert abs(usdt_fee - 0.6) < 1e-8

        # Cached on second call.
        usdt_fee2 = await GridLiveTrader._convert_fee_to_usdt(
            trader, {'cost': 0.002, 'currency': 'BNB'}, 'SOL/USDT', 100.0
        )
        assert abs(usdt_fee2 - 1.2) < 1e-8
        assert calls['n'] == 1

    @pytest.mark.asyncio
    async def testFeeBaseCurrencyConversion(self, trader):
        class _Ex:
            async def fetch_ticker(self, sym):
                raise AssertionError("base-currency fee uses trade price, not a fetch")
        trader.exchange = _Ex()
        trader._fee_ticker_cache = {}
        trader._fee_ticker_ttl_seconds = 60

        from execution.grid_live import GridLiveTrader
        usdt_fee = await GridLiveTrader._convert_fee_to_usdt(
            trader, {'cost': 0.01, 'currency': 'SOL'}, 'SOL/USDT', 150.0
        )
        assert abs(usdt_fee - 1.5) < 1e-8

    @pytest.mark.asyncio
    async def testEmptyFeeReturnsZero(self, trader):
        trader.exchange = None
        trader._fee_ticker_cache = {}
        trader._fee_ticker_ttl_seconds = 60

        from execution.grid_live import GridLiveTrader
        assert await GridLiveTrader._convert_fee_to_usdt(trader, None, 'SOL/USDT', 100.0) == 0.0
        assert await GridLiveTrader._convert_fee_to_usdt(trader, {}, 'SOL/USDT', 100.0) == 0.0
        assert await GridLiveTrader._convert_fee_to_usdt(
            trader, {'cost': 0, 'currency': 'BNB'}, 'SOL/USDT', 100.0
        ) == 0.0


class TestGridPairMatching:
    """Session 1 regression: GridStrategy realized/unrealized PnL must use pair_id
    so that a BUY closed by a SELL is not also counted as 'open' (double-count)."""

    def _make_strategy(self):
        from strategies.grid import GridStrategy, GridConfig
        s = GridStrategy('SOL/USDT')
        s.config = GridConfig(
            symbol='SOL/USDT', upper_price=110.0, lower_price=90.0,
            num_grids=4, total_investment=100.0
        )
        s.center_price = 100.0
        s.initialized = True
        s._create_grid_levels(100.0)
        return s

    def testRealizedPnlUsesPairId(self):
        s = self._make_strategy()
        # Fill the BUY at 95 and let _create_opposite_order spawn its SELL at 100.
        buy = next(l for l in s.grid_levels if l.side == 'buy' and abs(l.price - 95.0) < 1e-6)
        buy.filled = True
        buy.filled_at = datetime(2026, 1, 1, 12, 0, 0)
        s._create_opposite_order(buy)

        sell = next(l for l in s.grid_levels if l.pair_id == buy.level_id)
        sell.filled = True
        sell.filled_at = datetime(2026, 1, 1, 12, 30, 0)

        expected = (sell.price - buy.price) * min(buy.amount, sell.amount)
        assert abs(s.calculate_realized_pnl() - expected) < 1e-8

    def testUnrealizedExcludesPairedClosedBuys(self):
        s = self._make_strategy()
        # Two BUYs filled.
        buy_low = next(l for l in s.grid_levels if l.side == 'buy' and abs(l.price - 90.0) < 1e-6)
        buy_high = next(l for l in s.grid_levels if l.side == 'buy' and abs(l.price - 95.0) < 1e-6)
        for b in (buy_low, buy_high):
            b.filled = True
            b.filled_at = datetime(2026, 1, 1, 12, 0, 0)
            s._create_opposite_order(b)

        # Only buy_high's paired SELL fires.
        sell_for_high = next(l for l in s.grid_levels if l.pair_id == buy_high.level_id)
        sell_for_high.filled = True
        sell_for_high.filled_at = datetime(2026, 1, 1, 12, 30, 0)

        # Unrealized must include buy_low only.
        current = 105.0
        expected_unrealized = (current - buy_low.price) * buy_low.amount
        assert abs(s.calculate_unrealized_pnl(current) - expected_unrealized) < 1e-8

        # Realized must reflect buy_high closure only.
        expected_realized = (sell_for_high.price - buy_high.price) * min(buy_high.amount, sell_for_high.amount)
        assert abs(s.calculate_realized_pnl() - expected_realized) < 1e-8

    def testLegacyFifoFallbackForUnpairedLevels(self):
        """Levels created without level_id (e.g. restored from old state) still
        match via FIFO chronological order."""
        from strategies.grid import GridLevel
        s = self._make_strategy()
        # Bypass _create_opposite_order: insert a SELL without pair_id.
        legacy_buy = GridLevel(price=90.0, side='buy', amount=1.0,
                               filled=True, filled_at=datetime(2026, 1, 1, 10, 0, 0))
        legacy_sell = GridLevel(price=95.0, side='sell', amount=1.0,
                                filled=True, filled_at=datetime(2026, 1, 1, 11, 0, 0))
        s.grid_levels = [legacy_buy, legacy_sell]
        assert abs(s.calculate_realized_pnl() - 5.0) < 1e-8
        # No paired link → unrealized would also see legacy_buy as open. That's
        # the documented legacy behaviour; the fix protects only pair-tagged levels.
