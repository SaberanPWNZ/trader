#!/usr/bin/env python3
import pandas as pd
from datetime import datetime
import sys

def analyze_grid():
    try:
        trades = pd.read_csv('data/grid_trades.csv')
        trades['timestamp'] = pd.to_datetime(trades['timestamp'])
    except FileNotFoundError:
        print("❌ Grid trades file not found!")
        sys.exit(1)
    
    if len(trades) == 0:
        print("📊 No trades yet!")
        return
    
    initial_balance = 100.0
    latest = trades.iloc[-1]
    
    print("\n╔════════════════════════════════════════╗")
    print("║     GRID TRADING DAILY SUMMARY         ║")
    print("╠════════════════════════════════════════╣")
    print(f"║ 💰 Initial Balance: ${initial_balance:.2f}           ║")
    print(f"║ 📈 Realized PnL:    ${latest['realized_pnl']:.2f}           ║")
    print(f"║ 📊 Unrealized PnL:  ${latest['unrealized_pnl']:.2f}          ║")
    print("╠════════════════════════════════════════╣")
    
    real_value = initial_balance + latest['realized_pnl'] + latest['unrealized_pnl']
    real_roi = ((real_value - initial_balance) / initial_balance) * 100
    
    print(f"║ 💵 Current Value:   ${real_value:.2f}          ║")
    print(f"║ 📉 ROI:             {real_roi:+.2f}%            ║")
    print("╠════════════════════════════════════════╣")
    print(f"║ 🔄 Total Trades:    {len(trades):<16} ║")
    
    runtime_hours = (trades['timestamp'].max() - trades['timestamp'].min()).total_seconds() / 3600
    print(f"║ ⏱  Runtime:         {runtime_hours:.1f}h{' '*(15-len(f'{runtime_hours:.1f}h'))} ║")
    print("╚════════════════════════════════════════╝\n")
    
    print("📋 TRADE BREAKDOWN:")
    btc_trades = len(trades[trades['symbol'] == 'BTC/USDT'])
    eth_trades = len(trades[trades['symbol'] == 'ETH/USDT'])
    buy_trades = len(trades[trades['side'] == 'BUY'])
    sell_trades = len(trades[trades['side'] == 'SELL'])
    
    print(f"  BTC/USDT: {btc_trades} trades")
    print(f"  ETH/USDT: {eth_trades} trades")
    print(f"  BUY:      {buy_trades} trades")
    print(f"  SELL:     {sell_trades} trades")
    
    closed_pairs = min(buy_trades, sell_trades)
    if closed_pairs > 0:
        avg_profit = latest['realized_pnl'] / closed_pairs
        print(f"\n💹 PERFORMANCE:")
        print(f"  Closed pairs: {closed_pairs}")
        print(f"  Avg profit per pair: ${avg_profit:.4f}")
    
    print(f"\n📊 LAST 10 TRADES:")
    for idx, trade in trades.tail(10).iterrows():
        emoji = "🟢" if trade['side'] == 'BUY' else "🔴"
        symbol = trade['symbol'].replace('/USDT', '')
        print(f"  {emoji} {trade['side']:<4} {symbol:<3} ${trade['price']:.2f} | "
              f"Total: ${trade['total_value']:.2f} ({trade['roi_percent']:+.2f}%)")
    
    try:
        snapshots = pd.read_csv('data/grid_snapshots.csv')
        if len(snapshots) > 0:
            print(f"\n📈 SCHEDULED REPORTS: {len(snapshots)}")
            snapshots['timestamp'] = pd.to_datetime(snapshots['timestamp'])
            for idx, snap in snapshots.iterrows():
                time = snap['timestamp'].strftime('%Y-%m-%d %H:%M')
                print(f"  {snap['report_type']:<4} | {time} | "
                      f"${snap['total_value']:.2f} ({snap['roi_percent']:+.2f}%)")
    except FileNotFoundError:
        pass
    
    print()

if __name__ == "__main__":
    analyze_grid()
