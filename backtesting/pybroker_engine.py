"""
PyBroker backtesting engine with monitoring integration.

Replaces custom backtesting implementation with PyBroker's
built-in backtesting and walk-forward validation.
Includes monitoring hooks for trade tracking and alerts.
"""
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import pandas as pd
from pybroker import Backtest, YFinance
from loguru import logger

from config.settings import settings
from strategies.base import BaseStrategy
from monitoring.logger import TradingLogger
from monitoring.metrics_collector import MetricsCollector
from monitoring.alerts import TelegramAlert


@dataclass
class BacktestResult:
    """Backtest results container."""
    strategy_name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    total_return: float
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    start_date: str
    end_date: str
    initial_balance: float
    final_balance: float
    detailed_stats: Dict[str, Any]


class BacktestEngine:
    """
    Backtesting engine using PyBroker.
    
    Provides:
    - Historical data backtesting
    - Performance metrics
    - Walk-forward validation
    - Risk-adjusted returns
    - Monitoring integration (logging, metrics, alerts)
    """
    
    def __init__(
        self,
        initial_balance: float = None,
        commission: float = None,
        slippage: float = None,
        enable_monitoring: bool = True
    ):
        """
        Initialize backtest engine.
        
        Args:
            initial_balance: Starting balance
            commission: Commission rate
            slippage: Slippage rate
            enable_monitoring: Enable monitoring and alerts
        """
        self.initial_balance = initial_balance or settings.backtest.initial_balance
        self.commission = commission or settings.backtest.trading_fee
        self.slippage = slippage or settings.backtest.slippage
        self.enable_monitoring = enable_monitoring
        
        # Initialize monitoring components
        if enable_monitoring:
            self.logger = TradingLogger()
            self.metrics = MetricsCollector()
            self.alerts = TelegramAlert()
        else:
            self.logger = None
            self.metrics = None
            self.alerts = None
    
    def run(
        self,
        symbol: str,
        strategy: BaseStrategy,
        start_date: str = None,
        end_date: str = None,
        benchmark_symbol: str = None
    ) -> BacktestResult:
        """
        Run backtest on historical data.
        
        Args:
            symbol: Trading symbol (YFinance format, e.g., 'BTC-USD')
            strategy: Trading strategy to test
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            benchmark_symbol: Benchmark symbol for comparison
            
        Returns:
            Backtest results
        """
        start_date = start_date or settings.backtest.start_date
        end_date = end_date or settings.backtest.end_date
        
        logger.info(f"Starting backtest: {symbol} [{start_date} to {end_date}]")
        
        try:
            # Initialize data source
            data_source = YFinance()
            
            # Build PyBroker strategy
            pb_strategy = strategy.build_strategy()
            
            if pb_strategy is None:
                logger.error("Failed to build strategy")
                return None
            
            # Run backtest
            result = Backtest(
                data_source,
                pb_strategy,
                cash=self.initial_balance,
                commission=self.commission
            ).backtest(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                benchmark=benchmark_symbol
            )
            
            # Extract results
            backtest_result = self._parse_results(
                result,
                strategy.name,
                symbol,
                start_date,
                end_date
            )
            
            # Log results if monitoring enabled
            if self.logger:
                self.logger.log_backtest(
                    strategy_name=strategy.name,
                    symbol=symbol,
                    total_trades=backtest_result.total_trades,
                    win_rate=backtest_result.win_rate,
                    total_return=backtest_result.total_return,
                    sharpe=backtest_result.sharpe_ratio
                )
            
            logger.info(
                f"Backtest complete: "
                f"Trades={backtest_result.total_trades}, "
                f"Return={backtest_result.total_return:.2f}%, "
                f"Sharpe={backtest_result.sharpe_ratio:.2f}"
            )
            
            return backtest_result
        
        except Exception as e:
            logger.error(f"Backtest error: {e}")
            if self.alerts:
                try:
                    asyncio.run(self.alerts.risk_alert(
                        event_type="Backtest Error",
                        details=str(e)
                    ))
                except:
                    pass
            raise
    
    def _parse_results(
        self,
        result: Any,
        strategy_name: str,
        symbol: str,
        start_date: str,
        end_date: str
    ) -> BacktestResult:
        """Parse PyBroker backtest results."""
        
        stats = result.stats if hasattr(result, 'stats') else {}
        trades = result.trades if hasattr(result, 'trades') else []
        
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.pnl > 0)
        losing_trades = total_trades - winning_trades
        
        total_pnl = sum(t.pnl for t in trades) if trades else 0
        total_return = (result.final_balance - self.initial_balance) / self.initial_balance if hasattr(result, 'final_balance') else 0
        
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # Calculate profit factor
        gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        return BacktestResult(
            strategy_name=strategy_name,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            total_pnl=total_pnl,
            total_return=total_return * 100,
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=stats.get('sharpe', 0) if isinstance(stats, dict) else 0,
            max_drawdown=abs(stats.get('max_drawdown', 0)) if isinstance(stats, dict) else 0,
            start_date=start_date,
            end_date=end_date,
            initial_balance=self.initial_balance,
            final_balance=result.final_balance if hasattr(result, 'final_balance') else self.initial_balance,
            detailed_stats=stats
        )
    
    def walk_forward_validation(
        self,
        symbol: str,
        strategy: BaseStrategy,
        start_date: str,
        end_date: str,
        train_size: int = 252,
        test_size: int = 63
    ) -> List[BacktestResult]:
        """
        Perform walk-forward validation.
        
        Args:
            symbol: Trading symbol (YFinance format)
            strategy: Trading strategy to test
            start_date: Overall start date
            end_date: Overall end date
            train_size: Training size in days
            test_size: Testing size in days
            
        Returns:
            List of backtest results for each fold
        """
        logger.info(
            f"Walk-forward validation: {symbol} "
            f"({train_size}d train, {test_size}d test)"
        )
        
        results = []
        
        try:
            start = pd.Timestamp(start_date)
            end = pd.Timestamp(end_date)
            
            fold_idx = 0
            
            while start < end:
                test_start = start + pd.Timedelta(days=train_size)
                test_end = test_start + pd.Timedelta(days=test_size)
                
                if test_end > end:
                    break
                
                # Run backtest on test period
                result = self.run(
                    symbol,
                    strategy,
                    test_start.strftime("%Y-%m-%d"),
                    test_end.strftime("%Y-%m-%d")
                )
                
                if result:
                    results.append(result)
                    fold_idx += 1
                    
                    logger.info(f"WF Fold {fold_idx}: Win rate={result.win_rate*100:.1f}%, Return={result.total_return:.2f}%")
                
                start = test_start
            
            logger.info(f"Walk-forward validation: {len(results)} folds completed")
            
        except Exception as e:
            logger.error(f"Walk-forward validation error: {e}")
        
        return results
    
    def print_report(self, result: BacktestResult) -> None:
        """Print backtest report."""
        report = f"""
╔═══════════════════════════════════════════════════════════╗
║              BACKTEST PERFORMANCE REPORT                  ║
╠═══════════════════════════════════════════════════════════╣
║ Strategy:           {result.strategy_name:<35} ║
║ Period:             {result.start_date} to {result.end_date}          ║
║                                                           ║
║ SUMMARY                                                   ║
║ ─────────────────────────────────────────────────────── ║
║ Total Trades:       {result.total_trades:<35} ║
║ Winning Trades:     {result.winning_trades:<35} ║
║ Losing Trades:      {result.losing_trades:<35} ║
║ Win Rate:           {result.win_rate*100:.1f}%{' '*31}║
║                                                           ║
║ PERFORMANCE                                               ║
║ ─────────────────────────────────────────────────────── ║
║ Initial Balance:    ${result.initial_balance:>13,.2f}{' '*20} ║
║ Final Balance:      ${result.final_balance:>13,.2f}{' '*20} ║
║ Total Return:       {result.total_return:>13.2f}%{' '*20}║
║ Total PnL:          ${result.total_pnl:>13,.2f}{' '*20} ║
║                                                           ║
║ RISK METRICS                                              ║
║ ─────────────────────────────────────────────────────── ║
║ Sharpe Ratio:       {result.sharpe_ratio:>13.2f}{' '*20}║
║ Max Drawdown:       {result.max_drawdown*100:>13.1f}%{' '*20}║
║ Profit Factor:      {result.profit_factor:>13.2f}{' '*20}║
╚═══════════════════════════════════════════════════════════╝
"""
        print(report)
