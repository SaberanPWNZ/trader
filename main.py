#!/usr/bin/env python3
"""
Crypto AI Trading Bot - Main Entry Point

A fully autonomous AI-powered trading bot for cryptocurrency markets.
Supports backtesting, paper trading, and live trading modes.
Now using PyBroker framework for simplified backtesting and execution.
"""
import asyncio
import argparse
import sys
from datetime import datetime
from loguru import logger

from config.settings import settings
from monitoring.logger import setup_logging
from monitoring.alerts import telegram


async def run_backtest(args):
    """Run backtesting mode using PyBroker."""
    from strategies.rule_based_pb import RuleBasedStrategy
    from strategies.ai_strategy_pb import AIStrategy
    from backtesting.pybroker_engine import BacktestEngine
    
    logger.info("Starting backtest mode with PyBroker")
    
    # Get YFinance symbol from crypto pair
    yf_symbol = settings.get_symbol_for_pybroker(args.symbol)
    
    # Initialize strategy
    if args.strategy == "ai":
        strategy = AIStrategy(model_path=args.model)
    else:
        strategy = RuleBasedStrategy()
    
    try:
        # Run backtest using PyBroker engine
        logger.info(f"Running backtest for {args.symbol} ({yf_symbol}) from {args.start_date} to {args.end_date}")
        
        engine = BacktestEngine(
            initial_balance=args.initial_balance or settings.backtest.initial_balance,
            commission=settings.pybroker.commission,
            slippage=settings.pybroker.slippage,
        )
        
        result = engine.run(
            symbol=yf_symbol,
            strategy=strategy,
            start_date=args.start_date or settings.backtest.start_date,
            end_date=args.end_date or settings.backtest.end_date
        )
        
        # Print results
        engine.print_report(result)
        
        # Optional: Walk-forward validation
        if args.walk_forward:
            logger.info("Running walk-forward validation...")
            wf_results = engine.walk_forward_validation(
                symbol=yf_symbol,
                strategy=strategy,
                start_date=args.start_date or settings.backtest.start_date,
                end_date=args.end_date or settings.backtest.end_date,
                train_size=settings.backtest.walk_forward_periods,
                test_size=settings.backtest.walk_forward_test_size,
            )
            print(f"\n{'='*60}")
            print("WALK-FORWARD VALIDATION RESULTS")
            print(f"{'='*60}")
            for i, result in enumerate(wf_results):
                print(f"\nFold {i+1}:")
                engine.print_report(result)
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        sys.exit(1)




async def run_paper_trading(args):
    """Run paper trading mode using PyBroker."""
    from strategies.rule_based_pb import RuleBasedStrategy
    from strategies.ai_strategy_pb import AIStrategy
    from backtesting.pybroker_engine import BacktestEngine
    
    logger.info("Starting paper trading mode with PyBroker")
    
    # Get YFinance symbol
    yf_symbol = settings.get_symbol_for_pybroker(args.symbol)
    
    # Initialize strategy
    if args.strategy == "ai":
        strategy = AIStrategy(model_path=args.model)
    else:
        strategy = RuleBasedStrategy()
    
    try:
        # Run paper trading (similar to backtest but on live data)
        logger.info(f"Paper trading for {args.symbol} ({yf_symbol})")
        
        engine = BacktestEngine(
            initial_balance=args.initial_balance or settings.backtest.initial_balance
        )
        
        # Use recent data (last 3 months)
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        
        result = engine.run(
            symbol=yf_symbol,
            strategy=strategy,
            start_date=start_date,
            end_date=end_date
        )
        
        logger.info("Paper trading completed")
        engine.print_report(result)
        
        # Send notification
        await telegram.system_status("online", "Paper trading completed")
        
    except Exception as e:
        logger.error(f"Paper trading failed: {e}")
        await telegram.system_status("error", f"Paper trading error: {e}")
        sys.exit(1)




