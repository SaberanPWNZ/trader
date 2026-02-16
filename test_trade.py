"""
Тестовий скрипт для перевірки купівлі/продажу на Binance mainnet
"""
import asyncio
from exchange.factory import create_exchange
from loguru import logger

async def test_buy_sell():
    ex = create_exchange(testnet=False)
    await ex.connect()
    
    try:
        balance = await ex.fetch_balance()
        usdt_free = balance.get('USDT', {}).get('free', 0)
        eth_free = balance.get('ETH', {}).get('free', 0)
        
        ticker = await ex.fetch_ticker('ETH/USDT')
        eth_price = ticker['last']
        
        print("=" * 60)
        print("💰 ПОЧАТКОВИЙ БАЛАНС")
        print("=" * 60)
        print(f"USDT: ${usdt_free:.2f}")
        print(f"ETH: {eth_free:.6f} (${eth_free * eth_price:.2f})")
        print(f"ETH Price: ${eth_price:.2f}")
        print()
        
        test_amount_usd = 20.0
        test_amount_eth = test_amount_usd / eth_price
        
        if eth_free >= 0.01:
            print("🔴 Спочатку продаємо весь наявний ETH...")
            sell_order = await ex.create_order(
                symbol='ETH/USDT',
                type='market',
                side='sell',
                amount=eth_free
            )
            print(f"✅ Продано: {eth_free:.6f} ETH")
            print(f"   Order ID: {sell_order['id']}")
            await asyncio.sleep(2)
            
            balance = await ex.fetch_balance()
            usdt_free = balance.get('USDT', {}).get('free', 0)
            print(f"   Новий USDT баланс: ${usdt_free:.2f}")
            print()
        
        if usdt_free < test_amount_usd:
            print(f"❌ Недостатньо USDT для тесту (потрібно ${test_amount_usd:.2f}, є ${usdt_free:.2f})")
            return
        
        print(f"🟢 ТЕСТ: Купуємо ETH на ${test_amount_usd:.2f}...")
        buy_order = await ex.create_order(
            symbol='ETH/USDT',
            type='market',
            side='buy',
            amount=test_amount_eth
        )
        print(f"✅ Куплено: {test_amount_eth:.6f} ETH")
        print(f"   Order ID: {buy_order['id']}")
        print(f"   Status: {buy_order['status']}")
        
        await asyncio.sleep(2)
        
        balance = await ex.fetch_balance()
        eth_after_buy = balance.get('ETH', {}).get('free', 0)
        usdt_after_buy = balance.get('USDT', {}).get('free', 0)
        
        print(f"   Баланс після купівлі:")
        print(f"     USDT: ${usdt_after_buy:.2f}")
        print(f"     ETH: {eth_after_buy:.6f}")
        print()
        
        print(f"🔴 ТЕСТ: Продаємо ETH...")
        sell_order = await ex.create_order(
            symbol='ETH/USDT',
            type='market',
            side='sell',
            amount=eth_after_buy
        )
        print(f"✅ Продано: {eth_after_buy:.6f} ETH")
        print(f"   Order ID: {sell_order['id']}")
        print(f"   Status: {sell_order['status']}")
        
        await asyncio.sleep(2)
        
        balance = await ex.fetch_balance()
        usdt_final = balance.get('USDT', {}).get('free', 0)
        eth_final = balance.get('ETH', {}).get('free', 0)
        
        print()
        print("=" * 60)
        print("💰 ФІНАЛЬНИЙ БАЛАНС")
        print("=" * 60)
        print(f"USDT: ${usdt_final:.2f}")
        print(f"ETH: {eth_final:.6f}")
        print()
        
        profit = usdt_final - usdt_free
        print(f"📊 Результат тесту: ${profit:+.2f}")
        
        if abs(profit) < 1:
            print("✅ ТЕСТ УСПІШНИЙ! Купівля/продаж працюють")
        else:
            print(f"⚠️ Втрата на комісіях: ${abs(profit):.2f}")
        
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"Помилка: {e}")
        print(f"❌ ПОМИЛКА: {e}")
    
    finally:
        await ex.disconnect()

if __name__ == "__main__":
    asyncio.run(test_buy_sell())
