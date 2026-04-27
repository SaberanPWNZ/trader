"""
Regression tests for Session C7 — wiring C6 outputs into the live trader.

Covers the pure helpers used by ``GridLiveTrader``:

- ``compute_target_investment`` snapshots the *initial* free-USDT pot on
  the first funded call and derives equal per-symbol slices from that
  pot, even when later symbols see a depleted ``usdt_free`` because
  prior symbols locked their share in BUY orders, or when a single
  symbol reinitializes mid-life with most capital parked elsewhere.
"""
import pytest

from execution.portfolio_protection import (
    InvestmentBudget,
    compute_target_investment,
)


class TestComputeTargetInvestment:
    def test_first_call_snapshots_pot_and_returns_equal_share(self):
        budget = InvestmentBudget()
        v = compute_target_investment(
            budget=budget, symbol='BTC',
            usdt_free=1000.0, investment_ratio=0.85, num_symbols=5,
        )
        assert v == pytest.approx(170.0)
        assert budget.initial_pot == 1000.0
        assert budget.per_symbol == {'BTC': pytest.approx(170.0)}

    def test_sequential_initialization_gives_equal_slices(self):
        """Production startup: each symbol's fetch_balance sees less USDT
        because prior symbols locked theirs in BUYs. The shared pot
        snapshot must shield us from that drift."""
        budget = InvestmentBudget()
        symbols = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        usdt_free = 1000.0
        budgets = []
        for sym in symbols:
            v = compute_target_investment(
                budget=budget, symbol=sym,
                usdt_free=usdt_free, investment_ratio=0.85,
                num_symbols=len(symbols),
            )
            budgets.append(v)
            usdt_free -= v  # simulate capital locking
        assert all(b == pytest.approx(170.0) for b in budgets)
        assert usdt_free == pytest.approx(150.0)  # 1000 - 850 deployed

    def test_reinit_reuses_per_symbol_cache(self):
        budget = InvestmentBudget(
            initial_pot=1000.0,
            per_symbol={'BTC': 200.0},
        )
        v = compute_target_investment(
            budget=budget, symbol='BTC',
            usdt_free=15.0,  # would yield ~3 if recomputed
            investment_ratio=0.85, num_symbols=5,
        )
        assert v == 200.0  # cached, NOT recomputed

    def test_new_symbol_after_pot_snapshot_uses_pot(self):
        """A symbol that didn't init at startup (added later) should
        still get its slice of the *original* pot."""
        budget = InvestmentBudget(
            initial_pot=1000.0,
            per_symbol={'BTC': 170.0},
        )
        # Live free USDT is now small (most capital locked).
        v = compute_target_investment(
            budget=budget, symbol='ETH',
            usdt_free=20.0, investment_ratio=0.85, num_symbols=5,
        )
        # Should be derived from initial_pot, not from 20.0.
        assert v == pytest.approx(170.0)

    def test_handles_zero_free_first_call_does_not_snapshot(self):
        budget = InvestmentBudget()
        v = compute_target_investment(
            budget=budget, symbol='BTC',
            usdt_free=0.0, investment_ratio=0.85, num_symbols=5,
        )
        assert v == 0.0
        assert budget.initial_pot is None  # not snapshotted yet
        assert 'BTC' not in budget.per_symbol

        # Later, USDT arrives — the next call should snapshot and compute.
        v2 = compute_target_investment(
            budget=budget, symbol='BTC',
            usdt_free=1000.0, investment_ratio=0.85, num_symbols=5,
        )
        assert v2 == pytest.approx(170.0)
        assert budget.initial_pot == 1000.0

    def test_handles_zero_symbols(self):
        budget = InvestmentBudget()
        v = compute_target_investment(
            budget=budget, symbol='BTC',
            usdt_free=1000.0, investment_ratio=0.85, num_symbols=0,
        )
        # num_symbols clamped to 1 → 850
        assert v == pytest.approx(850.0)

    def test_negative_ratio_clamped(self):
        budget = InvestmentBudget()
        v = compute_target_investment(
            budget=budget, symbol='BTC',
            usdt_free=1000.0, investment_ratio=-0.5, num_symbols=5,
        )
        assert v == 0.0

    def test_investment_budget_default_per_symbol_is_independent(self):
        """Each ``InvestmentBudget()`` instance must have its own dict —
        no shared mutable default classic Python footgun."""
        b1 = InvestmentBudget()
        b2 = InvestmentBudget()
        b1.per_symbol['BTC'] = 1.0
        assert 'BTC' not in b2.per_symbol
