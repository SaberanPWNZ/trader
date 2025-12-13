"""
Performance metrics calculation.
"""
from typing import List, Dict, Any
import pandas as pd
import numpy as np
from dataclasses import dataclass


class PerformanceMetrics:
    """
    Calculate trading performance metrics.
    
    Metrics:
    - Total PnL
    - Win rate
    - Profit factor
    - Sharpe ratio
    - Sortino ratio
    - Max drawdown
    - Average trade
    - And more...
    """
    
    def __init__(
        self,
        trades: List,
        equity_curve: pd.Series,
        initial_balance: float
    ):
        """
        Initialize metrics calculator.
        
        Args:
            trades: List of BacktestTrade objects
            equity_curve: Equity curve series
            initial_balance: Starting balance
        """
        self.trades = trades
        self.equity_curve = equity_curve
        self.initial_balance = initial_balance
    
    def calculate_all(self) -> Dict[str, Any]:
        """Calculate all performance metrics."""
        if not self.trades:
            return self._empty_metrics()
        
        returns = self.equity_curve.pct_change().dropna()
        
        return {
            # Basic metrics
            'total_trades': len(self.trades),
            'total_pnl': self._total_pnl(),
            'total_pnl_percent': self._total_pnl_percent(),
            'final_balance': self.equity_curve.iloc[-1] if len(self.equity_curve) > 0 else self.initial_balance,
            
            # Win/Loss metrics
            'winning_trades': self._winning_trades(),
            'losing_trades': self._losing_trades(),
            'win_rate': self._win_rate(),
            'loss_rate': 1 - self._win_rate(),
            
            # PnL metrics
            'gross_profit': self._gross_profit(),
            'gross_loss': self._gross_loss(),
            'profit_factor': self._profit_factor(),
            'average_trade': self._average_trade(),
            'average_win': self._average_win(),
            'average_loss': self._average_loss(),
            'largest_win': self._largest_win(),
            'largest_loss': self._largest_loss(),
            
            # Risk metrics
            'max_drawdown': self._max_drawdown(),
            'max_drawdown_percent': self._max_drawdown_percent(),
            'sharpe_ratio': self._sharpe_ratio(returns),
            'sortino_ratio': self._sortino_ratio(returns),
            'calmar_ratio': self._calmar_ratio(),
            
            # Trade statistics
            'avg_trade_duration': self._avg_trade_duration(),
            'total_fees': self._total_fees(),
            'expectancy': self._expectancy(),
            
            # Streak metrics
            'max_consecutive_wins': self._max_consecutive_wins(),
            'max_consecutive_losses': self._max_consecutive_losses(),
        }
    
    def _empty_metrics(self) -> Dict[str, Any]:
        """Return empty metrics when no trades."""
        return {
            'total_trades': 0,
            'total_pnl': 0,
            'total_pnl_percent': 0,
            'final_balance': self.initial_balance,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0,
            'loss_rate': 0,
            'gross_profit': 0,
            'gross_loss': 0,
            'profit_factor': 0,
            'average_trade': 0,
            'average_win': 0,
            'average_loss': 0,
            'largest_win': 0,
            'largest_loss': 0,
            'max_drawdown': 0,
            'max_drawdown_percent': 0,
            'sharpe_ratio': 0,
            'sortino_ratio': 0,
            'calmar_ratio': 0,
            'avg_trade_duration': 0,
            'total_fees': 0,
            'expectancy': 0,
            'max_consecutive_wins': 0,
            'max_consecutive_losses': 0,
        }
    
    def _total_pnl(self) -> float:
        """Calculate total profit/loss."""
        return sum(t.pnl for t in self.trades)
    
    def _total_pnl_percent(self) -> float:
        """Calculate total PnL as percentage."""
        return (self._total_pnl() / self.initial_balance) * 100
    
    def _winning_trades(self) -> int:
        """Count winning trades."""
        return len([t for t in self.trades if t.pnl > 0])
    
    def _losing_trades(self) -> int:
        """Count losing trades."""
        return len([t for t in self.trades if t.pnl <= 0])
    
    def _win_rate(self) -> float:
        """Calculate win rate."""
        if not self.trades:
            return 0.0
        return self._winning_trades() / len(self.trades)
    
    def _gross_profit(self) -> float:
        """Calculate gross profit."""
        return sum(t.pnl for t in self.trades if t.pnl > 0)
    
    def _gross_loss(self) -> float:
        """Calculate gross loss (absolute value)."""
        return abs(sum(t.pnl for t in self.trades if t.pnl < 0))
    
    def _profit_factor(self) -> float:
        """Calculate profit factor (gross profit / gross loss)."""
        gross_loss = self._gross_loss()
        if gross_loss == 0:
            return float('inf') if self._gross_profit() > 0 else 0
        return self._gross_profit() / gross_loss
    
    def _average_trade(self) -> float:
        """Calculate average trade PnL."""
        if not self.trades:
            return 0.0
        return self._total_pnl() / len(self.trades)
    
    def _average_win(self) -> float:
        """Calculate average winning trade."""
        winning = [t.pnl for t in self.trades if t.pnl > 0]
        return np.mean(winning) if winning else 0.0
    
    def _average_loss(self) -> float:
        """Calculate average losing trade."""
        losing = [t.pnl for t in self.trades if t.pnl < 0]
        return np.mean(losing) if losing else 0.0
    
    def _largest_win(self) -> float:
        """Find largest winning trade."""
        winning = [t.pnl for t in self.trades if t.pnl > 0]
        return max(winning) if winning else 0.0
    
    def _largest_loss(self) -> float:
        """Find largest losing trade."""
        losing = [t.pnl for t in self.trades if t.pnl < 0]
        return min(losing) if losing else 0.0
    
    def _max_drawdown(self) -> float:
        """Calculate maximum drawdown in absolute terms."""
        if len(self.equity_curve) == 0:
            return 0.0
        
        peak = self.equity_curve.expanding().max()
        drawdown = self.equity_curve - peak
        return abs(drawdown.min())
    
    def _max_drawdown_percent(self) -> float:
        """Calculate maximum drawdown as percentage."""
        if len(self.equity_curve) == 0:
            return 0.0
        
        peak = self.equity_curve.expanding().max()
        drawdown = (self.equity_curve - peak) / peak
        return abs(drawdown.min()) * 100
    
    def _sharpe_ratio(self, returns: pd.Series, risk_free_rate: float = 0.0) -> float:
        """
        Calculate Sharpe ratio.
        
        Assumes daily returns, annualizes to 365 days (crypto markets).
        """
        if len(returns) == 0 or returns.std() == 0:
            return 0.0
        
        excess_returns = returns - (risk_free_rate / 365)
        return (excess_returns.mean() / returns.std()) * np.sqrt(365)
    
    def _sortino_ratio(self, returns: pd.Series, risk_free_rate: float = 0.0) -> float:
        """
        Calculate Sortino ratio.
        
        Uses downside deviation instead of standard deviation.
        """
        if len(returns) == 0:
            return 0.0
        
        excess_returns = returns - (risk_free_rate / 365)
        downside_returns = returns[returns < 0]
        
        if len(downside_returns) == 0 or downside_returns.std() == 0:
            return float('inf') if excess_returns.mean() > 0 else 0.0
        
        downside_std = downside_returns.std()
        return (excess_returns.mean() / downside_std) * np.sqrt(365)
    
    def _calmar_ratio(self) -> float:
        """Calculate Calmar ratio (annual return / max drawdown)."""
        max_dd = self._max_drawdown_percent()
        if max_dd == 0:
            return 0.0
        
        # Approximate annual return
        total_return = self._total_pnl_percent()
        return total_return / max_dd
    
    def _avg_trade_duration(self) -> float:
        """Calculate average trade duration in hours."""
        durations = []
        for trade in self.trades:
            if trade.exit_time:
                duration = (trade.exit_time - trade.entry_time).total_seconds() / 3600
                durations.append(duration)
        
        return np.mean(durations) if durations else 0.0
    
    def _total_fees(self) -> float:
        """Calculate total fees paid."""
        return sum(t.fees for t in self.trades)
    
    def _expectancy(self) -> float:
        """
        Calculate trade expectancy.
        
        Expectancy = (Win Rate × Avg Win) - (Loss Rate × Avg Loss)
        """
        win_rate = self._win_rate()
        avg_win = self._average_win()
        avg_loss = abs(self._average_loss())
        
        return (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    
    def _max_consecutive_wins(self) -> int:
        """Calculate maximum consecutive winning trades."""
        if not self.trades:
            return 0
        
        max_streak = 0
        current_streak = 0
        
        for trade in self.trades:
            if trade.pnl > 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        
        return max_streak
    
    def _max_consecutive_losses(self) -> int:
        """Calculate maximum consecutive losing trades."""
        if not self.trades:
            return 0
        
        max_streak = 0
        current_streak = 0
        
        for trade in self.trades:
            if trade.pnl <= 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        
        return max_streak
    
    def generate_report(self) -> str:
        """Generate a text-based performance report."""
        metrics = self.calculate_all()
        
        report = """
═══════════════════════════════════════════════════════════
                    BACKTEST PERFORMANCE REPORT
═══════════════════════════════════════════════════════════

SUMMARY
───────────────────────────────────────────────────────────
Total Trades:           {total_trades}
Total PnL:              ${total_pnl:,.2f} ({total_pnl_percent:.2f}%)
Final Balance:          ${final_balance:,.2f}

WIN/LOSS ANALYSIS
───────────────────────────────────────────────────────────
Winning Trades:         {winning_trades} ({win_rate:.1%})
Losing Trades:          {losing_trades} ({loss_rate:.1%})
Profit Factor:          {profit_factor:.2f}

TRADE STATISTICS
───────────────────────────────────────────────────────────
Average Trade:          ${average_trade:,.2f}
Average Win:            ${average_win:,.2f}
Average Loss:           ${average_loss:,.2f}
Largest Win:            ${largest_win:,.2f}
Largest Loss:           ${largest_loss:,.2f}
Expectancy:             ${expectancy:,.2f}

RISK METRICS
───────────────────────────────────────────────────────────
Max Drawdown:           ${max_drawdown:,.2f} ({max_drawdown_percent:.2f}%)
Sharpe Ratio:           {sharpe_ratio:.2f}
Sortino Ratio:          {sortino_ratio:.2f}
Calmar Ratio:           {calmar_ratio:.2f}

ADDITIONAL STATS
───────────────────────────────────────────────────────────
Avg Trade Duration:     {avg_trade_duration:.1f} hours
Total Fees:             ${total_fees:,.2f}
Max Consecutive Wins:   {max_consecutive_wins}
Max Consecutive Losses: {max_consecutive_losses}

═══════════════════════════════════════════════════════════
""".format(**metrics)
        
        return report
