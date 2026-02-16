#!/usr/bin/env python3
import asyncio
from exchange.factory import create_exchange

async def check_balance():
    ex = create_exchange(testnet=False)
    await ex.connect()
    
    balance = await ex.fetch_balance()
    ticker = await ex.fetch_ticker('ETH/USDT')
    
    usdt = balance.get('USDT', {}).get('total', 0)
    usdt_free = balance.get('USDT', {}).get('free', 0)
    usdt_used = balance.get('USDT', {}).get('used', 0)
    
    eth = balance.get('ETH', {}).get('total', 0)
    eth_free = balance.get('ETH', {}).get('free', 0)
    eth_used = balance.get('ETH', {}).get('used', 0)
    
    eth_price = ticker['last']
    eth_value = eth * eth_price
    total_value = usdt + eth_value
    
    print("="*60)
    print("💰 РЕАЛЬНИЙ БАЛАНС BINANCE")
    print("="*60)
    print(f"USDT Total: ${usdt:.2f}")
    print(f"  Free:     ${usdt_free:.2f}")
    print(f"  Used:     ${usdt_used:.2f}")
    print()
    print(f"ETH Total:  {eth:.6f} ETH")
    print(f"  Free:     {eth_free:.6f} ETH")
    print(f"  Used:     {eth_used:.6f} ETH")
    print(f"  Value:    ${eth_value:.2f} (@ ${eth_price:.2f})")
    print()
    print(f"TOTAL:      ${total_value:.2f}")
    print("="*60)
    
    orders = await ex.fetch_open_orders('ETH/USDT')
    print(f"\n📋 Open Orders: {len(orders)}")
    for order in orders:
        print(f"  {order['side']} {order['amount']:.6f} ETH @ ${order['price']:.2f}")
    
    await ex.disconnect()

if __name__ == "__main__":
    asyncio.run(check_balance())
