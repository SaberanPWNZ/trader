#!/usr/bin/env python3
import csv
from datetime import datetime
import sys
from pathlib import Path
from collections import defaultdict

from analytics.pnl_attribution import attribute_pnl


LIVE_TRADES_FILE = Path('data/grid_live_trades.csv')


def printCauseAttributionSection():
    """Print a per-cause breakdown of realized PnL from live trades.

    Reads ``data/grid_live_trades.csv`` (the live grid trader's log,
    which carries the ``cause`` column populated by ``GridLiveTrader``)
    and pipes it through :func:`analytics.pnl_attribution.attribute_pnl`.
    Silently skipped when the file is missing — paper-trading-only
    deployments shouldn't see a stale section.
    """
    if not LIVE_TRADES_FILE.exists():
        return
    with open(LIVE_TRADES_FILE, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return

    result = attribute_pnl(rows)
    by_cause = result.by_cause()
    if not by_cause:
        return

    print("\n" + "=" * 80)
    print("📌 РЕАЛІЗОВАНИЙ PnL ЗА ПРИЧИНОЮ (live trades)")
    print("=" * 80)
    total = sum(by_cause.values())
    # Stable ordering: largest absolute contribution first so the
    # operator sees the dominant driver immediately.
    for cause, pnl in sorted(by_cause.items(), key=lambda kv: -abs(kv[1])):
        emoji = "🟢" if pnl >= 0 else "🔴"
        share = (pnl / total * 100.0) if total else 0.0
        print(f"   {emoji} {cause:<14s} ${pnl:>+10.2f}  ({share:+6.1f}%)")
    print("-" * 80)
    print(f"   Сума: ${total:+.2f} (за {len(rows)} live-фільтрами)")
    print("=" * 80)


def generateDailyProfitReport():
    tradesFile = Path('data/grid_trades.csv')
    
    if not tradesFile.exists():
        print("❌ Файл grid_trades.csv не знайдено!")
        sys.exit(1)
    
    trades = []
    with open(tradesFile, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['timestamp'] = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
            row['date'] = row['timestamp'].date()
            row['realized_pnl'] = float(row['realized_pnl'])
            row['unrealized_pnl'] = float(row['unrealized_pnl'])
            row['balance'] = float(row['balance'])
            row['total_value'] = float(row['total_value'])
            row['roi_percent'] = float(row['roi_percent'])
            trades.append(row)
    
    if len(trades) == 0:
        print("📊 Поки що немає трейдів!")
        return
    
    tradesByDate = defaultdict(list)
    for trade in trades:
        tradesByDate[trade['date']].append(trade)
    
    dailyStats = []
    dates = sorted(tradesByDate.keys())
    
    for date in dates:
        dayTrades = tradesByDate[date]
        lastTradeOfDay = dayTrades[-1]
        
        if len(dailyStats) > 0:
            prevTotalValue = dailyStats[-1]['total_value']
            dailyProfit = lastTradeOfDay['total_value'] - prevTotalValue
        else:
            initialBalance = 5000.0
            dailyProfit = lastTradeOfDay['total_value'] - initialBalance
        
        buyTrades = len([t for t in dayTrades if t['side'] == 'BUY'])
        sellTrades = len([t for t in dayTrades if t['side'] == 'SELL'])
        
        dailyStats.append({
            'date': date,
            'trades_count': len(dayTrades),
            'daily_profit': dailyProfit,
            'cumulative_realized_pnl': lastTradeOfDay['realized_pnl'],
            'unrealized_pnl': lastTradeOfDay['unrealized_pnl'],
            'ending_balance': lastTradeOfDay['balance'],
            'total_value': lastTradeOfDay['total_value'],
            'roi_percent': lastTradeOfDay['roi_percent'],
            'buy_trades': buyTrades,
            'sell_trades': sellTrades
        })
    
    print("\n" + "="*80)
    print("║" + " "*25 + "ДЕННИЙ ЗВІТ ПО ПРИБУТКУ" + " "*31 + "║")
    print("="*80)
    print(f"{'Дата':<12} {'Трейди':<8} {'Прибуток за день':<18} {'Кумул. PnL':<14} {'ROI %':<10} {'Баланс':<12}")
    print("-"*80)
    
    totalProfit = 0
    for stat in dailyStats:
        totalProfit += stat['daily_profit']
        emoji = "🟢" if stat['daily_profit'] >= 0 else "🔴"
        dateStr = stat['date'].strftime('%d.%m.%Y')
        
        print(f"{dateStr:<12} {stat['trades_count']:<8} {emoji} ${stat['daily_profit']:>+13.2f}   "
              f"${stat['cumulative_realized_pnl']:>10.2f}   {stat['roi_percent']:>+7.2f}%   "
              f"${stat['ending_balance']:>9.2f}")
    
    print("-"*80)
    lastStat = dailyStats[-1]
    currentValue = lastStat['total_value']
    initialBalance = 5000.0
    totalProfitActual = currentValue - initialBalance
    print(f"{'ВСЬОГО:':<12} {len(trades):<8} {'💰 Прибуток: $' + f'{totalProfitActual:+.2f}':<25} Поточна вартість: ${currentValue:.2f}")
    print("="*80)
    
    print("\n📊 ДЕТАЛЬНА СТАТИСТИКА ПО ДНЯХ:\n")
    
    for stat in dailyStats:
        dateStr = stat['date'].strftime('%d.%m.%Y')
        print(f"📅 {dateStr}:")
        print(f"   Трейдів: {stat['trades_count']} (🟢 {stat['buy_trades']} купівель, 🔴 {stat['sell_trades']} продажів)")
        print(f"   Прибуток за день: ${stat['daily_profit']:+.2f}")
        print(f"   Кумулятивний realized PnL: ${stat['cumulative_realized_pnl']:.2f}")
        print(f"   Нереалізований PnL: ${stat['unrealized_pnl']:+.2f}")
        print(f"   Загальна вартість портфелю: ${stat['total_value']:.2f}")
        print(f"   ROI: {stat['roi_percent']:+.2f}%")
        print()
    
    bestDay = max(dailyStats, key=lambda x: x['daily_profit'])
    worstDay = min(dailyStats, key=lambda x: x['daily_profit'])
    
    print("🏆 РЕКОРДИ:")
    print(f"   Найкращий день: {bestDay['date'].strftime('%d.%m.%Y')} (${bestDay['daily_profit']:+.2f})")
    print(f"   Найгірший день:  {worstDay['date'].strftime('%d.%m.%Y')} (${worstDay['daily_profit']:+.2f})")
    
    avgDailyProfit = totalProfit / len(dailyStats)
    print(f"   Середній прибуток за день: ${avgDailyProfit:+.2f}")
    
    profitableDays = len([s for s in dailyStats if s['daily_profit'] > 0])
    winRate = (profitableDays / len(dailyStats)) * 100
    print(f"   Прибуткових днів: {profitableDays}/{len(dailyStats)} ({winRate:.1f}%)")
    print()

    printCauseAttributionSection()

if __name__ == "__main__":
    generateDailyProfitReport()
