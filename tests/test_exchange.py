#!/usr/bin/env python3
import asyncio
import sys
from datetime import datetime
from loguru import logger

sys.path.insert(0, '.')

from config.settings import settings
from exchange.client import ExchangeClient
from exchange.factory import create_exchange, MockExchangeClient


async def testRealExchange():
    logger.info("=" * 60)
    logger.info("Testing REAL Exchange Connection (Testnet)")
    logger.info("=" * 60)
    
    if not settings.exchange.api_key or not settings.exchange.api_secret:
        logger.warning("No API keys configured. Set BINANCE_API_KEY and BINANCE_API_SECRET in .env")
        logger.info("Skipping real exchange test...")
        return False
    
    try:
        client = create_exchange(testnet=True)
        await client.connect()
        
        logger.info("✅ Connected to exchange")
        logger.info(f"   Exchange: {client.exchange_id}")
        logger.info(f"   Testnet: {client.testnet}")
        logger.info(f"   Markets: {len(client.markets)}")
        
        validation = await client.validate_connection()
        if validation['success']:
            logger.info("✅ Connection validated")
            logger.info(f"   Balance: {validation['balance']} USDT")
        else:
            logger.error(f"❌ Validation failed: {validation['error']}")
            return False
        
        ticker = await client.fetch_ticker('BTC/USDT')
        logger.info("✅ Fetched ticker")
        logger.info(f"   BTC/USDT: ${ticker['last']:,.2f}")
        
        ohlcv = await client.fetch_ohlcv('BTC/USDT', '1h', limit=5)
        logger.info("✅ Fetched OHLCV")
        logger.info(f"   Candles: {len(ohlcv)}")
        
        await client.disconnect()
        logger.info("✅ Disconnected")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Exchange test failed: {e}")
        return False


async def testMockExchange():
    logger.info("=" * 60)
    logger.info("Testing MOCK Exchange")
    logger.info("=" * 60)
    
    try:
        client = MockExchangeClient(initial_balance=10000.0)
        await client.connect()
        
        logger.info("✅ Connected to mock exchange")
        
        client.set_price('BTC/USDT', 50000.0)
        ticker = await client.fetch_ticker('BTC/USDT')
        logger.info(f"✅ Ticker: BTC/USDT = ${ticker['last']:,.2f}")
        
        balance = await client.fetch_balance()
        logger.info(f"✅ Initial balance: ${balance['USDT']['total']:,.2f}")
        
        order = await client.create_order(
            symbol='BTC/USDT',
            type='market',
            side='buy',
            amount=0.1
        )
        logger.info(f"✅ Created order: {order['id']}")
        logger.info(f"   Side: {order['side']}")
        logger.info(f"   Amount: {order['amount']}")
        logger.info(f"   Price: ${order['price']:,.2f}")
        logger.info(f"   Status: {order['status']}")
        
        balance = await client.fetch_balance()
        logger.info(f"✅ Balance after buy: ${balance['USDT']['free']:,.2f}")
        
        sell_order = await client.create_order(
            symbol='BTC/USDT',
            type='market',
            side='sell',
            amount=0.1
        )
        logger.info(f"✅ Closed position: {sell_order['id']}")
        
        balance = await client.fetch_balance()
        logger.info(f"✅ Final balance: ${balance['USDT']['free']:,.2f}")
        
        await client.disconnect()
        logger.info("✅ Disconnected")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Mock exchange test failed: {e}")
        return False


async def testOrderFlow():
    logger.info("=" * 60)
    logger.info("Testing Order Flow")
    logger.info("=" * 60)
    
    try:
        client = MockExchangeClient(initial_balance=10000.0)
        await client.connect()
        
        client.set_price('BTC/USDT', 50000.0)
        
        logger.info("Testing order flow simulation...")
        
        initial_balance = (await client.fetch_balance())['USDT']['total']
        logger.info(f"Initial: ${initial_balance:,.2f}")
        
        buy_order = await client.create_order('BTC/USDT', 'market', 'buy', 0.05)
        cost = buy_order['amount'] * buy_order['price']
        logger.info(f"BUY: {buy_order['amount']} BTC @ ${buy_order['price']:,.2f} = ${cost:,.2f}")
        
        client.set_price('BTC/USDT', 52000.0)
        
        sell_order = await client.create_order('BTC/USDT', 'market', 'sell', 0.05)
        revenue = sell_order['amount'] * sell_order['price']
        logger.info(f"SELL: {sell_order['amount']} BTC @ ${sell_order['price']:,.2f} = ${revenue:,.2f}")
        
        final_balance = (await client.fetch_balance())['USDT']['free']
        pnl = final_balance - initial_balance
        logger.info(f"Final: ${final_balance:,.2f}")
        logger.info(f"PnL: ${pnl:,.2f}")
        
        await client.disconnect()
        
        return pnl > 0
        
    except Exception as e:
        logger.error(f"❌ Order flow test failed: {e}")
        return False


async def main():
    logger.info("🧪 Exchange Integration Test Suite")
    logger.info(f"   Date: {datetime.now()}")
    logger.info("")
    
    results = {}
    
    results['mock'] = await testMockExchange()
    print()
    
    results['order_flow'] = await testOrderFlow()
    print()
    
    results['real'] = await testRealExchange()
    print()
    
    logger.info("=" * 60)
    logger.info("TEST RESULTS")
    logger.info("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"   {test_name}: {status}")
    
    all_passed = all(results.values())
    logger.info("")
    if all_passed:
        logger.info("🎉 All tests passed!")
    else:
        logger.warning("⚠️ Some tests failed")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