async def run_live_trading(args):
    """Run live trading mode with PyBroker integration."""
    import ccxt.async_support as ccxt
    from strategies.rule_based_pb import RuleBasedStrategy
    from strategies.ai_strategy_pb import AIStrategy
    from execution.pybroker_executor import ExecutionManager
    from risk.kill_switch import KillSwitch
    
    logger.warning("⚠️ LIVE TRADING MODE - Real money at risk!")
    
    if not args.confirm:
        print("\n" + "="*60)
        print("WARNING: Live trading will use real funds!")
        print("Use --confirm flag to acknowledge this risk")
        print("="*60 + "\n")
        return
    
    # Initialize exchange
    exchange_config = {
        'apiKey': settings.exchange.api_key,
        'secret': settings.exchange.api_secret,
        'timeout': settings.exchange.timeout,
        'enableRateLimit': True,
    }
    
    if settings.exchange.testnet:
        exchange_config['options'] = {'sandboxMode': True}
    
    exchange = getattr(ccxt, settings.exchange.name)(exchange_config)
    
    if settings.exchange.testnet:
        exchange.set_sandbox_mode(True)
    
    # Initialize components
    if args.strategy == "ai":
        strategy = AIStrategy(model_path=args.model)
    else:
        strategy = RuleBasedStrategy()
    
    kill_switch = KillSwitch()
    execution_mgr = ExecutionManager()
    
    try:
        await exchange.load_markets()
        logger.info(f"Connected to {settings.exchange.name}")
        
        balance = await exchange.fetch_balance()
        initial_balance = balance.get('total', {}).get('USDT', 10000)
        
        await telegram.system_status(
            "online",
            f"Live trading started\nBalance: ${initial_balance:,.2f}\nStrategy: {args.strategy}"
        )
        
        # Main trading loop
        logger.info("Entering live trading loop")
        while not kill_switch.is_active:
            for symbol in settings.trading.symbols:
                try:
                    # Execute trading logic with execution manager
                    # The execution manager handles risk checks and PyBroker integration
                    status = execution_mgr.get_status()
                    logger.info(f"Execution status for {symbol}: {status}")
                    
                except Exception as e:
                    logger.error(f"Error processing {symbol}: {e}")
            
            await asyncio.sleep(60)
    
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        kill_switch.activate(str(e))
        await telegram.system_status("error", f"Live trading error: {e}")
    finally:
        await exchange.close()
        await telegram.system_status("offline", "Live trading stopped")




async def train_model(args):
    """Train AI model on historical data."""
    from strategies.ai_strategy_pb import AIStrategy
    
    logger.info("Starting AI model training")
    
    # Get YFinance symbol
    yf_symbol = settings.get_symbol_for_pybroker(args.symbol)
    
    try:
        logger.info(f"Training model for {args.symbol} ({yf_symbol})")
        
        # Create and train strategy
        strategy = AIStrategy()
        metrics = strategy.train(
            symbol=yf_symbol,
            start_date=args.start_date,
            end_date=args.end_date
        )
        
        # Save model
        model_path = args.output or f"models/{args.symbol.replace('/', '_')}_{datetime.now():%Y%m%d_%H%M%S}.pkl"
        strategy.save_model(model_path)
        
        print("\n" + "="*60)
        print("MODEL TRAINING COMPLETE")
        print("="*60)
        if 'accuracy' in metrics:
            print(f"Model Accuracy: {metrics['accuracy']:.3f}")
        print(f"Samples processed: {metrics.get('samples', 'N/A')}")
        print(f"Model saved to: {model_path}")
        print("="*60)
        
        logger.info(f"Model training completed and saved to {model_path}")
        
    except Exception as e:
        logger.error(f"Model training failed: {e}")
        sys.exit(1)


# ════════════════════════════════════════════════════════════════════════════
# DEVELOPMENT MODE COMMANDS
# ════════════════════════════════════════════════════════════════════════════


async def dev_generate_data(args):
    """Generate mock data for development."""
    from data.mock_generator import MockDataGenerator, MockConfig
    from data.local_data import LocalDataManager
    
    logger.info("🔧 Development mode: Generating mock data")
    
    # Enable dev mode
    settings.enable_dev_mode()
    
    # Parse date range
    start_date = args.start_date or settings.backtest.start_date
    end_date = args.end_date or settings.backtest.end_date
    symbol = args.symbol or settings.dev.mock_symbol
    
    # Configure mock data
    config = MockConfig(
        base_price=args.base_price or settings.dev.mock_base_price,
        volatility=args.volatility or settings.dev.mock_volatility,
    )
    
    try:
        # Generate and save data
        generator = MockDataGenerator(config)
        df = generator.generate_ohlcv(symbol, start_date, end_date)
        
        # Cache it
        manager = LocalDataManager()
        filepath = manager.save_data(df, symbol, start_date, end_date)
        
        print(f"\n✅ Generated {len(df)} candles")
        print(f"   Symbol: {symbol}")
        print(f"   Range: {start_date} to {end_date}")
        print(f"   Saved: {filepath}\n")
        
    except Exception as e:
        logger.error(f"Failed to generate data: {e}")
        sys.exit(1)


