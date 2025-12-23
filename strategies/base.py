"""
Base strategy interface for PyBroker.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, TYPE_CHECKING
import pandas as pd
from datetime import datetime

if TYPE_CHECKING:
    from pybroker import Strategy

from config.constants import SignalType
from data.models import Signal


class BaseStrategy(ABC):
    def __init__(self, name: str):
        self.name = name
        self._strategy = None
        self._last_signal: Optional[Signal] = None
        self._signal_history: list = []
    
    @abstractmethod
    def build_strategy(self, 
                      data_source=None,
                      start_date: str = None,
                      end_date: str = None,
                      symbol: str = None):
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
        return self._last_signal
    
    def get_signal_history(self, limit: int = 100) -> list:
        return self._signal_history[-limit:]
    
    def reset(self) -> None:
        self._last_signal = None
        self._signal_history.clear()
