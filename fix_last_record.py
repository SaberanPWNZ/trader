#!/usr/bin/env python3
"""
Перерахунок останнього запису в CSV з реальними поточними цінами
"""
import csv
import yfinance as yf
from datetime import datetime

trades_file = "data/grid_trades.csv"

# Читаємо всі угоди
with open(trades_file, 'r') as f:
    reader = csv.DictReader(f)
    trades = list(reader)

# Знаходимо відкриті позиції
open_positions = {}
for trade in trades:
    symbol = trade['symbol']
    if symbol not in open_positions:
        open_positions[symbol] = []
    
    if trade['side'] == 'BUY':
        open_positions[symbol].append({
            'price': float(trade['price']),
            'amount': float(trade['amount']),
            'value': float(trade['value'])
        })
    elif trade['side'] == 'SELL' and open_positions[symbol]:
        open_positions[symbol].pop(0)

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

# Рахуємо unrealized PnL з поточними цінами
total_unrealized = 0.0
total_cost_basis = 0.0

print("\n💼 Open positions:")
for symbol, positions in open_positions.items():
    if not positions:
        continue
    
    current_price = current_prices.get(symbol, 0)
    symbol_unrealized = 0.0
    symbol_cost = 0.0
    
    for pos in positions:
        symbol_cost += pos['value']
        if current_price > 0:
            pnl = (current_price - pos['price']) * pos['amount']
            symbol_unrealized += pnl
    
    total_cost_basis += symbol_cost
    total_unrealized += symbol_unrealized
    
    print(f"  {symbol}: {len(positions)} positions, Cost: ${symbol_cost:.2f}, PnL: ${symbol_unrealized:+.2f}")

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
