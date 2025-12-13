"""
Metrics collection for monitoring and analysis.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import json
from pathlib import Path
from loguru import logger

from config.settings import settings


@dataclass
class TradeMetric:
    """Single trade metric record."""
    timestamp: datetime
    symbol: str
    side: str
    pnl: float
    pnl_percent: float
    entry_price: float
    exit_price: float
    duration_minutes: int


@dataclass
class PerformanceSnapshot:
    """Performance snapshot at a point in time."""
    timestamp: datetime
    balance: float
    equity: float
    daily_pnl: float
    drawdown: float
    open_positions: int
    total_trades: int


class MetricsCollector:
    """
    Collects and stores trading metrics for analysis.
    
    Tracks:
    - Trade-by-trade results
    - Equity curve
    - Drawdown
    - Win/loss streaks
    - Symbol performance
    """
    
    def __init__(self, data_dir: str = None):
        """
        Initialize metrics collector.
        
        Args:
            data_dir: Directory to store metrics files
        """
        self.data_dir = Path(data_dir or settings.data_dir) / "metrics"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory storage
        self._trades: List[TradeMetric] = []
        self._snapshots: List[PerformanceSnapshot] = []
        self._symbol_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'total_trades': 0,
            'winning_trades': 0,
            'total_pnl': 0.0,
            'best_trade': 0.0,
            'worst_trade': 0.0
        })
        
        # Streak tracking
        self._current_streak = 0
        self._max_win_streak = 0
        self._max_loss_streak = 0
    
    def record_trade(
        self,
        symbol: str,
        side: str,
        pnl: float,
        pnl_percent: float,
        entry_price: float,
        exit_price: float,
        entry_time: datetime,
        exit_time: datetime
    ) -> None:
        """Record a completed trade."""
        duration = int((exit_time - entry_time).total_seconds() / 60)
        
        trade = TradeMetric(
            timestamp=exit_time,
            symbol=symbol,
            side=side,
            pnl=pnl,
            pnl_percent=pnl_percent,
            entry_price=entry_price,
            exit_price=exit_price,
            duration_minutes=duration
        )
        
        self._trades.append(trade)
        
        # Update symbol stats
        stats = self._symbol_stats[symbol]
        stats['total_trades'] += 1
        stats['total_pnl'] += pnl
        
        if pnl > 0:
            stats['winning_trades'] += 1
            stats['best_trade'] = max(stats['best_trade'], pnl)
        else:
            stats['worst_trade'] = min(stats['worst_trade'], pnl)
        
        # Update streaks
        self._update_streaks(pnl > 0)
        
        logger.debug(f"Recorded trade metric: {symbol} PnL={pnl:.2f}")
    
    def record_snapshot(
        self,
        balance: float,
        equity: float,
        daily_pnl: float,
        drawdown: float,
        open_positions: int,
        total_trades: int
    ) -> None:
        """Record a performance snapshot."""
        snapshot = PerformanceSnapshot(
            timestamp=datetime.utcnow(),
            balance=balance,
            equity=equity,
            daily_pnl=daily_pnl,
            drawdown=drawdown,
            open_positions=open_positions,
            total_trades=total_trades
        )
        
        self._snapshots.append(snapshot)
    
    def _update_streaks(self, is_win: bool) -> None:
        """Update win/loss streak tracking."""
        if is_win:
            if self._current_streak > 0:
                self._current_streak += 1
            else:
                self._current_streak = 1
            self._max_win_streak = max(self._max_win_streak, self._current_streak)
        else:
            if self._current_streak < 0:
                self._current_streak -= 1
            else:
                self._current_streak = -1
            self._max_loss_streak = max(self._max_loss_streak, abs(self._current_streak))
    
    def get_summary(self, period: str = "all") -> Dict[str, Any]:
        """
        Get performance summary.
        
        Args:
            period: "all", "today", "week", "month"
            
        Returns:
            Summary dictionary
        """
        trades = self._filter_trades_by_period(period)
        
        if not trades:
            return self._empty_summary()
        
        total_pnl = sum(t.pnl for t in trades)
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl <= 0]
        
        return {
            'period': period,
            'total_trades': len(trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(trades) if trades else 0,
            'total_pnl': total_pnl,
            'average_pnl': total_pnl / len(trades) if trades else 0,
            'best_trade': max((t.pnl for t in trades), default=0),
            'worst_trade': min((t.pnl for t in trades), default=0),
            'average_duration_minutes': sum(t.duration_minutes for t in trades) / len(trades) if trades else 0,
            'max_win_streak': self._max_win_streak,
            'max_loss_streak': self._max_loss_streak,
            'current_streak': self._current_streak
        }
    
    def get_symbol_performance(self) -> Dict[str, Dict[str, Any]]:
        """Get performance breakdown by symbol."""
        result = {}
        
        for symbol, stats in self._symbol_stats.items():
            win_rate = stats['winning_trades'] / stats['total_trades'] if stats['total_trades'] > 0 else 0
            
            result[symbol] = {
                **stats,
                'win_rate': win_rate,
                'average_pnl': stats['total_pnl'] / stats['total_trades'] if stats['total_trades'] > 0 else 0
            }
        
        return result
    
    def get_equity_curve(self) -> List[Dict[str, Any]]:
        """Get equity curve data points."""
        return [
            {
                'timestamp': s.timestamp.isoformat(),
                'balance': s.balance,
                'equity': s.equity,
                'drawdown': s.drawdown
            }
            for s in self._snapshots
        ]
    
    def _filter_trades_by_period(self, period: str) -> List[TradeMetric]:
        """Filter trades by time period."""
        if period == "all":
            return self._trades
        
        now = datetime.utcnow()
        
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = now - timedelta(days=7)
        elif period == "month":
            start = now - timedelta(days=30)
        else:
            return self._trades
        
        return [t for t in self._trades if t.timestamp >= start]
    
    def _empty_summary(self) -> Dict[str, Any]:
        """Return empty summary."""
        return {
            'period': 'all',
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'average_pnl': 0,
            'best_trade': 0,
            'worst_trade': 0,
            'average_duration_minutes': 0,
            'max_win_streak': 0,
            'max_loss_streak': 0,
            'current_streak': 0
        }
    
    def save_to_file(self) -> None:
        """Save metrics to file."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        data = {
            'timestamp': timestamp,
            'summary': self.get_summary(),
            'symbol_performance': self.get_symbol_performance(),
            'equity_curve': self.get_equity_curve(),
            'trades': [
                {
                    'timestamp': t.timestamp.isoformat(),
                    'symbol': t.symbol,
                    'side': t.side,
                    'pnl': t.pnl,
                    'pnl_percent': t.pnl_percent,
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'duration_minutes': t.duration_minutes
                }
                for t in self._trades
            ]
        }
        
        filepath = self.data_dir / f"metrics_{timestamp}.json"
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Metrics saved to {filepath}")
    
    def load_from_file(self, filepath: str) -> None:
        """Load metrics from file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Restore trades
        self._trades = [
            TradeMetric(
                timestamp=datetime.fromisoformat(t['timestamp']),
                symbol=t['symbol'],
                side=t['side'],
                pnl=t['pnl'],
                pnl_percent=t['pnl_percent'],
                entry_price=t['entry_price'],
                exit_price=t['exit_price'],
                duration_minutes=t['duration_minutes']
            )
            for t in data.get('trades', [])
        ]
        
        logger.info(f"Loaded {len(self._trades)} trade records")
