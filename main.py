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


if __name__ == "__main__":
    main()
