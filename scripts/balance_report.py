#!/usr/bin/env python3
"""Show balance history and weekly summary."""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from learning.database import LearningDatabase
from loguru import logger


async def show_balance_report():
    logger.info("💰 Balance History Report")
    logger.info("=" * 70)
    
    db = LearningDatabase()
    await db.initialize()
    
    # Get weekly summary
    logger.info("\n📊 WEEKLY SUMMARY (Last 7 Days)")
    logger.info("-" * 70)
    
    weekly = await db.get_weekly_summary()
    if weekly:
        logger.info(f"Start Balance:    ${weekly['start_balance']:>12,.2f}")
        logger.info(f"End Balance:      ${weekly['end_balance']:>12,.2f}")
        logger.info(f"Start Equity:     ${weekly['start_equity']:>12,.2f}")
        logger.info(f"End Equity:       ${weekly['end_equity']:>12,.2f}")
        logger.info(f"")
        logger.info(f"Total PnL:        ${weekly['total_pnl']:>12,.2f}  ({weekly['pnl_percentage']:+.2f}%)")
        logger.info(f"Total Trades:     {weekly['total_trades']:>12}")
        logger.info(f"Winning Trades:   {weekly['winning_trades']:>12}")
        logger.info(f"Losing Trades:    {weekly['losing_trades']:>12}")
        
        win_rate = (weekly['winning_trades'] / weekly['total_trades'] * 100) if weekly['total_trades'] > 0 else 0
        logger.info(f"Win Rate:         {win_rate:>12.1f}%")
    else:
        logger.warning("No weekly data available yet")
    
    # Get balance history (last 24 hours)
    logger.info("\n\n📈 BALANCE HISTORY (Last 24 Hours)")
    logger.info("-" * 70)
    logger.info(f"{'Time':<20} {'Balance':>12} {'Equity':>12} {'PnL':>12} {'Trades':>8}")
    logger.info("-" * 70)
    
    history = await db.get_balance_history(hours=24)
    if history:
        for snapshot in history:
            timestamp = datetime.fromisoformat(snapshot['timestamp']).strftime('%Y-%m-%d %H:%M')
            logger.info(
                f"{timestamp:<20} "
                f"${snapshot['balance']:>11,.2f} "
                f"${snapshot['equity']:>11,.2f} "
                f"${snapshot['total_pnl']:>11,.2f} "
                f"{snapshot['total_trades']:>8}"
            )
    else:
        logger.warning("No balance history available yet")
    
    # Get full week history
    logger.info("\n\n📊 DAILY SNAPSHOTS (Last 7 Days)")
    logger.info("-" * 70)
    logger.info(f"{'Date':<12} {'Balance':>12} {'Equity':>12} {'PnL':>12} {'Trades':>8} {'Win Rate':>10}")
    logger.info("-" * 70)
    
    week_history = await db.get_balance_history(hours=168)
    if week_history:
        # Group by day
        daily = {}
        for snapshot in week_history:
            date = datetime.fromisoformat(snapshot['timestamp']).strftime('%Y-%m-%d')
            if date not in daily or snapshot['timestamp'] > daily[date]['timestamp']:
                daily[date] = snapshot
        
        for date in sorted(daily.keys()):
            snapshot = daily[date]
            win_rate = (snapshot['winning_trades'] / snapshot['total_trades'] * 100) if snapshot['total_trades'] > 0 else 0
            logger.info(
                f"{date:<12} "
                f"${snapshot['balance']:>11,.2f} "
                f"${snapshot['equity']:>11,.2f} "
                f"${snapshot['total_pnl']:>11,.2f} "
                f"{snapshot['total_trades']:>8} "
                f"{win_rate:>9.1f}%"
            )
    
    logger.info("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(show_balance_report())
