#!/usr/bin/env python3
"""Analyze accumulated learning database."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from learning.database import LearningDatabase
from config.settings import settings
from loguru import logger


async def analyzeDatabase():
    logger.info("📊 Analyzing Learning Database")
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
        
        logger.info(f"\n🎯 Deployed Models: {len(deployed_models)}")
        for model in deployed_models:
            logger.info(f"   {model['symbol']} - {model['model_type']}")
            logger.info(f"      Train Acc: {model['train_accuracy']:.2%}")
            logger.info(f"      Test Acc: {model['test_accuracy']:.2%}")
            logger.info(f"      Samples: {model['samples_trained']}")
            logger.info(f"      Created: {model['created_at']}")
        
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM models ORDER BY created_at DESC")
            all_rows = await cursor.fetchall()
            all_models = [dict(row) for row in all_rows]
        logger.info(f"\n📦 Total Models Trained: {len(all_models)}")
        
        symbols = set(m['symbol'] for m in all_models)
        for symbol in symbols:
            symbol_models = [m for m in all_models if m['symbol'] == symbol]
            logger.info(f"\n   {symbol}: {len(symbol_models)} models")
            
            if symbol_models:
                accuracies = [m['test_accuracy'] for m in symbol_models]
                logger.info(f"      Best Test Accuracy: {max(accuracies):.2%}")
                logger.info(f"      Avg Test Accuracy: {sum(accuracies)/len(accuracies):.2%}")
        
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM training_runs")
            training_count = (await cursor.fetchone())[0]
            logger.info(f"\n🏃 Training Runs: {training_count}")
            
            cursor = await conn.execute("""
                SELECT symbol, COUNT(*), AVG(test_accuracy), AVG(improvement) 
                FROM training_runs 
                WHERE status = 'completed'
                GROUP BY symbol
            """)
            rows = await cursor.fetchall()
            
            for symbol, count, avg_acc, avg_imp in rows:
                logger.info(f"\n   {symbol}:")
                logger.info(f"      Completed runs: {count}")
                logger.info(f"      Avg accuracy: {avg_acc:.2%}")
                logger.info(f"      Avg improvement: {avg_imp:.2%}")
            
            cursor = await conn.execute("SELECT COUNT(*) FROM predictions")
            pred_count = (await cursor.fetchone())[0]
            logger.info(f"\n🎲 Predictions Logged: {pred_count}")
            
            if pred_count > 0:
                cursor = await conn.execute("""
                    SELECT predicted_signal, COUNT(*), 
                           AVG(CASE WHEN actual_signal IS NOT NULL THEN 
                               CASE WHEN predicted_signal = actual_signal THEN 1 ELSE 0 END 
                           END) as accuracy
                    FROM predictions
                    GROUP BY predicted_signal
                """)
                rows = await cursor.fetchall()
                
                for signal, count, accuracy in rows:
                    signal_name = {-1: 'SELL', 0: 'HOLD', 1: 'BUY'}.get(signal, signal)
                    acc_str = f"{accuracy:.2%}" if accuracy else "N/A"
                    logger.info(f"      {signal_name}: {count} predictions, accuracy: {acc_str}")
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ Analysis complete")
        
    except Exception as e:
        logger.error(f"❌ Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    result = asyncio.run(analyzeDatabase())
    sys.exit(0 if result else 1)
