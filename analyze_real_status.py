#!/usr/bin/env python3
import asyncio
from datetime import datetime
from exchange.factory import create_exchange
import json

async def full_analysis():
    ex = create_exchange(testnet=True)
    await ex.connect()
    
    all_trades = []
    since = None
    for _ in range(10):
        trades = await ex.fetch_my_trades('ETH/USDT', since=since, limit=1000)
        if not trades:
            break
        all_trades.extend(trades)
        if len(trades) < 100:
            break
        since = trades[-1]['timestamp'] + 1
    
    balance = await ex.fetch_balance()
    ticker = await ex.fetch_ticker('ETH/USDT')
    eth_price = ticker['last']
    
    usdt_total = balance.get('USDT', {}).get('total', 0)
    eth_total = balance.get('ETH', {}).get('total', 0)
    eth_value = eth_total * eth_price
    total_value = usdt_total + eth_value
    
    print('=' * 60)
    print('        ПОВНИЙ АНАЛІЗ TESTNET ТОРГІВЛІ')
    print('=' * 60)
    print()
    
    print('1. СТАТИСТИКА УГОД:')
    print(f'   Всього угод на біржі: {len(all_trades)}')
    buy_trades = [t for t in all_trades if t["side"] == 'buy']
    sell_trades = [t for t in all_trades if t["side"] == 'sell']
    print(f'   BUY: {len(buy_trades)}, SELL: {len(sell_trades)}')
    
    with open('data/grid_live_trades.csv', 'r') as f:
        csv_lines = len(f.readlines()) - 1
    print(f'   Файл grid_live_trades.csv: {csv_lines} записів (НЕПОВНО!)')
    print()
    
    print('2. БАЛАНС:')
    print(f'   USDT: ${usdt_total:.2f}')
    print(f'   ETH: {eth_total:.6f} @ ${eth_price:.2f} = ${eth_value:.2f}')
    print(f'   Загалом: ${total_value:.2f}')
    print()
    
    print('3. PnL АНАЛІЗ:')
    with open('data/grid_live_balance.json', 'r') as f:
        state = json.load(f)
    initial = state.get('initial_balance', 12128.32)
    pnl = total_value - initial
    roi = (pnl / initial) * 100
    print(f'   Початковий баланс: ${initial:.2f}')
    print(f'   Поточна вартість: ${total_value:.2f}')
    print(f'   Прибуток: ${pnl:.2f} ({roi:.2f}%)')
    print()
    
    print('4. ПРОБЛЕМИ ЗНАЙДЕНО:')
    print('   - grid_live_trades.csv записує тільки частину угод')
    print('   - PnL в файлі розраховується неправильно')
    print('   - Файл не синхронізується з біржею')
    print('   - BUY не записуються в файл')
    print()
    
    buy_total = sum(t['cost'] for t in buy_trades)
    sell_total = sum(t['cost'] for t in sell_trades)
    
    print('5. ПРАВИЛЬНИЙ РОЗРАХУНОК:')
    print(f'   Куплено ETH на: ${buy_total:.2f}')
    print(f'   Продано ETH на: ${sell_total:.2f}')
    print(f'   Різниця (торговий прибуток): ${sell_total - buy_total:.2f}')
    print(f'   ETH залишок: {eth_total:.6f} = ${eth_value:.2f}')
    print()
    
    if all_trades:
        first_trade = min(all_trades, key=lambda x: x['timestamp'])
        last_trade = max(all_trades, key=lambda x: x['timestamp'])
        runtime_hours = (last_trade['timestamp'] - first_trade['timestamp']) / (1000 * 3600)
        print('6. ЧАС РОБОТИ:')
        print(f'   Перша угода: {first_trade["datetime"][:16]}')
        print(f'   Остання угода: {last_trade["datetime"][:16]}')
        print(f'   Час роботи: {runtime_hours:.1f} годин')
        if runtime_hours > 0:
            print(f'   Прибуток/годину: ${pnl/runtime_hours:.2f}')
        print()
    
    print('=' * 60)
    print('                     ВИСНОВОК')
    print('=' * 60)
    print(f'   Реальний прибуток: ${pnl:.2f} ({roi:.2f}%)')
    print()
    if pnl > 0:
        print('   ✅ Grid trading ПРАЦЮЄ - прибуток є!')
    else:
        print('   ❌ Grid trading в мінусі')
    print('   ⚠️  Логування/статистика НЕПОВНІ - потрібно виправити')
    print()
    
    print('=' * 60)
    print('           ГОТОВНІСТЬ ДО РЕАЛЬНИХ ГРОШЕЙ')
    print('=' * 60)
    print()
    ready = True
    issues = []
    
    if len(all_trades) < 100:
        issues.append('Замало угод для статистичної достовірності')
        ready = False
    
    if csv_lines != len(all_trades):
        issues.append('Логування угод працює неправильно')
        
    if roi < 1.0:
        issues.append('ROI занизький для впевненості')
        ready = False
        
    if runtime_hours < 24 * 3:
        issues.append('Мало часу тестування (менше 3 днів)')
    
    if ready and len(issues) < 2:
        print('   ✅ МОЖНА переходити на реальні гроші')
        print('      Але рекомендую:')
        print('      - Почати з малої суми (100-500$)')
        print('      - Виправити логування')
    else:
        print('   ⚠️  ПОКИ НЕ РЕКОМЕНДУЮ:')
        for issue in issues:
            print(f'      - {issue}')
    
    print('=' * 60)
    
    await ex.disconnect()

if __name__ == "__main__":
    asyncio.run(full_analysis())
