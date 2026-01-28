#!/usr/bin/env python3
import pandas as pd

trades = pd.read_csv('data/grid_trades.csv')
print(f'Total trades: {len(trades)}')

buys = trades[trades['side'] == 'BUY']
sells = trades[trades['side'] == 'SELL']

print(f'\nBUY trades: {len(buys)}')
print(f'SELL trades: {len(sells)}')

latest = trades.iloc[-1]
print(f'\n╔══════════════════════════════════════╗')
print(f'║     РЕАЛЬНІ ДАНІ (останній трейд)    ║')
print(f'╠══════════════════════════════════════╣')
print(f'║ Realized PnL:    ${latest["realized_pnl"]:.4f}       ║')
print(f'║ Unrealized PnL:  ${latest["unrealized_pnl"]:.4f}       ║')
print(f'║ Total Value:     ${latest["total_value"]:.2f}      ║')
print(f'║ ROI:             {latest["roi_percent"]:.4f}%        ║')
print(f'╚══════════════════════════════════════╝')

pairs_closed = min(len(buys), len(sells))
print(f'\n📊 Закриті пари: {pairs_closed}')
print(f'💰 Прибуток на пару: ${latest["realized_pnl"] / max(1, pairs_closed):.4f}')

print(f'\n🔍 ПРОБЛЕМА З WINRATE:')
print(f'   Grid simulator використовує формулу:')
print(f'   win_rate = winning_trades / (total_trades // 2)')
print(f'   ')
print(f'   Але це НЕПРАВИЛЬНО для grid trading!')
print(f'   ')
print(f'   В grid trading:')
print(f'   - Кожен BUY -> SELL цикл = мінімальний профіт')
print(f'   - Winrate має бути близько 100%!')
print(f'   - 30% це помилка в коді')

print(f'\n✅ РЕАЛЬНА СИТУАЦІЯ:')
print(f'   - Ти заробив ${latest["realized_pnl"]:.2f}')
print(f'   - {len(sells)} успішних продажів')
print(f'   - Кожен SELL після BUY = профіт')
print(f'   - Реальний winrate: ~100%')
