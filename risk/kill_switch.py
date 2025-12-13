"""
Kill switch implementation for emergency stop.
"""
import asyncio
from datetime import datetime
from typing import Optional, Callable, Awaitable, List
from loguru import logger

from config.settings import settings


class KillSwitch:
    """
    Emergency kill switch for the trading system.
    
    Monitors for critical conditions and can shut down
    trading operations immediately when triggered.
    
    Trigger conditions:
    - Manual activation
    - Max drawdown exceeded
    - Daily loss limit exceeded
    - API connection failures
    - Unusual market conditions
    """
    
    def __init__(self):
        self.config = settings.risk
        self.is_active = False
        self.activation_time: Optional[datetime] = None
        self.activation_reason: Optional[str] = None
        self._callbacks: List[Callable[[], Awaitable[None]]] = []
    
    def activate(self, reason: str) -> None:
        """
        Activate the kill switch.
        
        Args:
            reason: Reason for activation
        """
        if self.is_active:
            logger.warning("Kill switch already active")
            return
        
        self.is_active = True
        self.activation_time = datetime.utcnow()
        self.activation_reason = reason
        
        logger.critical(f"🚨 KILL SWITCH ACTIVATED: {reason}")
        
        # Execute callbacks synchronously to ensure immediate effect
        for callback in self._callbacks:
            try:
                asyncio.create_task(callback())
            except Exception as e:
                logger.error(f"Kill switch callback error: {e}")
    
    def deactivate(self, confirmation: str) -> bool:
        """
        Deactivate the kill switch.
        
        Requires confirmation string to prevent accidental deactivation.
        
        Args:
            confirmation: Must be "CONFIRM_DEACTIVATE"
            
        Returns:
            True if deactivated, False otherwise
        """
        if confirmation != "CONFIRM_DEACTIVATE":
            logger.warning("Kill switch deactivation rejected: invalid confirmation")
            return False
        
        if not self.is_active:
            logger.info("Kill switch is not active")
            return True
        
        self.is_active = False
        logger.warning(f"Kill switch deactivated (was active for {self.active_duration})")
        
        self.activation_time = None
        self.activation_reason = None
        
        return True
    
    def register_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """
        Register a callback to be executed when kill switch activates.
        
        Args:
            callback: Async function to call on activation
        """
        self._callbacks.append(callback)
    
    def check_drawdown(self, current_drawdown: float) -> bool:
        """
        Check if drawdown exceeds limit.
        
        Args:
            current_drawdown: Current drawdown percentage (0-1)
            
        Returns:
            True if kill switch should trigger
        """
        if current_drawdown >= self.config.max_drawdown:
            self.activate(f"Max drawdown exceeded: {current_drawdown:.1%}")
            return True
        return False
    
    def check_daily_loss(self, daily_loss_pct: float) -> bool:
        """
        Check if daily loss exceeds limit.
        
        Args:
            daily_loss_pct: Daily loss as percentage (0-1)
            
        Returns:
            True if kill switch should trigger
        """
        if daily_loss_pct >= self.config.max_daily_loss:
            self.activate(f"Max daily loss exceeded: {daily_loss_pct:.1%}")
            return True
        return False
    
    def check_api_failures(self, consecutive_failures: int, threshold: int = 5) -> bool:
        """
        Check for excessive API failures.
        
        Args:
            consecutive_failures: Number of consecutive API failures
            threshold: Maximum allowed consecutive failures
            
        Returns:
            True if kill switch should trigger
        """
        if consecutive_failures >= threshold:
            self.activate(f"Excessive API failures: {consecutive_failures} consecutive")
            return True
        return False
    
    @property
    def active_duration(self) -> Optional[str]:
        """Get duration since activation."""
        if not self.activation_time:
            return None
        
        duration = datetime.utcnow() - self.activation_time
        hours, remainder = divmod(duration.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        return f"{hours}h {minutes}m {seconds}s"
    
    @property
    def status(self) -> dict:
        """Get kill switch status."""
        return {
            'is_active': self.is_active,
            'activation_time': self.activation_time.isoformat() if self.activation_time else None,
            'activation_reason': self.activation_reason,
            'active_duration': self.active_duration,
            'enabled': self.config.kill_switch_enabled
        }
