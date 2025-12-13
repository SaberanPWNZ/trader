"""
Backtesting engine for strategy evaluation.
"""
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from loguru import logger

from config.settings import settings
from config.constants import SignalType
from strategies.base import BaseStrategy
from .metrics import PerformanceMetrics


@dataclass
class BacktestTrade:
    """Single backtest trade record."""
    entry_time: datetime
    exit_time: Optional[datetime]
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    exit_price: Optional[float]
    amount: float
    pnl: float = 0.0
    pnl_percent: float = 0.0
    fees: float = 0.0
    exit_reason: str = ""


@dataclass
class BacktestResult:
    """Backtest results container."""
    trades: List[BacktestTrade]
    equity_curve: pd.Series
    metrics: Dict[str, Any]
    signals: pd.DataFrame
    parameters: Dict[str, Any]


class BacktestEngine:
    """
    Backtesting engine for strategy evaluation.
    
    Features:
    - Historical data simulation
    - Trading fees and slippage modeling
    - Performance metrics calculation
    - Walk-forward validation support
    """
    
    def __init__(
        self,
        strategy: BaseStrategy,
        initial_balance: float = None,
        fee_rate: float = None,
        slippage: float = None
    ):
        """
        Initialize backtest engine.
        
        Args:
            strategy: Trading strategy to test
            initial_balance: Starting balance
            fee_rate: Trading fee rate
            slippage: Slippage rate
        """
        self.strategy = strategy
        self.initial_balance = initial_balance or settings.backtest.initial_balance
        self.fee_rate = fee_rate or settings.backtest.trading_fee
        self.slippage = slippage or settings.backtest.slippage
        self.risk_config = settings.risk
        
        # State
        self._balance = self.initial_balance
        self._position = None
        self._trades: List[BacktestTrade] = []
        self._equity_history: List[float] = []
        self._signals_log: List[Dict] = []
    
    def run(self, data: pd.DataFrame) -> BacktestResult:
        """
        Run backtest on historical data.
        
        Args:
            data: DataFrame with OHLCV data
            
        Returns:
            Backtest results
        """
        logger.info(f"Starting backtest: {len(data)} candles, {self.initial_balance} initial balance")
        
        # Reset state
        self._reset()
        
        # Add indicators
        data = self.strategy.calculate_features(data)
        
        # Get symbol from data
        symbol = data['symbol'].iloc[0] if 'symbol' in data.columns else 'UNKNOWN'
        
        # Walk through data
        for i in range(len(data)):
            if i < 50:  # Skip initial period for indicator warmup
                self._equity_history.append(self._balance)
                continue
            
            current_bar = data.iloc[i]
            historical_data = data.iloc[:i+1]
            
            # Update position value if we have one
            if self._position:
                self._update_position(current_bar)
            
            # Generate signal
            signal = self.strategy.generate_signal(historical_data)
            
            # Log signal
            self._signals_log.append({
                'timestamp': current_bar.name,
                'signal': signal.signal_type,
                'confidence': signal.confidence,
                'price': current_bar['close']
            })
            
            # Process signal
            self._process_signal(signal, current_bar, symbol)
            
            # Record equity
            equity = self._calculate_equity(current_bar['close'])
            self._equity_history.append(equity)
        
        # Close any open position at end
        if self._position:
            self._close_position(data.iloc[-1], "End of backtest")
        
        # Calculate metrics
        metrics = self._calculate_metrics()
        
        result = BacktestResult(
            trades=self._trades,
            equity_curve=pd.Series(self._equity_history, index=data.index),
            metrics=metrics,
            signals=pd.DataFrame(self._signals_log),
            parameters={
                'strategy': self.strategy.name,
                'initial_balance': self.initial_balance,
                'fee_rate': self.fee_rate,
                'slippage': self.slippage
            }
        )
        
        logger.info(f"Backtest complete: {len(self._trades)} trades, Final PnL: {metrics['total_pnl']:.2f}")
        
        return result
    
    def _reset(self) -> None:
        """Reset backtest state."""
        self._balance = self.initial_balance
        self._position = None
        self._trades = []
        self._equity_history = []
        self._signals_log = []
    
    def _process_signal(self, signal, bar: pd.Series, symbol: str) -> None:
        """Process trading signal."""
        # Check if we should close existing position
        if self._position:
            # Check stop-loss
            if self._check_stop_loss(bar):
                self._close_position(bar, "Stop-loss")
                return
            
            # Check take-profit
            if self._check_take_profit(bar):
                self._close_position(bar, "Take-profit")
                return
            
            # Check for exit signal
            if ((signal.signal_type == SignalType.SELL.value and self._position['side'] == 'long') or
                (signal.signal_type == SignalType.BUY.value and self._position['side'] == 'short')):
                self._close_position(bar, "Signal reversal")
        
        # Check if we should open new position
        if not self._position and signal.signal_type != SignalType.HOLD.value:
            self._open_position(signal, bar, symbol)
    
    def _open_position(self, signal, bar: pd.Series, symbol: str) -> None:
        """Open new position."""
        entry_price = bar['close']
        
        # Apply slippage
        if signal.signal_type == SignalType.BUY.value:
            entry_price *= (1 + self.slippage)
        else:
            entry_price *= (1 - self.slippage)
        
        # Calculate position size
        risk_amount = self._balance * self.risk_config.max_risk_per_trade
        
        if signal.stop_loss:
            risk_per_unit = abs(entry_price - signal.stop_loss)
            if risk_per_unit > 0:
                amount = risk_amount / risk_per_unit
            else:
                amount = self._balance * 0.1 / entry_price
        else:
            amount = self._balance * 0.1 / entry_price
        
        # Apply max position size
        max_amount = (self._balance * self.risk_config.max_position_size) / entry_price
        amount = min(amount, max_amount)
        
        # Calculate fees
        fees = amount * entry_price * self.fee_rate
        
        self._position = {
            'entry_time': bar.name,
            'symbol': symbol,
            'side': 'long' if signal.signal_type == SignalType.BUY.value else 'short',
            'entry_price': entry_price,
            'amount': amount,
            'stop_loss': signal.stop_loss,
            'take_profit': signal.take_profit,
            'fees': fees
        }
        
        self._balance -= fees
    
    def _close_position(self, bar: pd.Series, reason: str) -> None:
        """Close current position."""
        if not self._position:
            return
        
        exit_price = bar['close']
        
        # Apply slippage
        if self._position['side'] == 'long':
            exit_price *= (1 - self.slippage)
        else:
            exit_price *= (1 + self.slippage)
        
        # Calculate PnL
        if self._position['side'] == 'long':
            pnl = (exit_price - self._position['entry_price']) * self._position['amount']
        else:
            pnl = (self._position['entry_price'] - exit_price) * self._position['amount']
        
        # Subtract exit fees
        exit_fees = self._position['amount'] * exit_price * self.fee_rate
        total_fees = self._position['fees'] + exit_fees
        pnl -= exit_fees
        
        # Calculate PnL percentage
        position_value = self._position['entry_price'] * self._position['amount']
        pnl_percent = (pnl / position_value) * 100 if position_value > 0 else 0
        
        # Record trade
        trade = BacktestTrade(
            entry_time=self._position['entry_time'],
            exit_time=bar.name,
            symbol=self._position['symbol'],
            side=self._position['side'],
            entry_price=self._position['entry_price'],
            exit_price=exit_price,
            amount=self._position['amount'],
            pnl=pnl,
            pnl_percent=pnl_percent,
            fees=total_fees,
            exit_reason=reason
        )
        self._trades.append(trade)
        
        # Update balance
        self._balance += pnl
        
        self._position = None
    
    def _update_position(self, bar: pd.Series) -> None:
        """Update position with current bar data."""
        # Position tracking for equity calculation
        pass
    
    def _check_stop_loss(self, bar: pd.Series) -> bool:
        """Check if stop-loss is hit."""
        if not self._position or not self._position.get('stop_loss'):
            return False
        
        if self._position['side'] == 'long':
            return bar['low'] <= self._position['stop_loss']
        else:
            return bar['high'] >= self._position['stop_loss']
    
    def _check_take_profit(self, bar: pd.Series) -> bool:
        """Check if take-profit is hit."""
        if not self._position or not self._position.get('take_profit'):
            return False
        
        if self._position['side'] == 'long':
            return bar['high'] >= self._position['take_profit']
        else:
            return bar['low'] <= self._position['take_profit']
    
    def _calculate_equity(self, current_price: float) -> float:
        """Calculate current equity."""
        equity = self._balance
        
        if self._position:
            if self._position['side'] == 'long':
                unrealized = (current_price - self._position['entry_price']) * self._position['amount']
            else:
                unrealized = (self._position['entry_price'] - current_price) * self._position['amount']
            equity += unrealized
        
        return equity
    
    def _calculate_metrics(self) -> Dict[str, Any]:
        """Calculate performance metrics."""
        calculator = PerformanceMetrics(
            self._trades,
            pd.Series(self._equity_history),
            self.initial_balance
        )
        return calculator.calculate_all()
    
    def walk_forward_validation(
        self,
        data: pd.DataFrame,
        train_period: int,
        test_period: int,
        step: int = None
    ) -> List[BacktestResult]:
        """
        Perform walk-forward validation.
        
        Args:
            data: Full historical data
            train_period: Training period in bars
            test_period: Testing period in bars
            step: Step size (defaults to test_period)
            
        Returns:
            List of backtest results for each fold
        """
        step = step or test_period
        results = []
        
        start = 0
        while start + train_period + test_period <= len(data):
            train_end = start + train_period
            test_end = train_end + test_period
            
            # Train data (for potential model training)
            train_data = data.iloc[start:train_end]
            
            # Test data
            test_data = data.iloc[train_end:test_end]
            
            # Run backtest on test data
            self._reset()
            result = self.run(test_data)
            result.parameters['fold_start'] = train_end
            result.parameters['fold_end'] = test_end
            results.append(result)
            
            start += step
        
        logger.info(f"Walk-forward validation: {len(results)} folds")
        return results
