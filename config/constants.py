"""
Application constants and enumerations.
"""
from enum import Enum, auto


class TradingMode(Enum):
    """Trading operation modes."""
    BACKTEST = auto()
    PAPER = auto()
    LIVE = auto()


class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class SignalType(Enum):
    """Trading signal types."""
    BUY = 1
    SELL = -1
    HOLD = 0


class OrderStatus(Enum):
    """Order status enumeration."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PositionStatus(Enum):
    """Position status enumeration."""
    OPEN = "open"
    CLOSED = "closed"


class RiskEventType(Enum):
    """Risk event types."""
    MAX_LOSS_REACHED = "max_loss_reached"
    MAX_DRAWDOWN_REACHED = "max_drawdown_reached"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    KILL_SWITCH_TRIGGERED = "kill_switch_triggered"
    COOLDOWN_ACTIVE = "cooldown_active"


# Trading constants
MIN_ORDER_SIZE_USDT = 10.0
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# Feature columns for ML model
FEATURE_COLUMNS = [
    'ema_ratio_fast_medium',
    'ema_ratio_fast_slow',
    'ema_ratio_medium_slow',
    'rsi',
    'macd_histogram',
    'log_return',
    'volume_delta',
    'atr_normalized',
]
