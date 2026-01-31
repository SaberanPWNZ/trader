#!/usr/bin/env python3

import csv
import json
from datetime import datetime

def recalculate_with_correct_formula():
    print("🔄 Перерахунок grid_trades.csv з правильною формулою total_value\n")
    
    try:
        with open('data/grid_trades.csv', 'r') as f:
            reader = csv.DictReader(f)
            trades = list(reader)
        print(f"📊 Завантажено {len(trades)} записів\n")
    except Exception as e:
        print(f"❌ Помилка читання CSV: {e}")
        return
    
    initial_balance = 2000.0
    current_balance = initial_balance
    realized_pnl = 0.0
    positions = {}  # symbol -> list of {"price": float, "amount": float}
    
    corrected_trades = []
    
    print("🧮 Перерахунок кожної операції:")
    print("=" * 100)
    
    for i, trade in enumerate(trades):
        symbol = trade['symbol']
        side = trade['side']
        price = float(trade['price'])
        amount = float(trade['amount'])
        value = float(trade['value'])
        
        # Оновлюємо баланс
        if side == 'BUY':
            current_balance -= value
            # Додаємо позицію
            if symbol not in positions:
                positions[symbol] = []
            positions[symbol].append({"price": price, "amount": amount})
        else:  # SELL
            current_balance += value
            # Закриваємо позицію та рахуємо реалізований прибуток
            if symbol in positions and positions[symbol]:
                pos = positions[symbol].pop(0)
                profit = (price - pos["price"]) * pos["amount"]
                realized_pnl += profit
        
        # Рахуємо нереалізований PnL (приблизно, використовуючи поточну ціну як ринкову)
        unrealized_pnl = 0.0
        total_cost_basis = 0.0
        
        for pos_symbol, pos_list in positions.items():
            for pos in pos_list:
                cost_basis = pos["price"] * pos["amount"]
                total_cost_basis += cost_basis
                # Для спрощення використовуємо останню ціну транзакції як ринкову
                if pos_symbol == symbol:
                    market_value = price * pos["amount"]
                    unrealized_pnl += market_value - cost_basis
                else:
                    # Для інших символів використовуємо ціну входу (нуль нереалізованого PnL)
                    pass
        
        # Правильна формула: total_value = balance + total_cost_basis + unrealized_pnl
        total_value = current_balance + total_cost_basis + unrealized_pnl
        roi_percent = ((total_value - initial_balance) / initial_balance) * 100
        
        corrected_trade = {
            'timestamp': trade['timestamp'],
            'symbol': symbol,
            'side': side,
            'price': price,
            'amount': amount,
            'value': value,
            'realized_pnl': round(realized_pnl, 10),
            'unrealized_pnl': round(unrealized_pnl, 10),
            'balance': round(current_balance, 10),
            'total_value': round(total_value, 10),
            'roi_percent': round(roi_percent, 10)
        }
        corrected_trades.append(corrected_trade)
        
        print(f"{i+1:2d}. {symbol:8} {side:4} | Balance: ${current_balance:8.2f} | Cost: ${total_cost_basis:8.2f} | Unrealized: ${unrealized_pnl:6.2f} | Total: ${total_value:8.2f}")
    
    # Зберігаємо виправлені дані
    print("\n💾 Зберігаємо виправлені дані...")
    
    # Backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f'data/grid_trades_backup_{timestamp}.csv'
    
    with open(backup_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'symbol', 'side', 'price', 'amount', 'value',
            'realized_pnl', 'unrealized_pnl', 'balance', 'total_value', 'roi_percent'
        ])
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade)
    
    print(f"📦 Створено backup: {backup_file}")
    
    # Оновлюємо оригінальний файл
    with open('data/grid_trades.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'symbol', 'side', 'price', 'amount', 'value',
            'realized_pnl', 'unrealized_pnl', 'balance', 'total_value', 'roi_percent'
        ])
        writer.writeheader()
        writer.writerows(corrected_trades)
    
    print("✅ grid_trades.csv оновлено!")
    
    final_trade = corrected_trades[-1]
    print(f"\n📋 ПІДСУМОК:")
    print(f"💰 Баланс готівки:       ${final_trade['balance']:.2f}")
    print(f"📈 Реалізований PnL:     ${final_trade['realized_pnl']:.2f}")  
    print(f"📊 Нереалізований PnL:   ${final_trade['unrealized_pnl']:.2f}")
    print(f"💎 Загальна вартість:    ${final_trade['total_value']:.2f}")
    print(f"📊 ROI:                  {final_trade['roi_percent']:.2f}%")
    
    print(f"\n✅ Перевірка формули:")
    print(f"Початковий баланс + Реалізований PnL + Нереалізований PnL")
    print(f"${initial_balance:.2f} + ${final_trade['realized_pnl']:.2f} + ${final_trade['unrealized_pnl']:.2f}")
    print(f"= ${initial_balance + final_trade['realized_pnl'] + final_trade['unrealized_pnl']:.2f}")
    print(f"💎 Total Value: ${final_trade['total_value']:.2f}")

if __name__ == "__main__":
    recalculate_with_correct_formula()