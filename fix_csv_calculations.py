#!/usr/bin/env python3
"""
Перерахунок Total Value в grid_trades.csv з правильною формулою.
Старий код використовував середню ціну grid рівнів для unrealized PnL,
новий використовує поточну ринкову ціну.
"""
import csv
import shutil
from datetime import datetime

trades_file = "data/grid_trades.csv"
backup_file = f"data/grid_trades_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# Бекап
shutil.copy(trades_file, backup_file)
print(f"✅ Backup created: {backup_file}")

# Читаємо всі угоди
with open(trades_file, 'r') as f:
    reader = csv.DictReader(f)
    trades = list(reader)

print(f"📊 Processing {len(trades)} trades...")

# Відстежуємо відкриті позиції та ціни
open_positions = {}
initial_balance = 1000.0

corrected_trades = []

for i, trade in enumerate(trades):
    symbol = trade['symbol']
    side = trade['side']
    price = float(trade['price'])
    amount = float(trade['amount'])
    value = float(trade['value'])
    
    # Оновлюємо позиції
    if symbol not in open_positions:
        open_positions[symbol] = []
    
    if side == 'BUY':
        open_positions[symbol].append({
            'price': price,
            'amount': amount,
            'value': value
        })
    elif side == 'SELL' and open_positions[symbol]:
        open_positions[symbol].pop(0)
    
    # Рахуємо правильний unrealized PnL (використовуючи поточну ціну як прокcі)
    total_unrealized = 0.0
    total_cost_basis = 0.0
    
    for sym, positions in open_positions.items():
        # Використовуємо поточну ціну trade якщо це той самий символ
        current_price = price if sym == symbol else 0
        
        for pos in positions:
            total_cost_basis += pos['value']
            if current_price > 0:
                total_unrealized += (current_price - pos['price']) * pos['amount']
    
    # Правильний розрахунок
    balance = float(trade['balance'])
    realized_pnl = float(trade['realized_pnl'])
    
    # Total Value = Balance + Cost Basis + Unrealized PnL
    correct_total_value = balance + total_cost_basis + total_unrealized
    correct_roi = ((correct_total_value - initial_balance) / initial_balance) * 100
    
    # Оновлюємо запис
    trade['unrealized_pnl'] = f"{total_unrealized}"
    trade['total_value'] = f"{correct_total_value}"
    trade['roi_percent'] = f"{correct_roi}"
    
    corrected_trades.append(trade)

# Записуємо виправлені дані
with open(trades_file, 'w', newline='') as f:
    if corrected_trades:
        writer = csv.DictWriter(f, fieldnames=corrected_trades[0].keys())
        writer.writeheader()
        writer.writerows(corrected_trades)

print(f"✅ Fixed {len(corrected_trades)} records")

# Показуємо останній запис
if corrected_trades:
    last = corrected_trades[-1]
    print(f"\n📈 Last trade:")
    print(f"  Balance: ${float(last['balance']):.2f}")
    print(f"  Total Value: ${float(last['total_value']):.2f}")
    print(f"  ROI: {float(last['roi_percent']):.2f}%")
    print(f"  Realized: ${float(last['realized_pnl']):.2f}")
    print(f"  Unrealized: ${float(last['unrealized_pnl']):.2f}")
