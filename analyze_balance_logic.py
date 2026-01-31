#!/usr/bin/env python3

import csv

def analyze_balance_logic():
    print("🔍 Аналіз логіки балансу та total_value\n")
    
    with open('data/grid_trades.csv', 'r') as f:
        reader = csv.DictReader(f)
        trades = list(reader)
    
    initial_balance = 2000.0
    current_balance = initial_balance
    realized_pnl = 0.0
    positions = {}
    
    print("🧮 Аналіз кількох перших операцій:")
    print("=" * 120)
    
    for i, trade in enumerate(trades[:10]):
        symbol = trade['symbol']
        side = trade['side']
        price = float(trade['price'])
        amount = float(trade['amount'])
        value = float(trade['value'])
        csv_balance = float(trade['balance'])
        csv_realized = float(trade['realized_pnl'])
        csv_total_value = float(trade['total_value'])
        
        old_balance = current_balance
        
        if side == 'BUY':
            current_balance -= value
            if symbol not in positions:
                positions[symbol] = []
            positions[symbol].append({"price": price, "amount": amount, "value": value})
        else:  # SELL
            current_balance += value
            if symbol in positions and positions[symbol]:
                pos = positions[symbol].pop(0)
                profit = value - pos["value"]  # Різниця між SELL і BUY вартістю
                realized_pnl += profit
        
        # Підрахунок вартості відкритих позицій за ціною покупки
        total_position_cost = 0.0
        for pos_list in positions.values():
            for pos in pos_list:
                total_position_cost += pos["value"]
        
        expected_total_value = current_balance + total_position_cost
        
        print(f"{i+1:2d}. {symbol:8} {side:4} ${value:6.2f}")
        print(f"    Баланс:        ${old_balance:8.2f} → ${current_balance:8.2f} (CSV: ${csv_balance:8.2f})")
        print(f"    Позиції:       ${total_position_cost:8.2f}")
        print(f"    Expected Total: ${expected_total_value:8.2f} (CSV: ${csv_total_value:8.2f})")
        print(f"    Realized PnL:   ${realized_pnl:8.2f} (CSV: ${csv_realized:8.2f})")
        
        balance_match = abs(current_balance - csv_balance) < 0.01
        total_match = abs(expected_total_value - csv_total_value) < 0.01
        
        print(f"    ✅ Balance: {balance_match} | Total: {total_match}")
        print()
        
        if i >= 9:
            break
    
    print("\n💡 ВИСНОВОК:")
    print("• balance = готівка (зменшується при BUY, збільшується при SELL)")
    print("• total_value = balance + вартість_відкритих_позицій_за_поточними_цінами")
    print("• realized_pnl = сума прибутків від закритих позицій")
    print("• unrealized_pnl = різниця між поточною ціною та ціною покупки для відкритих позицій")
    
    print(f"\n🎯 КЛЮЧОВЕ РОЗУМІННЯ:")
    print("Формула 'initial_balance + realized_pnl + unrealized_pnl = total_value' НЕ правильна!")
    print("Правильна формула: total_value = balance + market_value_of_open_positions")
    print("Де balance вже включає realized PnL через операції BUY/SELL")

if __name__ == "__main__":
    analyze_balance_logic()