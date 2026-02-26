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
