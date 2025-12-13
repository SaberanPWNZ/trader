"""
Data models for trading data.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from enum import Enum


@dataclass
class OHLCV:
    """OHLCV candle data model."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str
    timeframe: str


@dataclass
class Trade:
    """Trade data model."""
    id: str
    timestamp: datetime
    symbol: str
    side: str  # 'buy' or 'sell'
    price: float
    amount: float
    cost: float
    fee: Optional[float] = None
    fee_currency: Optional[str] = None


@dataclass
class OrderBookLevel:
    """Single order book level."""
    price: float
    amount: float


@dataclass
class OrderBook:
    """Order book data model."""
    symbol: str
    timestamp: datetime
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    
    @property
    def best_bid(self) -> Optional[float]:
        """Get best bid price."""
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        """Get best ask price."""
        return self.asks[0].price if self.asks else None
    
    @property
    def spread(self) -> Optional[float]:
        """Calculate bid-ask spread."""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None
    
    @property
    def spread_percentage(self) -> Optional[float]:
        """Calculate spread as percentage."""
        if self.spread and self.best_bid:
            return (self.spread / self.best_bid) * 100
        return None


@dataclass
class Balance:
    """Account balance model."""
    currency: str
    free: float
    used: float
    total: float


@dataclass
class Position:
    """Trading position model."""
    id: str
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: float
    current_price: float
    amount: float
    unrealized_pnl: float
    realized_pnl: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    @property
    def pnl_percentage(self) -> float:
        """Calculate PnL percentage."""
        if self.side == 'long':
            return ((self.current_price - self.entry_price) / self.entry_price) * 100
        else:
            return ((self.entry_price - self.current_price) / self.entry_price) * 100


@dataclass
class Order:
    """Order data model."""
    id: str
    symbol: str
    type: str  # 'market', 'limit'
    side: str  # 'buy', 'sell'
    price: Optional[float]
    amount: float
    filled: float
    remaining: float
    status: str  # 'open', 'closed', 'canceled'
    timestamp: datetime
    
    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.status == 'closed' and self.remaining == 0


@dataclass
class Signal:
    """Trading signal model."""
    symbol: str
    signal_type: int  # 1 = BUY, -1 = SELL, 0 = HOLD
    confidence: float
    timestamp: datetime
    strategy: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    metadata: Optional[dict] = None
