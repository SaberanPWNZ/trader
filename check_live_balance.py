#!/usr/bin/env python3
import asyncio
import json
import os
from datetime import datetime
from exchange.factory import create_exchange

STATE_FILE = "data/grid_live_balance.json"

async def check_balance():
    ex = create_exchange(testnet=True)
    await ex.connect()
    
    balance = await ex.fetch_balance()
    ticker = await ex.fetch_ticker('ETH/USDT')
    eth_price = ticker['last']
    
    usdt_total = balance.get('USDT', {}).get('total', 0)
    eth_total = balance.get('ETH', {}).get('total', 0)
    eth_value = eth_total * eth_price
    total_value = usdt_total + eth_value
    
    state = {"initial_balance": 10000.0}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    else:
        state["initial_balance"] = total_value
        state["start_time"] = datetime.now().isoformat()
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    
    initial = state.get("initial_balance", 10000.0)
    pnl = total_value - initial
    pnl_pct = (pnl / initial) * 100 if initial > 0 else 0
    
    orders = await ex.fetch_open_orders('ETH/USDT')
    
    print()
    print("=" * 55)
    print("      📊 GRID LIVE TRADING - BINANCE TESTNET")
    print("=" * 55)
    print()
    print(f"  💵 USDT:          ${usdt_total:>12,.2f}")
    print(f"  🪙 ETH:           {eth_total:>12.6f} (${eth_value:,.2f})")
    print(f"  📈 ETH Price:     ${eth_price:>12,.2f}")
    print()
    print("-" * 55)
    print(f"  📦 Стартовий:     ${initial:>12,.2f}")
    print(f"  💰 Поточний:      ${total_value:>12,.2f}")
    print(f"  {'📈' if pnl >= 0 else '📉'} PnL:            ${pnl:>+12,.2f} ({pnl_pct:+.2f}%)")
    print("-" * 55)
    print()
    print(f"  📋 Відкритих ордерів: {len(orders)}")
    for o in orders:
        side = o['side'].upper()
        icon = "🟢" if side == "BUY" else "🔴"
        print(f"     {icon} {side:4} @ ${o['price']:.2f}")
    print()
    print("=" * 55)
    
    await ex.disconnect()

if __name__ == "__main__":
    asyncio.run(check_balance())
