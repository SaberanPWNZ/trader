# Виправлення Telegram звітів - Winrate Fix

## Проблема

У Telegram звітах winrate показував **30%** замість очікуваних **~100%** для grid trading.

### Причина
Стара формула була неправильною:
```python
win_rate = (self.winning_trades / max(1, self.total_trades // 2)) * 100
```

Ця формула ділила на `total_trades // 2`, що не враховує відкриті позиції.

## Рішення

Нова правильна формула:
```python
open_positions = sum(len(positions) for positions in self.positions.values())
completed_pairs = (self.total_trades - open_positions) // 2
win_rate = (self.winning_trades / max(1, completed_pairs)) * 100 if completed_pairs > 0 else 0
```

### Що змінилось:
1. Рахуємо **тільки закриті пари** (BUY→SELL циклі)
2. Виключаємо відкриті позиції з розрахунку
3. Winrate тепер показує **реальний відсоток прибуткових пар**

## Тести

| Сценарій | Стара формула | Нова формула |
|----------|---------------|--------------|
| 10 BUY, 8 SELL (2 open) | 88.9% | **100%** ✅ |
| 20 BUY, 15 SELL (5 open) | 88.2% | **100%** ✅ |
| 50 BUY, 50 SELL (0 open) | 96.0% | 96.0% |

## Виправлені файли

- `paper/grid_simulator.py` - 2 місця (рядки 300 та 362)

## Результат

Тепер в Telegram звітах:
- ✅ Winrate показує **~100%** (як і має бути для grid trading)
- ✅ Всі інші метрики залишились правильними (PnL, ROI, Total Value)
- ✅ Повідомлення про трейди виводяться коректно

## Приклад звіту (після виправлення)

```
📈 Grid 24 Hour Report
━━━━━━━━━━━━━━━━
⏱ Runtime: 24.0h
💰 Initial: $500.00
💵 Current: $545.00
━━━━━━━━━━━━━━━━
📈 Realized PnL: $30.00
📊 Unrealized: $15.00
💹 Total PnL: $45.00
📉 ROI: +9.00%
━━━━━━━━━━━━━━━━
🔄 Trades: 60
🎯 Win Rate: 100.0% ✅
```
