#!/usr/bin/env python3
"""
Показує детальну статистику торгівлі з розділенням Trading PnL та Holding PnL
"""
import json
import os
import pandas as pd
from datetime import datetime

def show_stats():
    state_file = "data/grid_live_balance.json"
    trades_file = "data/grid_live_trades.csv"
    
    print("="*80)
    print("📊 ДЕТАЛЬНА СТАТИСТИКА ТОРГІВЛІ")
    print("="*80)
    
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            state = json.load(f)
        
        initial = state.get('initial_balance', 0)
        initial_eth_price = state.get('initial_eth_price', 0)
        current_eth_price = state.get('eth_price', 0)
        total_value = state.get('total_value', 0)
        trading_pnl = state.get('trading_pnl', 0)
        holding_pnl = state.get('holding_pnl', 0)
        realized_pnl = state.get('realized_pnl', 0)
        total_fees = state.get('total_fees_paid', 0)
        
        cycles = state.get('completed_cycles', 0)
        wins = state.get('winning_trades', 0)
        losses = state.get('losing_trades', 0)
        win_rate = state.get('win_rate', 0)
        avg_profit = state.get('avg_profit_per_cycle', 0)
        
        eth_balance = state.get('eth_balance', 0)
        usdt_balance = state.get('usdt_balance', 0)
        
        eth_price_change = ((current_eth_price - initial_eth_price) / initial_eth_price * 100) if initial_eth_price > 0 else 0
        total_pnl = total_value - initial
        total_pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0
        
        print("\n💵 ПРИБУТКИ:")
        print(f"  Trading PnL:  ${trading_pnl:+10.2f}  (прибуток від торгівлі)")
        print(f"  Holding PnL:  ${holding_pnl:+10.2f}  (зміна через ціну ETH)")
        print(f"  Fees Paid:    ${-total_fees:10.2f}")
        print(f"  {'─'*45}")
        print(f"  Total PnL:    ${total_pnl:+10.2f}  ({total_pnl_pct:+.2f}%)")
        
        print("\n📈 ТОРГІВЛЯ:")
        print(f"  Completed Cycles:    {cycles}")
        print(f"  Winning Trades:      {wins} ({win_rate:.1f}%)")
        print(f"  Losing Trades:       {losses}")
        print(f"  Avg Profit/Cycle:    ${avg_profit:+.2f}")
        
        print("\n💰 БАЛАНС:")
        print(f"  Initial Balance:     ${initial:,.2f}")
        print(f"  Current Balance:     ${total_value:,.2f}")
        print(f"  USDT:                ${usdt_balance:,.2f}")
        print(f"  ETH:                 {eth_balance:.6f} ETH (${eth_balance * current_eth_price:.2f})")
        
        print("\n📊 ЦІНА ETH:")
        print(f"  Start Price:         ${initial_eth_price:.2f}")
        print(f"  Current Price:       ${current_eth_price:.2f}")
        print(f"  Price Change:        {eth_price_change:+.2f}%")
        
        print("\n" + "="*80)
        print("📌 ПОЯСНЕННЯ:")
        print("="*80)
        print("• Trading PnL  = Реальний прибуток від купівлі-продажу (мінус комісії)")
        print("• Holding PnL  = Зміна вартості через зростання/падіння ціни ETH")
        print("• Total PnL    = Trading PnL + Holding PnL")
        print("• Win Rate     = Відсоток прибуткових циклів (купівля → продаж)")
        print("\n✅ Trading PnL показує РЕАЛЬНИЙ заробіток від торгової стратегії")
        print("   (не залежить від того, чи зросла ціна ETH чи впала)")
        
    else:
        print("\n❌ Файл статистики не знайдено")
    
    if os.path.exists(trades_file):
        print("\n" + "="*80)
        print("📝 ОСТАННІ ТРЕЙДИ:")
        print("="*80)
        
        df = pd.read_csv(trades_file)
        if not df.empty:
            last_trades = df.tail(10)
            print(f"\nПоказано останні {len(last_trades)} трейдів:")
            print()
            
            for _, trade in last_trades.iterrows():
                ts = datetime.fromisoformat(trade['timestamp'].replace('Z', '')).strftime('%m-%d %H:%M')
                side = trade['side']
                price = float(trade['price'])
                amount = float(trade['amount'])
                
                if 'trading_pnl' in trade and pd.notna(trade['trading_pnl']):
                    trading_pnl = float(trade['trading_pnl'])
                    side_emoji = "🔴" if side == 'SELL' else "🟢"
                    pnl_str = f"PnL: ${trading_pnl:+.2f}" if side == 'SELL' else ""
                    print(f"  {side_emoji} {ts} | {side:4s} | {amount:.6f} ETH @ ${price:7.2f} | {pnl_str}")
                else:
                    side_emoji = "🔴" if side == 'SELL' else "🟢"
                    print(f"  {side_emoji} {ts} | {side:4s} | {amount:.6f} ETH @ ${price:7.2f}")
        else:
            print("\n❌ Ще немає трейдів")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    show_stats()
