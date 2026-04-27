#!/usr/bin/env python3
"""
Перерахунок останнього запису в CSV з реальними поточними цінами.

Math (FIFO replay + unrealized-from-positions) lives in
:mod:`analytics.pnl_recompute`; this script only handles the live-price
fetch and the CSV write-back.
"""
import csv
import yfinance as yf

from analytics.pnl_recompute import recompute_trades, unrealized_from_positions

trades_file = "data/grid_trades.csv"

# Читаємо всі угоди
with open(trades_file, 'r') as f:
    reader = csv.DictReader(f)
    trades = list(reader)

# Replay FIFO to get the residual position book.
result = recompute_trades(trades, initial_balance=1000.0)
open_positions = result.positions

# Отримуємо поточні ціни
symbols_map = {
    'BTC/USDT': 'BTC-USD',
    'ETH/USDT': 'ETH-USD',
    'SOL/USDT': 'SOL-USD',
    'DOGE/USDT': 'DOGE-USD'
}

print("📡 Fetching current prices...")
current_prices = {}
for symbol, yf_symbol in symbols_map.items():
    try:
        ticker = yf.Ticker(yf_symbol)
        data = ticker.history(period='1d', interval='1h')
        if not data.empty:
            current_prices[symbol] = data['Close'].iloc[-1]
            print(f"  {symbol}: ${current_prices[symbol]:,.2f}")
    except Exception as e:
        print(f"  ❌ {symbol}: {e}")

# Mark the residual positions to live quotes via the shared helper.
total_unrealized, total_cost_basis = unrealized_from_positions(
    open_positions, current_prices
)

print("\n💼 Open positions:")
for symbol, lots in open_positions.items():
    if not lots:
        continue
    current_price = current_prices.get(symbol, 0) or 0
    symbol_cost = sum(lot.price * lot.amount for lot in lots)
    symbol_unrealized = (
        sum((current_price - lot.price) * lot.amount for lot in lots)
        if current_price > 0
        else 0.0
    )
    print(
        f"  {symbol}: {len(lots)} positions, Cost: ${symbol_cost:.2f}, "
        f"PnL: ${symbol_unrealized:+.2f}"
    )

# Оновлюємо останній запис
last_trade = trades[-1]
balance = float(last_trade['balance'])
realized_pnl = float(last_trade['realized_pnl'])
initial_balance = 1000.0

correct_total_value = balance + total_cost_basis + total_unrealized
correct_roi = ((correct_total_value - initial_balance) / initial_balance) * 100

print(f"\n📊 Correct calculation:")
print(f"  Balance: ${balance:.2f}")
print(f"  Cost Basis: ${total_cost_basis:.2f}")
print(f"  Unrealized PnL: ${total_unrealized:+.2f}")
print(f"  Total Value: ${correct_total_value:.2f}")
print(f"  ROI: {correct_roi:+.2f}%")

# Оновлюємо останній запис
last_trade['unrealized_pnl'] = str(total_unrealized)
last_trade['total_value'] = str(correct_total_value)
last_trade['roi_percent'] = str(correct_roi)

# Записуємо назад
with open(trades_file, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=trades[0].keys())
    writer.writeheader()
    writer.writerows(trades)

print(f"\n✅ Updated last record in {trades_file}")
