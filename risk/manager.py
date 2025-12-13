"""
Risk management system.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from loguru import logger

from config.settings import settings
from config.constants import RiskEventType
from data.models import Signal, Position


@dataclass
class RiskState:
    """Current risk state tracking."""
    daily_pnl: float = 0.0
    peak_balance: float = 0.0
    current_balance: float = 0.0
    consecutive_losses: int = 0
    last_trade_time: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    kill_switch_active: bool = False
    open_positions: Dict[str, Position] = field(default_factory=dict)
    
    @property
    def current_drawdown(self) -> float:
        """Calculate current drawdown percentage."""
        if self.peak_balance <= 0:
            return 0.0
        return (self.peak_balance - self.current_balance) / self.peak_balance


class RiskManager:
    """
    Risk management system.
    
    Implements:
    - Max risk per trade
    - Max daily loss
    - Max drawdown
    - Max position size
    - Stop-loss / Take-profit enforcement
    - Cooldown after consecutive losses
    - Kill-switch emergency stop
    """
    
    def __init__(self, initial_balance: float = 10000.0):
        self.config = settings.risk
        self.state = RiskState(
            peak_balance=initial_balance,
            current_balance=initial_balance
        )
        self._risk_events: List[Dict[str, Any]] = []
    
    def can_trade(self, symbol: str) -> tuple:
        """
        Check if trading is allowed.
        
        Args:
            symbol: Trading pair
            
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        # Check kill switch
        if self.state.kill_switch_active:
            return False, "Kill switch is active"
        
        # Check cooldown
        if self.state.cooldown_until:
            if datetime.utcnow() < self.state.cooldown_until:
                remaining = (self.state.cooldown_until - datetime.utcnow()).seconds
                return False, f"Cooldown active for {remaining} seconds"
            else:
                self.state.cooldown_until = None
        
        # Check daily loss limit
        daily_loss_pct = abs(self.state.daily_pnl) / self.state.peak_balance
        if self.state.daily_pnl < 0 and daily_loss_pct >= self.config.max_daily_loss:
            self._record_risk_event(RiskEventType.MAX_LOSS_REACHED, {
                'daily_loss': self.state.daily_pnl,
                'daily_loss_pct': daily_loss_pct
            })
            return False, f"Daily loss limit reached ({daily_loss_pct:.1%})"
        
        # Check max drawdown
        if self.state.current_drawdown >= self.config.max_drawdown:
            self._record_risk_event(RiskEventType.MAX_DRAWDOWN_REACHED, {
                'drawdown': self.state.current_drawdown
            })
            return False, f"Max drawdown reached ({self.state.current_drawdown:.1%})"
        
        # Check existing position
        if symbol in self.state.open_positions:
            return False, f"Position already open for {symbol}"
        
        return True, "OK"
    
    def validate_signal(self, signal: Signal) -> tuple:
        """
        Validate trading signal against risk rules.
        
        Args:
            signal: Trading signal to validate
            
        Returns:
            Tuple of (valid: bool, reason: str)
        """
        can_trade, reason = self.can_trade(signal.symbol)
        if not can_trade:
            return False, reason
        
        # Check minimum confidence
        if signal.confidence < self.config.min_confidence if hasattr(self.config, 'min_confidence') else 0.5:
            return False, f"Signal confidence too low ({signal.confidence:.2f})"
        
        # Validate stop-loss
        if signal.stop_loss is None:
            return False, "Signal missing stop-loss"
        
        return True, "OK"
    
    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        symbol: str
    ) -> float:
        """
        Calculate position size based on risk parameters.
        
        Uses fixed-risk position sizing:
        Position Size = (Account Risk) / (Trade Risk per Unit)
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            symbol: Trading pair
            
        Returns:
            Position size in base currency
        """
        # Calculate risk per unit
        risk_per_unit = abs(entry_price - stop_loss)
        
        if risk_per_unit == 0:
            logger.warning("Risk per unit is zero, cannot calculate position size")
            return 0.0
        
        # Calculate account risk
        account_risk = self.state.current_balance * self.config.max_risk_per_trade
        
        # Calculate position size
        position_size = account_risk / risk_per_unit
        
        # Apply max position size constraint
        max_position_value = self.state.current_balance * self.config.max_position_size
        max_position_size = max_position_value / entry_price
        
        position_size = min(position_size, max_position_size)
        
        logger.debug(f"Position size for {symbol}: {position_size:.6f} (risk={account_risk:.2f})")
        
        return position_size
    
    def register_trade(self, position: Position) -> None:
        """Register a new trade/position."""
        self.state.open_positions[position.symbol] = position
        self.state.last_trade_time = datetime.utcnow()
        logger.info(f"Registered position for {position.symbol}")
    
    def close_position(self, symbol: str, realized_pnl: float) -> None:
        """
        Close a position and update risk state.
        
        Args:
            symbol: Trading pair
            realized_pnl: Realized profit/loss
        """
        if symbol in self.state.open_positions:
            del self.state.open_positions[symbol]
        
        # Update PnL tracking
        self.state.daily_pnl += realized_pnl
        self.state.current_balance += realized_pnl
        
        # Update peak balance
        if self.state.current_balance > self.state.peak_balance:
            self.state.peak_balance = self.state.current_balance
        
        # Track consecutive losses
        if realized_pnl < 0:
            self.state.consecutive_losses += 1
            
            if self.state.consecutive_losses >= self.config.max_consecutive_losses:
                self._activate_cooldown()
        else:
            self.state.consecutive_losses = 0
        
        logger.info(f"Closed position for {symbol}: PnL={realized_pnl:.2f}")
    
    def check_stop_loss(self, position: Position, current_price: float) -> bool:
        """Check if stop-loss should trigger."""
        if position.stop_loss is None:
            return False
        
        if position.side == 'long':
            return current_price <= position.stop_loss
        else:
            return current_price >= position.stop_loss
    
    def check_take_profit(self, position: Position, current_price: float) -> bool:
        """Check if take-profit should trigger."""
        if position.take_profit is None:
            return False
        
        if position.side == 'long':
            return current_price >= position.take_profit
        else:
            return current_price <= position.take_profit
    
    def activate_kill_switch(self, reason: str) -> None:
        """Activate emergency kill switch."""
        self.state.kill_switch_active = True
        self._record_risk_event(RiskEventType.KILL_SWITCH_TRIGGERED, {
            'reason': reason
        })
        logger.critical(f"KILL SWITCH ACTIVATED: {reason}")
    
    def deactivate_kill_switch(self) -> None:
        """Deactivate kill switch (requires manual intervention)."""
        self.state.kill_switch_active = False
        logger.warning("Kill switch deactivated")
    
    def _activate_cooldown(self) -> None:
        """Activate trading cooldown."""
        self.state.cooldown_until = datetime.utcnow() + timedelta(
            minutes=self.config.cooldown_minutes
        )
        self._record_risk_event(RiskEventType.COOLDOWN_ACTIVE, {
            'consecutive_losses': self.state.consecutive_losses,
            'cooldown_until': self.state.cooldown_until.isoformat()
        })
        logger.warning(f"Cooldown activated until {self.state.cooldown_until}")
    
    def _record_risk_event(self, event_type: RiskEventType, data: dict) -> None:
        """Record a risk event."""
        event = {
            'type': event_type.value,
            'timestamp': datetime.utcnow().isoformat(),
            'data': data
        }
        self._risk_events.append(event)
        logger.warning(f"Risk event: {event_type.value} - {data}")
    
    def reset_daily_stats(self) -> None:
        """Reset daily statistics (call at start of new trading day)."""
        self.state.daily_pnl = 0.0
        logger.info("Daily risk stats reset")
    
    def get_risk_summary(self) -> dict:
        """Get current risk state summary."""
        return {
            'current_balance': self.state.current_balance,
            'peak_balance': self.state.peak_balance,
            'daily_pnl': self.state.daily_pnl,
            'current_drawdown': self.state.current_drawdown,
            'consecutive_losses': self.state.consecutive_losses,
            'open_positions': len(self.state.open_positions),
            'kill_switch_active': self.state.kill_switch_active,
            'cooldown_active': self.state.cooldown_until is not None
        }
