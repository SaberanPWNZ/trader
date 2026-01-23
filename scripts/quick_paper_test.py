#!/usr/bin/env python3
"""Quick paper trading test (5 minutes)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from paper.simulator import PaperTradingSimulator
from strategies.ai_strategy import AIStrategy
from learning.database import LearningDatabase
from config.settings import settings
from loguru import logger


async def quickPaperTest():
    logger.info("📄 Quick Paper Trading Test (5 minutes)")
    logger.info("=" * 60)
    
    try:
        db = LearningDatabase()
        await db.initialize()
        
        strategy = AIStrategy(db=db)
        simulator = PaperTradingSimulator(
            strategy=strategy,
            symbols=["BTC/USDT"],
            initial_balance=10000.0,
            db=db
        )
        
        await simulator.start()
        logger.info("✅ Simulator started")
        logger.info(f"   Initial balance: ${simulator.initial_balance:,.2f}")
        
        logger.info("\n⏱️  Running for 5 minutes...")
        logger.info("   Press Ctrl+C to stop early\n")
        
        iterations = 0
        max_iterations = 5
        
        while iterations < max_iterations:
            try:
                await asyncio.sleep(5)
                iterations += 1
                
                logger.info(f"\n📊 Status (iteration {iterations}/{max_iterations}):")
                logger.info(f"   Balance: ${simulator._balance:,.2f}")
                logger.info(f"   PnL: ${simulator.stats.total_pnl:,.2f}")
                logger.info(f"   Trades: {simulator.stats.total_trades}")
                logger.info(f"   Win Rate: {simulator.stats.winning_trades}/{simulator.stats.total_trades if simulator.stats.total_trades > 0 else 1}")
                
                if iterations < max_iterations:
                    logger.info("   Waiting...")
                    
            except KeyboardInterrupt:
                logger.warning("\n⚠️  Stopping early (Ctrl+C)")
                break
        
        await simulator.stop()
        
        logger.info("\n" + "=" * 60)
        logger.info("📊 Final Results:")
        logger.info(f"   Initial: ${simulator.initial_balance:,.2f}")
        logger.info(f"   Final: ${simulator._balance:,.2f}")
        logger.info(f"   PnL: ${simulator.stats.total_pnl:,.2f}")
        logger.info(f"   Return: {(simulator._balance - simulator.initial_balance) / simulator.initial_balance * 100:.2f}%")
        logger.info(f"   Trades: {simulator.stats.total_trades}")
        logger.info(f"   Win Rate: {simulator.stats.winning_trades}/{simulator.stats.total_trades if simulator.stats.total_trades > 0 else 1}")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(quickPaperTest())
    sys.exit(0 if result else 1)