async def dev_backtest(args):
    """Run backtest with mock data (dev mode)."""
    from strategies.rule_based_pb import RuleBasedStrategy
    from strategies.ai_strategy_pb import AIStrategy
    from backtesting.pybroker_engine import BacktestEngine
    from data.local_data import DataLoader
    
    logger.info("🔧 Development mode: Running backtest with mock data")
    
    # Enable dev mode
    settings.enable_dev_mode()
    
    # Get symbol
    symbol = args.symbol or settings.dev.mock_symbol
    yf_symbol = settings.get_symbol_for_pybroker(symbol)
    start_date = args.start_date or settings.backtest.start_date
    end_date = args.end_date or settings.backtest.end_date
    
    # Initialize strategy
    if args.strategy == "ai":
        strategy = AIStrategy(model_path=args.model)
    else:
        strategy = RuleBasedStrategy()
    
    try:
        # Load mock data
        loader = DataLoader()
        data = loader.load_data(yf_symbol, start_date, end_date)
        
        # Run backtest
        logger.info(f"Running backtest on {len(data)} candles of mock data")
        
        engine = BacktestEngine(
            initial_balance=args.initial_balance or settings.backtest.initial_balance
        )
        
        result = engine.run(
            symbol=yf_symbol,
            strategy=strategy,
            start_date=start_date,
            end_date=end_date
        )
        
        # Print results
        engine.print_report(result)
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        sys.exit(1)


async def dev_train(args):
    import pickle
    from sklearn.ensemble import RandomForestClassifier
    from data.mock_generator import generate_training_data
    
    logger.info("🔧 Development mode: Training model with synthetic data")
    
    settings.enable_dev_mode()
    
    try:
        symbol = args.symbol or settings.dev.mock_symbol
        samples = args.samples or 1000
        features = args.features or 20
        
        logger.info(f"Generating {samples} training samples with {features} features")
        X, y = generate_training_data(symbol, samples, features)
        
        logger.info(f"Training RandomForest model on {samples} synthetic samples...")
        model = RandomForestClassifier(n_estimators=50, max_depth=10, random_state=42)
        model.fit(X, y)
        
        import os
        os.makedirs("models", exist_ok=True)
        model_path = args.output or f"models/{symbol}_dev_{datetime.now():%Y%m%d_%H%M%S}.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        
        print(f"\n✅ Model training complete")
        print(f"   Samples: {samples}")
        print(f"   Features: {features}")
        print(f"   Accuracy: {model.score(X, y):.2%}")
        print(f"   Saved: {model_path}\n")
        logger.info(f"Model saved to {model_path}")
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        sys.exit(1)


async def run_scheduler(args):
    from learning.scheduler import LearningScheduler
    from learning.database import LearningDatabase
    
    logger.info("🤖 Starting self-learning scheduler")
    
    settings.self_learning.enabled = True
    if args.interval:
        settings.self_learning.training_interval_hours = args.interval
    if args.auto_deploy:
        settings.self_learning.auto_deploy_enabled = True
    
    symbols = args.symbols or settings.trading.symbols
    
    db = LearningDatabase()
    scheduler = LearningScheduler(db=db, symbols=symbols)
    
    try:
        await scheduler.start()
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Shutting down scheduler...")
    finally:
        await scheduler.stop()


async def run_telegram_bot(args):
    from learning.telegram_bot import LearningTelegramBot
    from learning.scheduler import LearningScheduler
    from learning.database import LearningDatabase
    
    logger.info("🤖 Starting Telegram bot")
    
    settings.monitoring.telegram_commands_enabled = True
    
    db = LearningDatabase()
    scheduler = LearningScheduler(db=db)
    
    async def on_train(symbol: str) -> dict:
        return await scheduler.force_train(symbol)
    
    bot = LearningTelegramBot(db=db, on_train_command=on_train)
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Shutting down bot...")
    finally:
        await bot.stop()


