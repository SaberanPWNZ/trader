#!/usr/bin/env python3
import asyncio
import sys
from datetime import datetime
from loguru import logger

sys.path.insert(0, '.')

from config.settings import settings
from learning.database import LearningDatabase
from learning.prediction_tracker import PredictionTracker
from data.models import Signal
from config.constants import SignalType


async def testDatabaseInit():
    logger.info("Testing database initialization...")
    
    db = LearningDatabase(db_path="data/test_learning.db")
    await db.initialize()
    
    logger.info(f"✅ Database initialized at {db.db_path}")
    return True


async def testPredictionLogging():
    logger.info("Testing prediction logging...")
    
    db = LearningDatabase(db_path="data/test_learning.db")
    await db.initialize()
    tracker = PredictionTracker(db)
    
    signal = Signal(
        symbol='BTC/USDT',
        signal_type=SignalType.BUY.value,
        confidence=0.75,
        entry_price=50000.0,
        stop_loss=48000.0,
        take_profit=55000.0,
        timestamp=datetime.utcnow(),
        strategy='test_strategy'
    )
    
    model_id = await db.save_model(
        symbol='BTC/USDT',
        model_type='xgboost',
        train_accuracy=0.65,
        test_accuracy=0.62,
        samples_trained=1000,
        model_path='models/test_model.pkl'
    )
    logger.info(f"✅ Created test model: {model_id}")
    
    pred_id = await tracker.log_prediction(
        symbol='BTC/USDT',
        signal=signal,
        model_id=model_id
    )
    logger.info(f"✅ Logged prediction: {pred_id}")
    
    await tracker.update_prediction_outcome(
        symbol='BTC/USDT',
        actual_outcome=1,
        exit_price=52000.0,
        pnl=200.0
    )
    logger.info("✅ Updated prediction outcome")
    
    accuracy, count = await tracker.get_recent_accuracy('BTC/USDT', days=7)
    logger.info(f"✅ Recent accuracy: {accuracy:.1%} ({count} predictions)")
    
    return True


async def testAccuracyTracking():
    logger.info("Testing accuracy tracking with multiple predictions...")
    
    db = LearningDatabase(db_path="data/test_learning.db")
    await db.initialize()
    
    model_id = await db.save_model(
        symbol='ETH/USDT',
        model_type='xgboost',
        train_accuracy=0.70,
        test_accuracy=0.65,
        samples_trained=500,
        model_path='models/test_eth.pkl'
    )
    
    predictions = [
        {'signal': 2, 'confidence': 0.8, 'outcome': 1, 'pnl': 100},
        {'signal': 2, 'confidence': 0.7, 'outcome': 1, 'pnl': 50},
        {'signal': 0, 'confidence': 0.75, 'outcome': -1, 'pnl': 80},
        {'signal': 2, 'confidence': 0.6, 'outcome': -1, 'pnl': -30},
        {'signal': 0, 'confidence': 0.65, 'outcome': 0, 'pnl': -50},
    ]
    
    for i, p in enumerate(predictions):
        pred_id = await db.save_prediction(
            symbol='ETH/USDT',
            model_version_id=model_id,
            predicted_signal=p['signal'],
            confidence=p['confidence'],
            entry_price=3000.0 + i * 10
        )
        await db.update_prediction_outcome(
            prediction_id=pred_id,
            actual_outcome=p['outcome'],
            exit_price=3000.0 + i * 10 + (p['pnl'] / 10),
            pnl=p['pnl']
        )
    
    accuracy_stats = await db.get_prediction_accuracy('ETH/USDT', days=30)
    logger.info(f"✅ Accuracy stats:")
    logger.info(f"   Total: {accuracy_stats['total_predictions']}")
    logger.info(f"   Correct: {accuracy_stats['correct_predictions']}")
    logger.info(f"   Accuracy: {accuracy_stats['accuracy']:.1%}")
    logger.info(f"   Total PnL: ${accuracy_stats['total_pnl']:.2f}")
    
    return True


async def testPerformanceSummary():
    logger.info("Testing performance summary...")
    
    db = LearningDatabase(db_path="data/test_learning.db")
    await db.initialize()
    
    summary = await db.get_performance_summary(days=30)
    logger.info(f"✅ Performance summary for {len(summary)} symbols")
    
    for symbol, stats in summary.items():
        logger.info(f"   {symbol}:")
        logger.info(f"      Runs: {stats['total_runs']}")
        logger.info(f"      Avg Accuracy: {stats['avg_accuracy']:.1%}")
        logger.info(f"      Best Accuracy: {stats['best_accuracy']:.1%}")
    
    return True


async def main():
    logger.info("🧪 Prediction Tracking Test Suite")
    logger.info(f"   Date: {datetime.now()}")
    logger.info("")
    
    results = {}
    
    try:
        results['db_init'] = await testDatabaseInit()
        print()
        
        results['prediction_logging'] = await testPredictionLogging()
        print()
        
        results['accuracy_tracking'] = await testAccuracyTracking()
        print()
        
        results['performance_summary'] = await testPerformanceSummary()
        print()
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        results['error'] = False
    
    logger.info("=" * 60)
    logger.info("TEST RESULTS")
    logger.info("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"   {test_name}: {status}")
    
    all_passed = all(results.values())
    logger.info("")
    if all_passed:
        logger.info("🎉 All tests passed!")
    else:
        logger.warning("⚠️ Some tests failed")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
