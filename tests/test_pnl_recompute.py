"""Regression tests for ``analytics.pnl_recompute``.

The legacy ``fix_*.py`` scripts each re-implemented this math; these
tests pin the single source of truth so future drift is caught.
"""
import pytest

from analytics.pnl_recompute import (
    Lot,
    recompute_trades,
    unrealized_from_positions,
)


def _trade(symbol, side, price, amount, value=None, ts="t"):
    return {
        "timestamp": ts,
        "symbol": symbol,
        "side": side,
        "price": price,
        "amount": amount,
        "value": value if value is not None else price * amount,
    }


class TestRecomputeTrades:
    def test_empty_input(self):
        result = recompute_trades([], initial_balance=1000.0)
        assert result.rows == []
        assert result.positions == {}
        assert result.final_balance == 1000.0
        assert result.realized_pnl == 0.0

    def test_simple_round_trip_locks_realized_profit(self):
        # BUY 1 @100 → SELL 1 @110. Profit = $10.
        rows = [
            _trade("BTC/USDT", "BUY", 100.0, 1.0),
            _trade("BTC/USDT", "SELL", 110.0, 1.0),
        ]
        result = recompute_trades(rows, initial_balance=1000.0)

        assert result.realized_pnl == pytest.approx(10.0)
        assert result.final_balance == pytest.approx(1010.0)
        assert result.positions == {"BTC/USDT": []}

        # Mid-row state: after BUY, balance dropped by $100 and we hold one lot.
        after_buy = result.rows[0]
        assert after_buy["balance"] == pytest.approx(900.0)
        assert after_buy["realized_pnl"] == 0.0
        # Mark-to-market on the BUY itself = entry price → 0 unrealized.
        assert after_buy["unrealized_pnl"] == pytest.approx(0.0)
        assert after_buy["total_value"] == pytest.approx(1000.0)

        # Final row: realized $10, no open positions, total = $1010.
        last = result.rows[-1]
        assert last["realized_pnl"] == pytest.approx(10.0)
        assert last["total_value"] == pytest.approx(1010.0)
        assert last["roi_percent"] == pytest.approx(1.0)

    def test_partial_close_uses_fifo_order(self):
        # Two BUYs at different prices, then one SELL — must pop the
        # *oldest* lot (lower price), realizing the bigger gain.
        rows = [
            _trade("BTC/USDT", "BUY", 100.0, 1.0),
            _trade("BTC/USDT", "BUY", 120.0, 1.0),
            _trade("BTC/USDT", "SELL", 130.0, 1.0),
        ]
        result = recompute_trades(rows, initial_balance=1000.0)
        # FIFO → matched against $100 lot, profit = $30.
        assert result.realized_pnl == pytest.approx(30.0)
        # Residual: one lot at $120.
        assert len(result.positions["BTC/USDT"]) == 1
        assert result.positions["BTC/USDT"][0].price == 120.0
        assert result.positions["BTC/USDT"][0].amount == 1.0

    def test_unrealized_marked_to_last_seen_price(self):
        # Open a BTC position, then a later trade in the same symbol at
        # higher price should re-mark the *previous* row's unrealized to
        # the new "last seen" once it occurs in the next row.
        rows = [
            _trade("BTC/USDT", "BUY", 100.0, 1.0),
            _trade("BTC/USDT", "BUY", 150.0, 1.0),
        ]
        result = recompute_trades(rows, initial_balance=1000.0)

        # After 2nd BUY: balance = 1000 - 100 - 150 = 750; cost basis = 250;
        # both lots marked at $150 → unrealized = (150-100) + (150-150) = $50.
        last = result.rows[-1]
        assert last["balance"] == pytest.approx(750.0)
        assert last["unrealized_pnl"] == pytest.approx(50.0)
        # Total = balance + cost_basis + unrealized = 750 + 250 + 50 = 1050.
        assert last["total_value"] == pytest.approx(1050.0)
        assert last["roi_percent"] == pytest.approx(5.0)

    def test_multi_symbol_marks_each_independently(self):
        # BTC and ETH each marked to their own last-seen price.
        rows = [
            _trade("BTC/USDT", "BUY", 100.0, 1.0),
            _trade("ETH/USDT", "BUY", 50.0, 2.0),
            _trade("BTC/USDT", "BUY", 110.0, 1.0),  # BTC last_seen=110
        ]
        result = recompute_trades(rows, initial_balance=1000.0)
        last = result.rows[-1]
        # Cost basis = 100 + 100 (eth) + 110 = 310.
        # BTC unrealized = (110-100) + (110-110) = 10.
        # ETH unrealized = (50-50)*2 = 0  (last_seen still 50).
        # Balance = 1000 - 310 = 690.
        # Total = 690 + 310 + 10 = 1010.
        assert last["balance"] == pytest.approx(690.0)
        assert last["unrealized_pnl"] == pytest.approx(10.0)
        assert last["total_value"] == pytest.approx(1010.0)

    def test_orphan_sell_credits_balance_no_position_pop(self):
        # Legacy CSV with a SELL that has no matching BUY (e.g. manual
        # intervention). Balance must still credit; no realized PnL.
        rows = [_trade("BTC/USDT", "SELL", 100.0, 1.0)]
        result = recompute_trades(rows, initial_balance=1000.0)
        assert result.final_balance == pytest.approx(1100.0)
        assert result.realized_pnl == 0.0
        assert result.positions.get("BTC/USDT", []) == []

    def test_current_prices_override_for_marking(self):
        # When current_prices is supplied, *every* row marks to the
        # override snapshot, not to last-seen playback prices.
        rows = [
            _trade("BTC/USDT", "BUY", 100.0, 1.0),
        ]
        result = recompute_trades(
            rows,
            initial_balance=1000.0,
            current_prices={"BTC/USDT": 200.0},
        )
        last = result.rows[-1]
        # Marked at $200 instead of $100 → unrealized = $100.
        assert last["unrealized_pnl"] == pytest.approx(100.0)
        assert last["total_value"] == pytest.approx(1100.0)

    def test_balance_conservation(self):
        # Balance conservation through a longer mixed sequence. NB: a SELL
        # pops the *entire* oldest lot regardless of its own amount —
        # this matches the legacy fix_*.py behaviour and the live grid
        # which fills exactly one lot per level.
        rows = [
            _trade("BTC/USDT", "BUY", 100.0, 1.0),
            _trade("ETH/USDT", "BUY", 50.0, 2.0),
            _trade("BTC/USDT", "SELL", 105.0, 1.0),
            _trade("ETH/USDT", "BUY", 55.0, 1.0),
            _trade("ETH/USDT", "SELL", 60.0, 1.0),
        ]
        result = recompute_trades(rows, initial_balance=1000.0)
        last = result.rows[-1]
        # Cash-only: 1000 - 100 - 100 + 105 - 55 + 60 = 910.
        assert last["balance"] == pytest.approx(910.0)
        # FIFO pops the whole [50, 2.0] lot first → ETH residual is the
        # later [55, 1.0] lot only.
        eth_lots = result.positions["ETH/USDT"]
        assert len(eth_lots) == 1
        assert eth_lots[0].price == pytest.approx(55.0)
        assert eth_lots[0].amount == pytest.approx(1.0)

    def test_zero_initial_balance_returns_zero_roi(self):
        # Avoid div-by-zero crash when ``initial_balance == 0``.
        rows = [_trade("BTC/USDT", "BUY", 100.0, 1.0)]
        result = recompute_trades(rows, initial_balance=0.0)
        assert result.rows[-1]["roi_percent"] == 0.0

    def test_string_inputs_coerced(self):
        # CSV rows arrive with string fields — must not crash.
        rows = [
            {"symbol": "BTC/USDT", "side": "BUY", "price": "100", "amount": "1", "value": "100"},
            {"symbol": "BTC/USDT", "side": "SELL", "price": "110", "amount": "1", "value": "110"},
        ]
        result = recompute_trades(rows, initial_balance=1000.0)
        assert result.realized_pnl == pytest.approx(10.0)

    def test_unknown_side_is_noop(self):
        rows = [
            _trade("BTC/USDT", "BUY", 100.0, 1.0),
            {"symbol": "BTC/USDT", "side": "DEPOSIT", "price": 0, "amount": 0, "value": 0},
        ]
        result = recompute_trades(rows, initial_balance=1000.0)
        assert result.final_balance == pytest.approx(900.0)
        assert len(result.positions["BTC/USDT"]) == 1


