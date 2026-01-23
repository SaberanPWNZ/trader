#!/usr/bin/env python3
"""Test live predictions with deployed models."""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from learning.database import LearningDatabase
from learning.model_manager import ModelManager
from strategies.ai_strategy import AIStrategy
from data.collector import DataCollector
from config.settings import settings
from loguru import logger


async def testLivePredictions():
    logger.info("🔮 Testing Live Predictions")
    logger.info("=" * 60)
    
    db = LearningDatabase()
    
    try:
        await db.initialize()
        
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM models WHERE is_deployed = TRUE")
            deployed_rows = await cursor.fetchall()
            deployed_models = [dict(row) for row in deployed_rows]
        
        if not deployed_models:
            logger.warning("⚠️  No deployed models found!")
            logger.info("   Run 'python main.py force-train BTC/USDT' first")
            return False
        
        logger.info(f"\n📦 Found {len(deployed_models)} deployed models")
        
        for model_info in deployed_models:
            symbol = model_info['symbol']
            logger.info(f"\n🎯 Testing {symbol}")
            logger.info(f"   Model: {model_info['model_type']}")
            logger.info(f"   Test Accuracy: {model_info['test_accuracy']:.2%}")
            
            try:
                collector = DataCollector()
                await collector.connect()
                df = await collector.fetch_ohlcv(symbol=symbol, timeframe='1h', limit=100)
                
                if df.empty:
                    logger.warning(f"   ⚠️  No data for {symbol}")
                    continue
                
                logger.info(f"   Latest price: ${df['close'].iloc[-1]:,.2f}")
                
                df['symbol'] = symbol
                strategy = AIStrategy(db=db)
                await strategy.load_model_for_symbol(symbol)
                signal_obj = strategy.generate_signal(df)
                signal = signal_obj.signal_type if hasattr(signal_obj, 'signal_type') else signal_obj
                
                signal_name = {-1: '🔴 SELL', 0: '⚪ HOLD', 1: '🟢 BUY'}.get(signal, signal)
                logger.info(f"   Signal: {signal_name}")
                
                pred_id = await db.save_prediction(
                    symbol=symbol,
                    model_version_id=model_info['id'],
                    predicted_signal=signal,
                    confidence=0.75,
                    entry_price=float(df['close'].iloc[-1])
                )
                
                logger.info(f"   ✅ Prediction logged (ID: {pred_id})")
                
                await collector.disconnect()
                
            except Exception as e:
                logger.error(f"   ❌ Failed: {e}")
                import traceback
                traceback.print_exc()
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ Live prediction test complete")
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    result = asyncio.run(testLivePredictions())
    sys.exit(0 if result else 1)
