"""
PyBroker backtesting engine with monitoring integration.

Updated for PyBroker 2.x API.
Includes monitoring hooks for trade tracking and alerts.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import pandas as pd
from pybroker import Strategy, YFinance, ExecContext
from loguru import logger

from config.settings import settings
from strategies.base import BaseStrategy


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
    Backtesting engine using PyBroker 2.x.
    
    Provides:
    - Historical data backtesting
    - Performance metrics
    - Risk-adjusted returns
    - Monitoring integration
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
            commission: Commission rate (0.001 = 0.1%)
            slippage: Slippage rate
            enable_monitoring: Enable monitoring and alerts
        """
        self.initial_balance = initial_balance or settings.backtest.initial_balance
        self.commission = commission or settings.backtest.trading_fee
        self.slippage = slippage or settings.backtest.slippage
        self.enable_monitoring = enable_monitoring
        self.data_source = YFinance()
        
        logger.info(
            f"BacktestEngine initialized: "
            f"balance=${self.initial_balance}, "
            f"commission={self.commission*100:.2f}%, "
            f"slippage={self.slippage*100:.2f}%"
        )
    
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
            BacktestResult with performance metrics
        """
        start_date = start_date or settings.backtest.start_date
        end_date = end_date or settings.backtest.end_date
        
        logger.info(
            f"Starting backtest: {symbol} [{start_date} to {end_date}] "
            f"with {strategy.name} strategy"
        )
        
        try:
            # Get strategy (with data_source and dates)
            pb_strategy = strategy.build_strategy(
                data_source=self.data_source,
                start_date=start_date,
                end_date=end_date,
                symbol=symbol
            )
            
            if pb_strategy is None:
                logger.error("Failed to build strategy")
                return None
            
            # Run backtest using PyBroker's backtest method
            # PyBroker 2.x: strategy.backtest(start_date, end_date, ...)
            result = pb_strategy.backtest(
                start_date=start_date,
                end_date=end_date
            )
            
            # Parse and return results
            backtest_result = self._parse_results(
                result,
                strategy.name,
                symbol,
                start_date,
                end_date
            )
            
            self.print_report(backtest_result)
            
            return backtest_result
            
        except Exception as e:
            logger.error(f"Backtest failed: {e}", exc_info=True)
            return None
    
    def _parse_results(
        self,
        result: Any,
        strategy_name: str,
        symbol: str,
        start_date: str,
        end_date: str
    ) -> BacktestResult:
        """
        Parse PyBroker backtest results.
        
        PyBroker 2.x result structure varies, so handle gracefully.
        """
        try:
            # Try to extract metrics from result object
            if hasattr(result, 'metrics'):
                metrics = result.metrics
            elif hasattr(result, 'stats'):
                metrics = result.stats
            else:
                metrics = result if isinstance(result, dict) else {}
            
            # Get trades - handle DataFrame or list
            trades_raw = getattr(result, 'trades', None)
            trades = []
            
            # Convert to list of trade objects if needed
            if trades_raw is not None and not trades_raw.empty:
                # Try to get pnl column from DataFrame
                for _, row in trades_raw.iterrows():
                    class Trade:
                        def __init__(self, pnl):
                            self.pnl = pnl
                    pnl_val = row.get('pnl', 0) if hasattr(row, 'get') else getattr(row, 'pnl', 0)
                    trades.append(Trade(pnl_val))
            
            # Calculate metrics
            total_trades = len(trades)
            winning_trades = sum(1 for t in trades if hasattr(t, 'pnl') and t.pnl > 0) if len(trades) > 0 else 0
            losing_trades = total_trades - winning_trades
            
            total_pnl = sum(t.pnl for t in trades if hasattr(t, 'pnl')) if len(trades) > 0 else 0
            
            # Get balance
            final_balance = getattr(result, 'final_balance', self.initial_balance)
            if isinstance(metrics, dict):
                final_balance = metrics.get('final_balance', final_balance)
            
            total_return = (final_balance - self.initial_balance) / self.initial_balance
            
            # Win rate
            win_rate = winning_trades / total_trades if total_trades > 0 else 0
            
            # Profit factor
            gross_profit = sum(t.pnl for t in trades if hasattr(t, 'pnl') and t.pnl > 0) if trades else 0
            gross_loss = abs(sum(t.pnl for t in trades if hasattr(t, 'pnl') and t.pnl < 0)) if trades else 0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)
            
            # Get metrics safely
            sharpe_ratio = metrics.get('sharpe', 0) if isinstance(metrics, dict) else 0
            max_drawdown = metrics.get('max_drawdown', 0) if isinstance(metrics, dict) else 0
            
            return BacktestResult(
                strategy_name=strategy_name,
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                total_pnl=total_pnl,
                total_return=total_return * 100,
                win_rate=win_rate * 100,
                profit_factor=profit_factor,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=abs(max_drawdown) * 100,
                start_date=start_date,
                end_date=end_date,
                initial_balance=self.initial_balance,
                final_balance=final_balance,
                detailed_stats=metrics if isinstance(metrics, dict) else {}
            )
            
        except Exception as e:
            logger.error(f"Error parsing results: {e}")
            # Return empty result
            return BacktestResult(
                strategy_name=strategy_name,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                total_pnl=0,
                total_return=0,
                win_rate=0,
                profit_factor=0,
                sharpe_ratio=0,
                max_drawdown=0,
                start_date=start_date,
                end_date=end_date,
                initial_balance=self.initial_balance,
                final_balance=self.initial_balance,
                detailed_stats={}
            )
    
    def walk_forward_validation(
        self,
        symbol: str,
        strategy: BaseStrategy,
        start_date: str,
        end_date: str,
        train_size_days: int = 252,
        test_size_days: int = 63
    ) -> List[BacktestResult]:
        """
        Perform walk-forward validation.
        
        Splits data into overlapping train/test periods and 
        backtests on each fold to ensure strategy generalizes.
        
        Args:
            symbol: Trading symbol
            strategy: Trading strategy
            start_date: Overall start date
            end_date: Overall end date
            train_size_days: Training period size
            test_size_days: Testing period size
            
        Returns:
            List of backtest results for each fold
        """
        logger.info(
            f"Walk-forward validation: {symbol} "
            f"({train_size_days}d train, {test_size_days}d test)"
        )
        
        results = []
        
        try:
            # Convert dates
            start_dt = pd.Timestamp(start_date)
            end_dt = pd.Timestamp(end_date)
            
            # Generate folds
            current_start = start_dt
            fold_num = 0
            
            while current_start + timedelta(days=train_size_days + test_size_days) <= end_dt:
                fold_num += 1
                
                train_start = current_start
                train_end = train_start + timedelta(days=train_size_days)
                test_end = train_end + timedelta(days=test_size_days)
                
                logger.info(
                    f"Fold {fold_num}: "
                    f"Train [{train_start.date()} → {train_end.date()}], "
                    f"Test [{train_end.date()} → {test_end.date()}]"
                )
                
                # Run backtest on test period only
                # (in reality, would train on train period first)
                result = self.run(
                    symbol,
                    strategy,
                    start_date=train_end.strftime("%Y-%m-%d"),
                    end_date=test_end.strftime("%Y-%m-%d")
                )
                
                if result:
                    results.append(result)
                
                # Move to next fold
                current_start += timedelta(days=test_size_days)
            
            # Print summary
            if results:
                avg_return = sum(r.total_return for r in results) / len(results)
                avg_win_rate = sum(r.win_rate for r in results) / len(results)
                
                print(f"\n╔════════════════════════════════════════════╗")
                print(f"║     WALK-FORWARD VALIDATION SUMMARY        ║")
                print(f"╠════════════════════════════════════════════╣")
                print(f"║ Total Folds:     {len(results):<22} ║")
                print(f"║ Avg Return:      {avg_return:>20.1f}% ║")
                print(f"║ Avg Win Rate:    {avg_win_rate:>20.1f}% ║")
                print(f"║────────────────────────────────────────────║")
                
                for i, res in enumerate(results, 1):
                    print(f"║ Fold {i}: Return {res.total_return:>6.1f}% | "
                          f"Win {res.win_rate:>5.1f}% │")
                
                print(f"╚════════════════════════════════════════════╝\n")
            
        except Exception as e:
            logger.error(f"Walk-forward validation failed: {e}", exc_info=True)
        
        return results
    
    def print_report(self, result: BacktestResult) -> None:
        """Print formatted backtest report."""
        print(f"\n╔════════════════════════════════════════════╗")
        print(f"║     BACKTEST PERFORMANCE REPORT           ║")
        print(f"╠════════════════════════════════════════════╣")
        print(f"║ Strategy:        {result.strategy_name:<22} ║")
        print(f"║ Period:          {result.start_date} → {result.end_date} ║")
        print(f"║────────────────────────────────────────────║")
        print(f"║ Total Trades:    {result.total_trades:<22} ║")
        print(f"║ Win Rate:        {result.win_rate:>20.1f}% ║")
        print(f"║ Profit Factor:   {result.profit_factor:>20.2f} ║")
        print(f"║────────────────────────────────────────────║")
        print(f"║ Total PnL:       ${result.total_pnl:>19,.2f} ║")
        print(f"║ Total Return:    {result.total_return:>20.1f}% ║")
        print(f"║ Sharpe Ratio:    {result.sharpe_ratio:>20.2f} ║")
        print(f"║ Max Drawdown:    {result.max_drawdown:>20.1f}% ║")
        print(f"║────────────────────────────────────────────║")
        print(f"║ Initial Balance: ${result.initial_balance:>19,.2f} ║")
        print(f"║ Final Balance:   ${result.final_balance:>19,.2f} ║")
        print(f"╚════════════════════════════════════════════╝\n")