class TestUnrealizedFromPositions:
    def test_empty_positions(self):
        u, c = unrealized_from_positions({}, {})
        assert u == 0.0
        assert c == 0.0

    def test_missing_price_contributes_to_cost_only(self):
        positions = {"BTC/USDT": [Lot(100.0, 1.0, 100.0)]}
        u, c = unrealized_from_positions(positions, {})  # no price for BTC
        assert u == 0.0
        assert c == pytest.approx(100.0)

    def test_zero_price_treated_as_missing(self):
        positions = {"BTC/USDT": [Lot(100.0, 1.0, 100.0)]}
        u, c = unrealized_from_positions(positions, {"BTC/USDT": 0.0})
        assert u == 0.0
        assert c == pytest.approx(100.0)

    def test_multi_symbol(self):
        positions = {
            "BTC/USDT": [Lot(100.0, 1.0, 100.0), Lot(110.0, 0.5, 55.0)],
            "ETH/USDT": [Lot(50.0, 2.0, 100.0)],
        }
        prices = {"BTC/USDT": 120.0, "ETH/USDT": 45.0}
        u, c = unrealized_from_positions(positions, prices)
        # BTC: (120-100)*1 + (120-110)*0.5 = 20 + 5 = 25
        # ETH: (45-50)*2 = -10
        assert u == pytest.approx(15.0)
        # cost basis = 100 + 55 + 100 = 255
        assert c == pytest.approx(255.0)
