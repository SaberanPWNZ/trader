#!/usr/bin/env python3
import csv
import shutil
from datetime import datetime

def fix_balance_calculations():
    trades_file = "data/grid_trades.csv"
    backup_file = f"data/grid_trades_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    shutil.copy(trades_file, backup_file)
    print(f"✅ Backup created: {backup_file}")
    
    with open(trades_file, 'r') as f:
        reader = csv.DictReader(f)
        trades = list(reader)
    
    initial_balance = 1000.0
    current_balance = initial_balance
    realized_pnl = 0.0
    
    positions = {}
    current_prices = {}
    
    corrected_trades = []
    
    for trade in trades:
        symbol = trade['symbol']
        side = trade['side']
        price = float(trade['price'])
        amount = float(trade['amount'])
        value = float(trade['value'])
        
        if side == 'BUY':
            current_balance -= value
            if symbol not in positions:
                positions[symbol] = []
            positions[symbol].append({
                'price': price,
                'amount': amount
            })
        else:
            if symbol in positions and positions[symbol]:
                current_balance += value
                pos = positions[symbol].pop(0)
                profit = (price - pos['price']) * pos['amount']
                realized_pnl += profit
        
        current_prices[symbol] = price
        
        unrealized_pnl = 0.0
        total_cost_basis = 0.0
        
        for pos_symbol, pos_list in positions.items():
            market_price = current_prices.get(pos_symbol, 0)
            for pos in pos_list:
                cost = pos['price'] * pos['amount']
                total_cost_basis += cost
                if market_price > 0:
                    unrealized_pnl += (market_price - pos['price']) * pos['amount']
        
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
    
    with open(trades_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'symbol', 'side', 'price', 'amount', 'value',
            'realized_pnl', 'unrealized_pnl', 'balance', 'total_value', 'roi_percent'
        ])
        writer.writeheader()
        writer.writerows(corrected_trades)
    
    print(f"✅ Виправлено {len(corrected_trades)} записів")
    
    last = corrected_trades[-1]
    print(f"\n📊 Підсумок після виправлення:")
    print(f"💰 Balance (готівка):    ${last['balance']:.2f}")
    print(f"📈 Realized PnL:         ${last['realized_pnl']:.2f}")
    print(f"📊 Unrealized PnL:       ${last['unrealized_pnl']:.2f}")
    print(f"💎 Total Value:          ${last['total_value']:.2f}")
    print(f"📊 ROI:                  {last['roi_percent']:.2f}%")
    
    print(f"\n🔍 Відкриті позиції:")
    total_cost = 0
    for symbol, pos_list in positions.items():
        if pos_list:
            cost = sum(p['price'] * p['amount'] for p in pos_list)
            total_cost += cost
            print(f"  {symbol}: {len(pos_list)} позицій, вартість: ${cost:.2f}")
    
    print(f"\n✅ Перевірка: Balance + Cost Basis = ${last['balance']:.2f} + ${total_cost:.2f} = ${last['balance'] + total_cost:.2f}")

if __name__ == "__main__":
    fix_balance_calculations()
