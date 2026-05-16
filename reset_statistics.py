#!/usr/bin/env python3
"""Reset trading statistics to start counting profit from today"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

def reset_statistics():
    state_file = "data/grid_live_balance.json"
    trades_file = "data/grid_live_trades.csv"
    
    print("="*70)
    print("🔄 СКИДАННЯ СТАТИСТИКИ")
    print("="*70)
    
    if not os.path.exists(state_file):
        print("❌ Файл статистики не знайдено")
        return
    
    with open(state_file, 'r') as f:
        state = json.load(f)
    
    initial_balance = state.get('initial_balance', 0)
    current_balance = state.get('total_value', 0)
    
    print(f"\n📊 Поточна статистика:")
    print(f"   Початковий баланс: ${initial_balance:.2f}")
    print(f"   Поточна вартість: ${current_balance:.2f}")
    print(f"   PnL: ${state.get('trading_pnl', 0):.2f}")
    
    backup_file = f"{state_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(state_file, backup_file)
    print(f"\n✅ Резервна копія: {backup_file}")
    
    now = datetime.utcnow().isoformat()
    
    new_state = {
        "initial_balance": current_balance,
        "initial_base_prices": state.get('initial_base_prices', {}),
        "start_time": now,
        "usdt_balance": state.get('usdt_balance', 0),
        "base_balances": state.get('base_balances', {}),
        "total_value": current_balance,
        "trading_pnl": 0.0,
        "holding_pnl": 0.0,
        "realized_pnl": 0.0,
        "total_fees_paid": 0.0,
        "total_trades": 0,
        "completed_cycles": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "win_rate": 0.0,
        "avg_profit_per_cycle": 0.0,
        "symbols": state.get('symbols', []),
        "last_update": now
    }
    
    with open(state_file, 'w') as f:
        json.dump(new_state, f, indent=2)
    
    print(f"\n✅ Оновлено {state_file}")
    print(f"   Новий початковий баланс: ${current_balance:.2f}")
    print(f"   Час старту: {now}")
    
    if os.path.exists(trades_file):
        backup_trades = f"{trades_file}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy(trades_file, backup_trades)
        
        with open(trades_file, 'w') as f:
            f.write("timestamp,symbol,side,price,amount,value,realized_pnl,unrealized_pnl,balance,total_value,roi_percent\n")
        
        print(f"✅ Очищено {trades_file}")
        print(f"   Резервна копія: {backup_trades}")
    
    print("\n" + "="*70)
    print("✅ СТАТИСТИКА СКИНУТА!")
    print("   Прибутки будуть рахуватися ВІД СЬОГОДНІ")
    print("="*70)

if __name__ == "__main__":
    reset_statistics()