async def run_force_train(args):
    from learning.scheduler import LearningScheduler
    from learning.database import LearningDatabase
    
    symbol = args.symbol
    if "/" not in symbol:
        symbol = f"{symbol}/USDT"
    
    logger.info(f"🤖 Force training model for {symbol}")
    
    db = LearningDatabase()
    scheduler = LearningScheduler(db=db)
    
    result = await scheduler.force_train(symbol)
    
    if result["status"] == "success":
        print(f"\n✅ Training complete")
        print(f"   Model ID: {result['model_id']}")
        print(f"   Train Accuracy: {result['train_accuracy']:.1%}")
        print(f"   Test Accuracy: {result['test_accuracy']:.1%}")
        print(f"   Samples: {result['samples']:,}")
        print(f"   Improvement: {result['improvement']:.1%}")
        print(f"   Should deploy: {result['should_deploy']}\n")
    else:
        print(f"\n❌ Training failed: {result.get('error', 'Unknown')}\n")
        sys.exit(1)


def dev_list_data(args):
    """List cached local data files."""
    from data.local_data import LocalDataManager
    
    logger.info("🔧 Listing cached data files")
    
    settings.enable_dev_mode()
    
    try:
        manager = LocalDataManager()
        summary = manager.get_data_summary()
        
        print(f"\n📊 Cached Data Files")
        print(f"   Total files: {summary['total_files']}")
        print(f"   Total size: {summary['total_size_mb']:.2f} MB")
        
        if summary['files']:
            print(f"\n   Files:")
            for file_info in summary['files']:
                print(f"     - {file_info['name']} ({file_info['size_mb']:.2f} MB)")
        
        print()
        
    except Exception as e:
        logger.error(f"Failed to list data: {e}")
        sys.exit(1)


