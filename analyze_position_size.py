#!/usr/bin/env python3

capital = 500
num_grids = 20
num_symbols = 4
total_positions = num_grids * num_symbols
per_position = capital / total_positions

print('📊 ПОТОЧНА СИТУАЦІЯ:')
print(f'💰 Капітал: ${capital}')
print(f'📈 Grid рівнів: {num_grids}')
print(f'🪙 Символів: {num_symbols}')
print(f'📍 Всього позицій: {total_positions}')
print(f'💵 На одну позицію: ${per_position:.2f}')
print()
print('⚠️ ПРОБЛЕМА:')
print(f'   ${per_position:.2f} × 0.5% прибуток = ${per_position * 0.005:.4f} за трейд')
print(f'   Це занадто мало!')
print()

target_profit_per_trade = 1.0
print(f'🎯 ЩОБ ЗАРОБИТИ ${target_profit_per_trade} ЗА ТРЕЙД:')
print(f'   Потрібна позиція: ${target_profit_per_trade / 0.005:.0f} (якщо 0.5% спред)')
print()

print('💡 РІШЕННЯ 1: ЗМЕНШИТИ РОЗПОДІЛЕННЯ')
for grids in [10, 5, 3]:
    for symbols in [2, 1]:
        pos_size = capital / (grids * symbols)
        profit = pos_size * 0.005
        print(f'   {grids} грідів × {symbols} символів = ${pos_size:.2f}/позицію = ${profit:.2f}/трейд')

print()
print('💡 РІШЕННЯ 2: ЗБІЛЬШИТИ СПРЕД (більша різниця цін)')
spreads = [0.01, 0.02, 0.03, 0.05]
pos = 25  # $25 per position
for spread in spreads:
    profit = pos * spread
    print(f'   Позиція ${pos} × {spread*100:.1f}% спред = ${profit:.2f}/трейд')

print()
print('🚀 АГРЕСИВНА СТРАТЕГІЯ ДЛЯ $30-100/ДЕНЬ:')
print('   Опція 1: 3 гріди × 1 символ × 2% спред')
profit_per_trade = (500/3) * 0.02
trades_per_day = 20
print(f'   ${profit_per_trade:.2f}/трейд × {trades_per_day} трейдів = ${profit_per_trade * trades_per_day:.2f}/день')

print()
print('   Опція 2: 5 грідів × 2 символи × 1.5% спред')
profit_per_trade = (500/10) * 0.015
trades_per_day = 50
print(f'   ${profit_per_trade:.2f}/трейд × {trades_per_day} трейдів = ${profit_per_trade * trades_per_day:.2f}/день')

print()
print('   Опція 3: 10 грідів × 1 символ (DOGE/SOL) × 3% спред')
profit_per_trade = (500/10) * 0.03
trades_per_day = 30
print(f'   ${profit_per_trade:.2f}/трейд × {trades_per_day} трейдів = ${profit_per_trade * trades_per_day:.2f}/день')
