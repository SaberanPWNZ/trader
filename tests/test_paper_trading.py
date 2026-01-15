#!/usr/bin/env python3
import asyncio
import sys
from datetime import datetime
from loguru import logger

sys.path.insert(0, '.')

from config.settings import settings
from paper.simulator import PaperTradingSimulator
from strategies.rule_based import RuleBasedStrategy
from strategies.ai_strategy import AIStrategy
from learning.database import LearningDatabase


async def testPaperSimulatorInit():
    logger.info("Testing paper simulator initialization...")
    
    strategy = RuleBasedStrategy()
    
    simulator = PaperTradingSimulator(
        strategy=strategy,
        initial_balance=10000.0,
        symbols=['BTC/USDT']
    )
    
    logger.info(f"✅ Simulator initialized")
    logger.info(f"   Balance: ${simulator.initial_balance:,.2f}")
    logger.info(f"   Symbols: {simulator.symbols}")
    logger.info(f"   Fee rate: {simulator.fee_rate:.2%}")
    
    return True


async def testPaperSimulatorWithDB():
    logger.info("Testing paper simulator with database...")
    
    db = LearningDatabase()
    await db.initialize()
    
    strategy = RuleBasedStrategy()
    
    simulator = PaperTradingSimulator(
        strategy=strategy,
        initial_balance=10000.0,
        db=db,
        symbols=['BTC/USDT']
    )
    
    logger.info(f"✅ Simulator with DB initialized")
    logger.info(f"   Prediction tracker: {'enabled' if simulator.prediction_tracker else 'disabled'}")
    
    return True


async def testDataFetching():
    logger.info("Testing market data fetching...")
    
    strategy = RuleBasedStrategy()
    simulator = PaperTradingSimulator(
        strategy=strategy,
        initial_balance=10000.0,
        symbols=['BTC/USDT']
    )
    
    data = await simulator._fetch_market_data('BTC/USDT', limit=100)
    
    if data.empty:
        logger.error("❌ No data fetched")
        return False
    
    logger.info(f"✅ Fetched {len(data)} candles")
    logger.info(f"   Columns: {list(data.columns)}")
    logger.info(f"   Latest close: ${data['close'].iloc[-1]:,.2f}")
    
    return True


async def testSignalGeneration():
    logger.info("Testing signal generation...")
    
    strategy = RuleBasedStrategy()
    simulator = PaperTradingSimulator(
        strategy=strategy,
        initial_balance=10000.0,
        symbols=['BTC/USDT']
    )
    
    data = await simulator._fetch_market_data('BTC/USDT', limit=200)
    
    if data.empty:
        logger.warning("No data available, skipping signal test")
        return True
    
    signal = strategy.generate_signal(data)
    
    logger.info(f"✅ Signal generated")
    logger.info(f"   Symbol: {signal.symbol}")
    logger.info(f"   Type: {signal.signal_type}")
    logger.info(f"   Confidence: {signal.confidence:.1%}")
    logger.info(f"   Entry: ${signal.entry_price:,.2f}" if signal.entry_price else "   Entry: N/A")
    
    return True


async def testSimulatorStatus():
    logger.info("Testing simulator status...")
    
    strategy = RuleBasedStrategy()
    simulator = PaperTradingSimulator(
        strategy=strategy,
        initial_balance=10000.0,
        symbols=['BTC/USDT']
    )
    
    status = simulator.get_status()
    
    logger.info(f"✅ Status retrieved")
    logger.info(f"   Running: {status['running']}")
    logger.info(f"   Balance: ${status['balance']:,.2f}")
    logger.info(f"   Equity: ${status['equity']:,.2f}")
    logger.info(f"   Open positions: {status['open_positions']}")
    logger.info(f"   Total trades: {status['total_trades']}")
    
    return True


async def main():
    logger.info("🧪 Paper Trading Test Suite")
    logger.info(f"   Date: {datetime.now()}")
    logger.info("")
    
    results = {}
    
    try:
        results['init'] = await testPaperSimulatorInit()
        print()
        
        results['db_init'] = await testPaperSimulatorWithDB()
        print()
        
        results['data_fetch'] = await testDataFetching()
        print()
        
        results['signal_gen'] = await testSignalGeneration()
        print()
        
        results['status'] = await testSimulatorStatus()
        print()
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
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
