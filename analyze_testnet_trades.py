#!/usr/bin/env python3
import asyncio
import json
import os
from datetime import datetime
from exchange.factory import create_exchange

async def fetch_all_trades(ex, symbol):
    all_trades = []
    since = None
    for _ in range(10):
        trades = await ex.fetch_my_trades(symbol, since=since, limit=1000)
        if not trades:
            break
        all_trades.extend(trades)
        if len(trades) < 100:
            break
        since = trades[-1]['timestamp'] + 1
    return all_trades

async def analyze_testnet_trades():
    ex = create_exchange(testnet=True)
    await ex.connect()
    
    all_trades = await fetch_all_trades(ex, 'ETH/USDT')
    
    balance = await ex.fetch_balance()
    ticker = await ex.fetch_ticker('ETH/USDT')
    eth_price = ticker['last']
    
    usdt_total = balance.get('USDT', {}).get('total', 0)
    eth_total = balance.get('ETH', {}).get('total', 0)
    eth_value = eth_total * eth_price
    total_value = usdt_total + eth_value
    
    state_file = "data/grid_live_balance.json"
    initial = 10000.0
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            state = json.load(f)
            initial = state.get("initial_balance", 10000.0)
    
    await ex.disconnect()
    
    buys = [t for t in all_trades if t['side'] == 'buy']
    sells = [t for t in all_trades if t['side'] == 'sell']
    
    print("\n╔════════════════════════════════════════════════════════════╗")
    print("║         📊 АНАЛІЗ TESTNET TRADES (GRID TRADING)            ║")
    print("╠════════════════════════════════════════════════════════════╣")
    print(f"║  Total Trades: {len(all_trades):>5}                                     ║")
    print(f"║  BUY trades:   {len(buys):>5}                                     ║")
    print(f"║  SELL trades:  {len(sells):>5}                                     ║")
    print("╠════════════════════════════════════════════════════════════╣")
    print(f"║  Initial Balance:  ${initial:>10,.2f}                       ║")
    print(f"║  Current USDT:     ${usdt_total:>10,.2f}                       ║")
    print(f"║  Current ETH:      {eth_total:>10.4f} ETH                    ║")
    print(f"║  ETH Value:        ${eth_value:>10,.2f}                       ║")
    print(f"║  Total Value:      ${total_value:>10,.2f}                       ║")
    print(f"║  Total PnL:        ${total_value - initial:>+10,.2f} ({(total_value - initial) / initial * 100:+.2f}%)     ║")
    print("╚════════════════════════════════════════════════════════════╝")
    
    print("\n💡 ПЕРШІ 10 TRADES (для перевірки):")
    print("=" * 80)
    first_10 = all_trades[:10]
    for i, t in enumerate(first_10, 1):
        side_icon = "🟢" if t['side'] == 'buy' else "🔴"
        ts = datetime.fromtimestamp(t['timestamp']/1000).strftime('%m-%d %H:%M:%S')
        print(f"{i:2d}. {side_icon} {t['side'].upper():4} {t['amount']:.4f} ETH @ ${t['price']:.2f} = ${t['cost']:.2f} ({ts})")
    
    print("\n🔍 АНАЛІЗ ПАРНИХ УГОД (ПРАВИЛЬНИЙ FIFO MATCHING):")
    print("=" * 80)
    
    all_trades_sorted = sorted(all_trades, key=lambda x: x['timestamp'])
    
    buy_positions = []
    total_realized_pnl = 0.0
    total_fees = 0.0
    matched_pairs = 0
    trade_details = []
    
    for trade in all_trades_sorted:
        fee = trade.get('fee', {}).get('cost', 0) if trade.get('fee') else 0
        total_fees += fee
        
        if trade['side'] == 'buy':
            buy_positions.append({
                'price': trade['price'],
                'amount': trade['amount'],
                'cost': trade['cost'],
                'timestamp': trade['timestamp'],
                'fee': fee
            })
        else:
            if buy_positions:
                buy = buy_positions.pop(0)
                
                amount = min(trade['amount'], buy['amount'])
                profit = (trade['price'] - buy['price']) * amount
                profit_pct = (profit / buy['cost'] * 100) if buy['cost'] > 0 else 0
                
                total_realized_pnl += profit
                matched_pairs += 1
                
                buy_time = datetime.fromtimestamp(buy['timestamp']/1000).strftime('%m-%d %H:%M')
                sell_time = datetime.fromtimestamp(trade['timestamp']/1000).strftime('%m-%d %H:%M')
                
                emoji = "✅" if profit > 0 else "❌"
                
                trade_details.append({
                    'num': matched_pairs,
                    'emoji': emoji,
                    'buy_price': buy['price'],
                    'sell_price': trade['price'],
                    'buy_time': buy_time,
                    'sell_time': sell_time,
                    'profit': profit,
                    'profit_pct': profit_pct
                })
    
    for detail in trade_details[:20] + trade_details[-10:]:
        print(f"{detail['num']:3d}. {detail['emoji']} BUY @ ${detail['buy_price']:.2f} ({detail['buy_time']}) -> "
              f"SELL @ ${detail['sell_price']:.2f} ({detail['sell_time']}) = "
              f"${detail['profit']:+.2f} ({detail['profit_pct']:+.2f}%)")
    
    if len(trade_details) > 30:
        print(f"... ({len(trade_details) - 30} more trades) ...")
    
    open_buys = len(buy_positions)
    unrealized_pnl = sum((eth_price - b['price']) * b['amount'] for b in buy_positions)
    
    print("=" * 80)
    print(f"\n📊 ПІДСУМОК REALIZED PROFITS:")
    print(f"  Closed pairs:      {matched_pairs}")
    print(f"  Total realized PnL: ${total_realized_pnl:,.2f}")
    print(f"  Total fees:         ${total_fees:,.2f}")
    print(f"  Net realized PnL:   ${total_realized_pnl - total_fees:,.2f}")
    print(f"  Avg per pair:       ${total_realized_pnl / matched_pairs:.2f}" if matched_pairs > 0 else "  Avg per pair:       N/A")
    
    print(f"\n📊 UNREALIZED (OPEN POSITIONS):")
    print(f"  Open BUY orders:    {open_buys}")
    print(f"  Unrealized PnL:     ${unrealized_pnl:+,.2f}")
    
    print(f"\n💰 ФОРМУЛА ПЕРЕВІРКИ:")
    print(f"  Initial Balance:     ${initial:,.2f}")
    print(f"  + Realized PnL:      ${total_realized_pnl:+,.2f}")
    print(f"  - Trading Fees:      ${-total_fees:,.2f}")
    print(f"  + Unrealized PnL:    ${unrealized_pnl:+,.2f}")
    print(f"  = Expected Value:    ${initial + total_realized_pnl - total_fees + unrealized_pnl:,.2f}")
    print(f"  Actual Total Value:  ${total_value:,.2f}")
    print(f"  Difference:          ${total_value - (initial + total_realized_pnl - total_fees + unrealized_pnl):+,.2f}")
    
    winning_pairs = sum(1 for t in trade_details if t['profit'] > 0)
    losing_pairs = sum(1 for t in trade_details if t['profit'] < 0)
    breakeven_pairs = matched_pairs - winning_pairs - losing_pairs
    
    print(f"\n🎯 WIN RATE:")
    print(f"  Winning pairs:   {winning_pairs}/{matched_pairs} ({winning_pairs / matched_pairs * 100:.1f}%)" if matched_pairs > 0 else "  Winning pairs:   N/A")
    print(f"  Losing pairs:    {losing_pairs}/{matched_pairs} ({losing_pairs / matched_pairs * 100:.1f}%)" if matched_pairs > 0 else "  Losing pairs:    N/A")
    print(f"  Breakeven:       {breakeven_pairs}/{matched_pairs}" if matched_pairs > 0 else "  Breakeven:       N/A")
    
    print("\n⚠️  ВАЖЛИВО:")
    print("  Grid trading працює так:")
    print("  • Кожен BUY -> SELL завжди має profit (через spacing)")
    print("  • Але відкриті позиції можуть бути в мінусі (unrealized loss)")
    print("  • Якщо ціна падає, ти купуєш дешевше (unrealized loss)")
    print("  • Загальний PnL = Realized + Unrealized")
    print("  • '100% виграшних угод' це НОРМАЛЬНО для grid!")

if __name__ == '__main__':
    asyncio.run(analyze_testnet_trades())
