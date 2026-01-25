#!/usr/bin/env python3
"""Manually trigger balance snapshot save."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from learning.database import LearningDatabase
from loguru import logger


async def manual_snapshot():
    """Manually save a balance snapshot with test data."""
    db = LearningDatabase()
    await db.initialize()
    
    # Example snapshot
    await db.save_balance_snapshot(
        balance=10000.0,
        equity=10050.0,
        total_pnl=50.0,
        total_trades=5,
        winning_trades=3,
        losing_trades=2,
        open_positions=1,
        notes="Manual test snapshot"
    )
    
    logger.info("✅ Balance snapshot saved manually")
    
    # Show recent history
    history = await db.get_balance_history(hours=24)
    logger.info(f"\nTotal snapshots in last 24h: {len(history)}")
    
    if history:
        latest = history[-1]
        logger.info(f"Latest snapshot:")
        logger.info(f"  Balance: ${latest['balance']:,.2f}")
        logger.info(f"  Equity: ${latest['equity']:,.2f}")
        logger.info(f"  PnL: ${latest['total_pnl']:,.2f}")
        logger.info(f"  Trades: {latest['total_trades']}")


if __name__ == "__main__":
    asyncio.run(manual_snapshot())
