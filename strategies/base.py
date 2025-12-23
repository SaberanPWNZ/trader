"""
Base strategy interface for PyBroker.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import pandas as pd
from datetime import datetime
from pybroker import Strategy

from config.constants import SignalType
from data.models import Signal


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies with PyBroker.
    
    Subclasses implement strategy logic using PyBroker decorators
    like @strategy.entry and @strategy.exit.
    """
    
    def __init__(self, name: str):
        """
        Initialize strategy.
        
        Args:
            name: Strategy identifier
        """
        self.name = name
        self._strategy: Optional[Strategy] = None
        self._last_signal: Optional[Signal] = None
        self._signal_history: list = []
    
    @abstractmethod
    def build_strategy(self, 
                      data_source=None,
                      start_date: str = None,
                      end_date: str = None,
                      symbol: str = None) -> Strategy:
        """
        Build PyBroker strategy with entry/exit rules.
        
        Args:
            data_source: PyBroker data source (e.g., YFinance)
            start_date: Start date for backtest (YYYY-MM-DD)
            end_date: End date for backtest (YYYY-MM-DD)
            symbol: Trading symbol (e.g., 'BTC-USD')
        
        Returns:
            PyBroker Strategy instance
        """
        pass
    
    def create_signal(
        self,
        symbol: str,
        signal_type: SignalType,
        confidence: float,
        entry_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Signal:
        """
        Create a trading signal.
        
        Args:
            symbol: Trading pair
            signal_type: BUY, SELL, or HOLD
            confidence: Signal confidence (0-1)
            entry_price: Suggested entry price
            stop_loss: Suggested stop loss price
            take_profit: Suggested take profit price
            metadata: Additional signal information
            
        Returns:
            Signal object
        """
        signal = Signal(
            symbol=symbol,
            signal_type=signal_type.value,
            confidence=confidence,
            timestamp=datetime.utcnow(),
            strategy=self.name,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata=metadata
        )
        
        self._last_signal = signal
        self._signal_history.append(signal)
        
        return signal
    
    @property
    def last_signal(self) -> Optional[Signal]:
        """Get the most recent signal."""
        return self._last_signal
    
    def get_signal_history(self, limit: int = 100) -> list:
        """Get recent signal history."""
        return self._signal_history[-limit:]
    
    def reset(self) -> None:
        """Reset strategy state."""
        self._last_signal = None
        self._signal_history.clear()
