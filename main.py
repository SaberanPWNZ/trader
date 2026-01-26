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
    logger.warning("⚠️ Backtest mode not available - PyBroker not installed")
    logger.info("Available modes: force-train, scheduler, bot")
    sys.exit(1)




async def run_grid_trading(args):
    from paper.grid_simulator import GridPaperSimulator
    from monitoring.alerts import telegram
    
    logger.info("🔲 Starting Grid Trading mode")
    
    grid_symbols = ["BTC/USDT", "ETH/USDT"]
    initial_balance = args.initial_balance if hasattr(args, 'initial_balance') and args.initial_balance else 300.0
    
    simulator = GridPaperSimulator(
        symbols=grid_symbols,
        initial_balance=initial_balance
    )
    
    try:
        await simulator.start()
    except KeyboardInterrupt:
        logger.info("Stopping grid trading...")
    finally:
        await simulator.stop()


async def run_paper_trading(args):
    from paper.simulator import PaperTradingSimulator
    from strategies.ai_strategy import AIStrategy
    from strategies.rule_based import RuleBasedStrategy
    from learning.database import LearningDatabase
    from monitoring.alerts import telegram
    
    logger.info("📄 Starting Paper Trading mode")
    
    symbols = settings.trading.symbols
    logger.info(f"Trading symbols: {', '.join(symbols)}")
    
    db = LearningDatabase()
    await db.initialize()
    
    if args.strategy == "ai":
        for sym in symbols:
            deployed = await db.get_deployed_model(sym)
            if deployed:
                logger.info(f"Found model for {sym}: {deployed['model_path']}")
            else:
                logger.warning(f"No deployed model for {sym}")
        
        strategy = AIStrategy(db=db)
    else:
        logger.info(f"🎯 Using Rule-Based Strategy (RSI+MACD+EMA)")
        strategy = RuleBasedStrategy()
    
    initial_balance = args.initial_balance or settings.backtest.initial_balance
    
    simulator = PaperTradingSimulator(
        strategy=strategy,
        initial_balance=initial_balance,
        db=db,
        symbols=symbols
    )
    
    await telegram.send_message(
        f"📄 Paper trading started\n"
        f"Symbols: {', '.join(symbols)}\n"
        f"Strategy: {args.strategy}\n"
        f"Balance: ${initial_balance:,.2f}"
    )
    
    try:
        await simulator.start()
        
        while True:
            await asyncio.sleep(60)
            status = simulator.get_status()
            logger.info(
                f"Paper: Balance=${status['balance']:,.2f} "
                f"PnL=${status['total_pnl']:,.2f} "
                f"Trades={status['total_trades']} "
                f"WinRate={status['win_rate']:.1%}"
            )
    except KeyboardInterrupt:
        logger.info("Stopping paper trading...")
    finally:
        await simulator.stop()
        await telegram.send_message(
            f"📄 Paper trading stopped\n"
            f"Final PnL: ${simulator.stats.total_pnl:,.2f}\n"
            f"Total Trades: {simulator.stats.total_trades}"
        )




async def run_live_trading(args):
    from exchange.client import ExchangeClient
    from exchange.factory import create_exchange
    from execution.executor import TradeExecutor
    from strategies.ai_strategy import AIStrategy
    from strategies.rule_based import RuleBasedStrategy
    from learning.database import LearningDatabase
    from risk.manager import RiskManager
    from monitoring.alerts import telegram
    import yfinance as yf
    
    if not args.confirm:
        logger.error("❌ Live trading requires --confirm flag")
        logger.warning("⚠️ THIS WILL TRADE WITH REAL MONEY!")
        logger.info("   Add --confirm to proceed")
        sys.exit(1)
    
    if not settings.exchange.api_key or not settings.exchange.api_secret:
        logger.error("❌ Exchange API keys not configured")
        logger.info("   Set BINANCE_API_KEY and BINANCE_API_SECRET in .env")
        sys.exit(1)
    
    logger.warning("🚨 STARTING LIVE TRADING - REAL MONEY AT RISK 🚨")
    
    symbols = settings.trading.symbols
    
    if args.strategy == "ai":
        db = LearningDatabase()
        await db.initialize()
        
        model_path = args.model
        if not model_path:
            deployed = await db.get_deployed_model(symbols[0])
            if deployed:
                model_path = deployed['model_path']
        
        if not model_path:
            logger.error(f"No deployed model for {symbols[0]}")
            sys.exit(1)
        
        strategy = AIStrategy(model_path=model_path)
    else:
        strategy = RuleBasedStrategy()
    
    exchange = create_exchange(testnet=settings.exchange.testnet)
    await exchange.connect()
    
    validation = await exchange.validate_connection()
    if not validation['success']:
        logger.error(f"Exchange connection failed: {validation['error']}")
        sys.exit(1)
    
    logger.info(f"✅ Connected to {exchange.exchange_id}")
    logger.info(f"   Testnet: {exchange.testnet}")
    logger.info(f"   Balance: {validation['balance']} USDT")
    
    balance = await exchange.get_available_balance('USDT')
    risk_manager = RiskManager(portfolio_value=balance)
    executor = TradeExecutor(exchange, risk_manager)
    
    db = LearningDatabase()
    await db.initialize()
    executor.set_learning_db(db)
    
    await telegram.send_message(
        f"🚨 LIVE TRADING STARTED\n"
        f"Exchange: {exchange.exchange_id}\n"
        f"Testnet: {exchange.testnet}\n"
        f"Balance: ${balance:,.2f}\n"
        f"Strategy: {args.strategy}"
    )
    
    try:
        while True:
            for symbol in symbols:
                try:
                    yf_symbol = settings.get_symbol_for_pybroker(symbol)
                    ticker = yf.Ticker(yf_symbol)
                    data = ticker.history(period="7d", interval="1h")
                    
                    if data.empty:
                        continue
                    
                    data = data.reset_index()
                    data.columns = [c.lower() for c in data.columns]
                    data['symbol'] = symbol
                    
                    signal = strategy.generate_signal(data)
                    
                    if signal.signal_type != 0:
                        result = await executor.execute_signal(signal)
                        if result and result.success:
                            await telegram.send_message(
                                f"📈 Trade executed\n"
                                f"Symbol: {symbol}\n"
                                f"Side: {result.side}\n"
                                f"Amount: {result.amount}\n"
                                f"Price: ${result.average_price:,.2f}"
                            )
                    
                except Exception as e:
                    logger.error(f"Error processing {symbol}: {e}")
            
            await asyncio.sleep(300)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await executor.close_all_positions("Shutdown")
        await exchange.disconnect()
        await telegram.send_message("🛑 LIVE TRADING STOPPED")




async def train_model(args):
    logger.warning("⚠️ Use: python main.py force-train <symbol>")
    logger.info("Available modes: force-train, scheduler, bot")
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
    logger.warning("⚠️ Backtest mode not available - PyBroker not installed")
    logger.info("Available modes: force-train, scheduler, bot")
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
    
    # Grid trading parser
    grid_parser = subparsers.add_parser("grid", help="Run grid trading bot")
    grid_parser.add_argument("--initial-balance", type=float, default=300.0, help="Initial balance for grid trading")
    
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
    elif args.mode == "grid":
        asyncio.run(run_grid_trading(args))
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
