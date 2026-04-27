"""Step C tests:

* Item 4 — ``cause`` column wiring in ``GridLiveTrader._log_trade_from_exchange``
  and CSV header migration.
* Item 5 — ``analyze_slippage.py`` CLI report (collect_slippage_bps + main).
* Item 6 — ``GridConfig.get_grid_range_pct`` per-symbol overrides and
  ``MLGridAdvisor`` plumbing.
"""
from __future__ import annotations

import csv

import pytest

import analyze_slippage
from analyze_slippage import collect_slippage_bps
from config.settings import settings
from execution.grid_live import GridLiveTrader
from strategies.ml_grid_advisor import MLGridAdvisor


# --------------------------------------------------------------------------- #
# Item 4 — cause column                                                       #
# --------------------------------------------------------------------------- #
class TestCauseColumn:
    def _make_trader(self, tmp_path) -> GridLiveTrader:
        # Redirect data files into tmp before construction so __init__'s
        # CSV-header writer lands in the test's tmp dir.
        trader = GridLiveTrader.__new__(GridLiveTrader)
        # Mirror only the bits that ``_log_trade_from_exchange`` and
        # the header migration touch.
        trader._trades_file = str(tmp_path / "trades.csv")
        trader._fill_ids_file = str(tmp_path / "fills.json")
        trader._processed_trade_ids = set()
        trader._expected_prices = {}
        trader._order_causes = {}
        trader.realized_pnl = 0.0
        return trader

    def test_new_csv_has_cause_column(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from execution.grid_live import GridLiveTrader as Cls

        trader = Cls(symbols=["BTC/USDT"], testnet=True)
        with open(trader._trades_file, "r", newline="") as fh:
            header = next(csv.reader(fh))
        assert "cause" in header
        assert "expected_price" in header
        # Order: cause comes after expected_price (last two columns).
        assert header[-2:] == ["expected_price", "cause"]

    def test_log_writes_cause_when_known(self, tmp_path):
        trader = self._make_trader(tmp_path)
        # Seed the CSV header so the appender doesn't reject it.
        with open(trader._trades_file, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([
                "timestamp", "symbol", "side", "price", "amount", "value",
                "order_id", "status", "fee", "trading_pnl", "holding_pnl",
                "realized_pnl", "balance", "total_value", "base_held",
                "expected_price", "cause",
            ])

        trader._order_causes["abc123"] = "stop_loss"
        trader._expected_prices["abc123"] = 100.0

        trader._log_trade_from_exchange(
            symbol="BTC/USDT", side="sell", price=99.5, amount=0.01,
            value=0.995, order_id="abc123", fee=0.001,
            trading_pnl=-0.5, holding_pnl=0.0,
            balance=1000.0, total_value=1000.0, base_held=0.0,
        )

        with open(trader._trades_file, "r", newline="") as fh:
            row = list(csv.DictReader(fh))[0]
        assert row["cause"] == "stop_loss"
        assert row["expected_price"] != ""
        # Cache popped — second log without the tag must produce blank.
        assert "abc123" not in trader._order_causes
        assert "abc123" not in trader._expected_prices

    def test_log_writes_blank_cause_for_vanilla_grid_fill(self, tmp_path):
        trader = self._make_trader(tmp_path)
        with open(trader._trades_file, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([
                "timestamp", "symbol", "side", "price", "amount", "value",
                "order_id", "status", "fee", "trading_pnl", "holding_pnl",
                "realized_pnl", "balance", "total_value", "base_held",
                "expected_price", "cause",
            ])

        trader._log_trade_from_exchange(
            symbol="BTC/USDT", side="buy", price=100.0, amount=0.01,
            value=1.0, order_id="grid_fill_42", fee=0.001,
            trading_pnl=0.0, holding_pnl=0.0,
            balance=1000.0, total_value=1000.0, base_held=0.01,
        )
        with open(trader._trades_file, "r", newline="") as fh:
            row = list(csv.DictReader(fh))[0]
        assert row["cause"] == ""

    def test_legacy_header_migrated_to_include_cause(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Pre-Step-C CSV: has expected_price but no cause.
        import os as _os
        _os.makedirs("data", exist_ok=True)
        legacy = "data/grid_live_trades.csv"
        with open(legacy, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([
                "timestamp", "symbol", "side", "price", "amount", "value",
                "order_id", "status", "fee", "trading_pnl", "holding_pnl",
                "realized_pnl", "balance", "total_value", "base_held",
                "expected_price",
            ])
            w.writerow([
                "2024-01-01T00:00:00", "BTC/USDT", "buy", "100", "0.01", "1.0",
                "x1", "filled", "0.001", "0", "0", "0", "1000", "1000",
                "0.01", "100.0",
            ])

        GridLiveTrader(symbols=["BTC/USDT"], testnet=True)

        with open(legacy, "r", newline="") as fh:
            rows = list(csv.reader(fh))
        assert rows[0][-1] == "cause"
        assert rows[0][-2] == "expected_price"
        # Existing data row preserved (positional readers still work).
        assert rows[1][1] == "BTC/USDT"


# --------------------------------------------------------------------------- #
# Item 5 — analyze_slippage CLI                                               #
# --------------------------------------------------------------------------- #
class TestAnalyzeSlippage:
    def test_collect_filters_blank_expected_price(self):
        rows = [
            {"symbol": "BTC/USDT", "side": "buy",
             "expected_price": "100.0", "price": "100.5"},  # +50 bps adverse
            {"symbol": "BTC/USDT", "side": "buy",
             "expected_price": "", "price": "101.0"},  # no expected → skip
            {"symbol": "ETH/USDT", "side": "sell",
             "expected_price": "2000.0", "price": "1990.0"},  # +50 bps adverse
        ]
        out = collect_slippage_bps(rows)
        assert set(out.keys()) == {"BTC/USDT", "ETH/USDT"}
        assert out["BTC/USDT"] == [pytest.approx(50.0)]
        assert out["ETH/USDT"] == [pytest.approx(50.0)]

    def test_collect_skips_unparseable_rows(self):
        rows = [
            {"symbol": "BTC/USDT", "side": "buy",
             "expected_price": "abc", "price": "100"},  # bad expected
            {"symbol": "BTC/USDT", "side": "",
             "expected_price": "100", "price": "100"},  # blank side
            {"symbol": "", "side": "buy",
             "expected_price": "100", "price": "100"},  # blank symbol
            {"symbol": "BTC/USDT", "side": "buy",
             "expected_price": "0", "price": "100"},  # zero expected → bps None
        ]
        out = collect_slippage_bps(rows)
        assert out == {}

    def test_main_missing_file_exits_nonzero(self, tmp_path, capsys):
        rc = analyze_slippage.main(["--file", str(tmp_path / "nope.csv")])
        assert rc == 1
        err = capsys.readouterr().err
        assert "not found" in err.lower()

    def test_main_no_expected_column_exits_nonzero(self, tmp_path, capsys):
        path = tmp_path / "live.csv"
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "symbol", "side", "price"])
            w.writerow(["2024-01-01", "BTC/USDT", "buy", "100"])
        rc = analyze_slippage.main(["--file", str(path)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "expected_price" in err

    def test_main_happy_path_prints_overall_and_symbols(self, tmp_path, capsys):
        path = tmp_path / "live.csv"
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "symbol", "side", "price", "expected_price"])
            w.writerow(["t1", "BTC/USDT", "buy", "100.5", "100.0"])
            w.writerow(["t2", "BTC/USDT", "sell", "99.5", "100.0"])  # +50 bps adverse
            w.writerow(["t3", "ETH/USDT", "buy", "2000", "2000"])    # 0 bps
        rc = analyze_slippage.main(["--file", str(path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OVERALL" in out
        assert "BTC/USDT" in out
        assert "ETH/USDT" in out


# --------------------------------------------------------------------------- #
# Item 6 — per-symbol grid_range_pct                                          #
# --------------------------------------------------------------------------- #
class TestPerSymbolGridRange:
    def test_default_falls_back_to_global(self):
        assert settings.grid.get_grid_range_pct("UNKNOWN/USDT") == \
            settings.grid.grid_range_pct

    def test_override_returned_for_known_symbol(self, monkeypatch):
        monkeypatch.setattr(
            settings.grid, "grid_range_pct_overrides",
            {"DOGE/USDT": 0.04, "BTC/USDT": 0.015},
        )
        assert settings.grid.get_grid_range_pct("DOGE/USDT") == pytest.approx(0.04)
        assert settings.grid.get_grid_range_pct("BTC/USDT") == pytest.approx(0.015)
        # Unknown still falls back to global.
        assert settings.grid.get_grid_range_pct("XRP/USDT") == \
            settings.grid.grid_range_pct

    def test_default_advice_uses_per_symbol_override(self, monkeypatch):
        monkeypatch.setattr(
            settings.grid, "grid_range_pct_overrides",
            {"DOGE/USDT": 0.045},
        )
        advisor = MLGridAdvisor()
        # ``insufficient data`` path goes through ``_default_advice``.
        advice = advisor.get_advice("DOGE/USDT", ohlcv_df=None)
        assert advice.grid_range_pct == pytest.approx(0.045)
        # Unknown symbol uses the global default.
        advice2 = advisor.get_advice("BTC/USDT", ohlcv_df=None)
        assert advice2.grid_range_pct == pytest.approx(settings.grid.grid_range_pct)

    def test_compute_grid_params_honours_base_range(self):
        advisor = MLGridAdvisor()
        vol = {
            "atr_pct": 0.02, "bb_width": 0.04, "vol_ratio": 1.0,
            "price_range_24h": 0.02,
        }
        trend = {"trend_score": 0.0}
        a = advisor._compute_grid_params(vol, trend, ml_confidence=0.0,
                                         ml_direction=0.0, base_range=0.02)
        b = advisor._compute_grid_params(vol, trend, ml_confidence=0.0,
                                         ml_direction=0.0, base_range=0.04)
        # Higher base_range must produce wider grid_range_pct (40% weight).
        assert b.grid_range_pct >= a.grid_range_pct
