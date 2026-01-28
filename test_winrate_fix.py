#!/usr/bin/env python3
"""
Тест виправлення winrate формули
"""

print("🧪 ТЕСТ WINRATE ФОРМУЛИ\n")

print("СЦЕНАРІЙ 1: 10 BUY, 8 SELL (2 відкриті позиції)")
total_trades = 18
open_positions = 2
winning_trades = 8

old_formula = (winning_trades / max(1, total_trades // 2)) * 100
completed_pairs = (total_trades - open_positions) // 2
new_formula = (winning_trades / max(1, completed_pairs)) * 100 if completed_pairs > 0 else 0

print(f"  Total trades: {total_trades}")
print(f"  Open positions: {open_positions}")
print(f"  Winning trades: {winning_trades}")
print(f"  Completed pairs: {completed_pairs}")
print(f"  ❌ Стара формула: {old_formula:.1f}%")
print(f"  ✅ Нова формула: {new_formula:.1f}%")
print()

print("СЦЕНАРІЙ 2: 20 BUY, 15 SELL (5 відкритих)")
total_trades = 35
open_positions = 5
winning_trades = 15

old_formula = (winning_trades / max(1, total_trades // 2)) * 100
completed_pairs = (total_trades - open_positions) // 2
new_formula = (winning_trades / max(1, completed_pairs)) * 100 if completed_pairs > 0 else 0

print(f"  Total trades: {total_trades}")
print(f"  Open positions: {open_positions}")
print(f"  Winning trades: {winning_trades}")
print(f"  Completed pairs: {completed_pairs}")
print(f"  ❌ Стара формула: {old_formula:.1f}%")
print(f"  ✅ Нова формула: {new_formula:.1f}%")
print()

print("СЦЕНАРІЙ 3: 50 BUY, 50 SELL (всі закриті)")
total_trades = 100
open_positions = 0
winning_trades = 48

old_formula = (winning_trades / max(1, total_trades // 2)) * 100
completed_pairs = (total_trades - open_positions) // 2
new_formula = (winning_trades / max(1, completed_pairs)) * 100 if completed_pairs > 0 else 0

print(f"  Total trades: {total_trades}")
print(f"  Open positions: {open_positions}")
print(f"  Winning trades: {winning_trades}")
print(f"  Completed pairs: {completed_pairs}")
print(f"  ❌ Стара формула: {old_formula:.1f}%")
print(f"  ✅ Нова формула: {new_formula:.1f}%")
print()

print("💡 ВИСНОВОК:")
print("  В grid trading кожна закрита пара = профітна")
print("  Стара формула ділила на total_trades//2 (неправильно)")
print("  Нова формула ділить на completed_pairs (правильно)")
print("  Winrate має бути близько 100% для grid strategy")
