#!/usr/bin/env python3

import csv
import json

def verify_balance_calculations():
    print("🔍 Детальна перевірка розрахунків балансу\n")
    
    try:
        with open('data/grid_trades.csv', 'r') as f:
            reader = csv.DictReader(f)
            trades = list(reader)
        print(f"📊 Завантажено {len(trades)} записів з grid_trades.csv\n")
    except Exception as e:
        print(f"❌ Помилка читання CSV: {e}")
        return
    
    try:
        with open('grid_state.json', 'r') as f:
            state = json.load(f)
            initial_balance = state.get('initial_balance', 2000)
    except:
        initial_balance = 2000
    
    print(f"💰 Початковий баланс: ${initial_balance}")
    
    current_balance = initial_balance
    print("\n📈 Перевірка кожної операції:")
    print("=" * 80)
    
    for i, trade in enumerate(trades):
        old_balance = current_balance
        value = float(trade['value'])
        
        if trade['side'] == 'BUY':
            current_balance -= value
            operation = f"BUY  - віднімаємо ${value:.2f}"
        else:
            current_balance += value
            operation = f"SELL + додаємо    ${value:.2f}"
        
        csv_balance = float(trade['balance'])
        balance_diff = abs(current_balance - csv_balance)
        
        if balance_diff > 0.01:
            status = "❌ ПОМИЛКА"
        else:
            status = "✅"
        
        print(f"{i+1:2d}. {trade['symbol']:8} {operation} | Було: ${old_balance:8.2f} → Стало: ${current_balance:8.2f} | CSV: ${csv_balance:8.2f} {status}")
        
        if balance_diff > 0.01:
            print(f"    🚨 Різниця: ${balance_diff:.4f}")
    
    print("=" * 80)
    
    final_trade = trades[-1]
    balance = float(final_trade['balance'])
    realized_pnl = float(final_trade['realized_pnl'])
    unrealized_pnl = float(final_trade['unrealized_pnl'])
    total_value = float(final_trade['total_value'])
    roi_percent = float(final_trade['roi_percent'])
    
    print(f"\n📋 ПІДСУМОК (останній рядок CSV):")
    print(f"💰 Баланс готівки:     ${balance:.2f}")
    print(f"📈 Реалізований PnL:   ${realized_pnl:.2f}")
    print(f"📊 Нереалізований PnL: ${unrealized_pnl:.2f}")
    print(f"💎 Загальна вартість:  ${total_value:.2f}")
    print(f"📊 ROI:                {roi_percent:.2f}%")
    
    print(f"\n🧮 МАТЕМАТИЧНА ПЕРЕВІРКА:")
    total_in_trades = (balance - initial_balance)
    print(f"Вкладено в відкриті позиції: ${-total_in_trades:.2f}")
    print(f"Реалізований прибуток/збиток: ${realized_pnl:.2f}")
    print(f"Нереалізований прибуток/збиток: ${unrealized_pnl:.2f}")
    
    expected_total = initial_balance + realized_pnl + unrealized_pnl
    actual_total = total_value
    
    print(f"\n🎯 ПЕРЕВІРКА ФОРМУЛИ:")
    print(f"Початковий баланс:      ${initial_balance:.2f}")
    print(f"+ Реалізований PnL:     ${realized_pnl:.2f}")
    print(f"+ Нереалізований PnL:   ${unrealized_pnl:.2f}")
    print(f"= Очікувана вартість:   ${expected_total:.2f}")
    print(f"Фактична вартість CSV:  ${actual_total:.2f}")
    
    diff = abs(expected_total - actual_total)
    if diff < 0.01:
        print(f"✅ ФОРМУЛА ПРАВИЛЬНА! Різниця: ${diff:.4f}")
    else:
        print(f"❌ ПОМИЛКА В ФОРМУЛІ! Різниця: ${diff:.4f}")
    
    print(f"\n💡 ПОЯСНЕННЯ ЛОГІКИ:")
    print(f"• BUY операції: віднімаємо з готівки (balance -= value)")
    print(f"• SELL операції: додаємо до готівки (balance += value)")
    print(f"• total_value = balance + вартість позицій")
    print(f"• ROI = (total_value - initial_balance) / initial_balance * 100%")

if __name__ == "__main__":
    verify_balance_calculations()