def dev_clear_cache(args):
    """Clear cached data files."""
    from data.local_data import LocalDataManager
    
    logger.info("🔧 Clearing cache")
    
    settings.enable_dev_mode()
    
    try:
        manager = LocalDataManager()
        symbol = args.symbol or None
        
        count = manager.clear_cache(symbol)
        
        if symbol:
            print(f"\n✅ Deleted {count} cached files for {symbol}\n")
        else:
            print(f"\n✅ Deleted {count} cached files\n")
        
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Crypto AI Trading Bot - PyBroker Edition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run backtest
  python main.py backtest --symbol BTC/USDT --start-date 2024-01-01 --end-date 2024-12-01
  
  # Run backtest with walk-forward validation
  python main.py backtest --symbol BTC/USDT --walk-forward
  
  # Run paper trading
  python main.py paper --symbol BTC/USDT --strategy rule_based
  
  # Run live trading (testnet)
  python main.py live --strategy ai --model models/btc_model.pkl --confirm
  
  # Train AI model
  python main.py train --symbol BTC/USDT --start-date 2024-01-01 --end-date 2024-11-01
        """
    )
    
    subparsers = parser.add_subparsers(dest="mode", help="Trading mode (powered by PyBroker)")
    
    # Backtest parser
    backtest_parser = subparsers.add_parser("backtest", help="Run backtesting with PyBroker")
    backtest_parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair (crypto)")
    backtest_parser.add_argument("--strategy", choices=["rule_based", "ai"], default="rule_based")
    backtest_parser.add_argument("--model", help="Path to AI model file")
    backtest_parser.add_argument("--start-date", help="Backtest start date (YYYY-MM-DD)")
    backtest_parser.add_argument("--end-date", help="Backtest end date (YYYY-MM-DD)")
    backtest_parser.add_argument("--initial-balance", type=float, help="Initial portfolio balance")
    backtest_parser.add_argument("--walk-forward", action="store_true", help="Run walk-forward validation")
    
    # Paper trading parser
    paper_parser = subparsers.add_parser("paper", help="Run paper trading with PyBroker")
    paper_parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair (crypto)")
    paper_parser.add_argument("--strategy", choices=["rule_based", "ai"], default="rule_based")
    paper_parser.add_argument("--model", help="Path to AI model file")
    paper_parser.add_argument("--initial-balance", type=float, help="Initial portfolio balance")
    
    # Live trading parser
    live_parser = subparsers.add_parser("live", help="Run live trading (PyBroker integration)")
    live_parser.add_argument("--strategy", choices=["rule_based", "ai"], default="rule_based")
    live_parser.add_argument("--model", help="Path to AI model file")
    live_parser.add_argument("--confirm", action="store_true", help="Confirm live trading")
    
    # Model training parser
    train_parser = subparsers.add_parser("train", help="Train AI model on historical data")
    train_parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair (crypto)")
    train_parser.add_argument("--start-date", default="2024-01-01", help="Training start date (YYYY-MM-DD)")
    train_parser.add_argument("--end-date", default="2024-11-01", help="Training end date (YYYY-MM-DD)")
    train_parser.add_argument("--output", help="Output model path")
    
    # Dev mode: Generate mock data
    dev_gen_parser = subparsers.add_parser("dev-gen", help="[DEV] Generate mock data")
    dev_gen_parser.add_argument("--symbol", default="BTC-USD", help="Symbol for mock data")
    dev_gen_parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    dev_gen_parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    dev_gen_parser.add_argument("--base-price", type=float, help="Base price for mock data")
    dev_gen_parser.add_argument("--volatility", type=float, help="Daily volatility (0-1)")
    
    # Dev mode: Backtest with mock data
    dev_backtest_parser = subparsers.add_parser("dev-backtest", help="[DEV] Backtest with mock data")
    dev_backtest_parser.add_argument("--symbol", default="BTC-USD", help="Symbol for mock data")
    dev_backtest_parser.add_argument("--strategy", choices=["rule_based", "ai"], default="rule_based")
    dev_backtest_parser.add_argument("--model", help="Path to AI model file")
    dev_backtest_parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    dev_backtest_parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    dev_backtest_parser.add_argument("--initial-balance", type=float, help="Initial balance")
    
    # Dev mode: Train with synthetic data
    dev_train_parser = subparsers.add_parser("dev-train", help="[DEV] Train model with synthetic data")
    dev_train_parser.add_argument("--symbol", default="BTC-USD", help="Symbol name")
    dev_train_parser.add_argument("--samples", type=int, help="Number of training samples")
    dev_train_parser.add_argument("--features", type=int, help="Number of features")
    dev_train_parser.add_argument("--output", help="Output model path")
    
    # Dev mode: List cached data
    dev_list_parser = subparsers.add_parser("dev-list", help="[DEV] List cached data files")
    
    # Dev mode: Clear cache
    dev_clear_parser = subparsers.add_parser("dev-clear", help="[DEV] Clear cached data")
    dev_clear_parser.add_argument("--symbol", help="Clear specific symbol (or all if not set)")
    
    scheduler_parser = subparsers.add_parser("scheduler", help="Run self-learning scheduler")
    scheduler_parser.add_argument("--interval", type=int, help="Training interval in hours")
    scheduler_parser.add_argument("--symbols", nargs="+", help="Symbols to train")
    scheduler_parser.add_argument("--auto-deploy", action="store_true", help="Auto-deploy improved models")
    
    bot_parser = subparsers.add_parser("bot", help="Run Telegram bot for learning control")
    
    force_train_parser = subparsers.add_parser("force-train", help="Force training for a symbol")
    force_train_parser.add_argument("symbol", help="Symbol to train (e.g., BTC/USDT)")
    
    args = parser.parse_args()
    
    if not args.mode:
        parser.print_help()
        return
    
    # Setup logging
    setup_logging()
    
    logger.info(f"Crypto AI Trading Bot (PyBroker) - Mode: {args.mode}")
    
    # Run selected mode
    if args.mode == "backtest":
        asyncio.run(run_backtest(args))
    elif args.mode == "paper":
        asyncio.run(run_paper_trading(args))
    elif args.mode == "live":
        asyncio.run(run_live_trading(args))
    elif args.mode == "train":
        asyncio.run(train_model(args))
    # Dev mode commands
    elif args.mode == "dev-gen":
        asyncio.run(dev_generate_data(args))
    elif args.mode == "dev-backtest":
        asyncio.run(dev_backtest(args))
    elif args.mode == "dev-train":
        asyncio.run(dev_train(args))
    elif args.mode == "dev-list":
        dev_list_data(args)
    elif args.mode == "dev-clear":
        dev_clear_cache(args)
    elif args.mode == "scheduler":
        asyncio.run(run_scheduler(args))
    elif args.mode == "bot":
        asyncio.run(run_telegram_bot(args))
    elif args.mode == "force-train":
        asyncio.run(run_force_train(args))


if __name__ == "__main__":
    main()
