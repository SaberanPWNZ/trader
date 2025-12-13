"""
Simplified execution layer for PyBroker.

PyBroker handles order execution, position management, and fills internally.
This module provides a thin wrapper for integration with our risk management
and monitoring systems.
"""
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass
from loguru import logger

from config.settings import settings
from risk.manager import RiskManager
from monitoring.alerts import TelegramAlert


@dataclass
class ExecutionState:
    """Execution state tracking."""
    active_positions: Dict[str, Dict[str, Any]]
    last_execution_time: Optional[datetime]
    total_executions: int = 0
    failed_executions: int = 0


class ExecutionManager:
    """
    Execution manager for PyBroker integration.
    
    PyBroker handles the actual order execution internally.
    This manager:
    - Monitors execution events
    - Applies risk checks before PyBroker execution
    - Tracks execution metrics
    - Logs trades for monitoring
    - Sends Telegram alerts for trade events
    """
    
    def __init__(self, risk_manager: Optional[RiskManager] = None):
        """
        Initialize execution manager.
        
        Args:
            risk_manager: Risk management instance (optional)
        """
        self.risk_manager = risk_manager or RiskManager(settings.backtest.initial_balance)
        self.alerts = TelegramAlert()
        self.state = ExecutionState(
            active_positions={},
            last_execution_time=None
        )
    
    def pre_trade_check(self, symbol: str) -> tuple:
        """
        Pre-execution risk checks before PyBroker places order.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        # Check risk manager constraints
        can_trade, reason = self.risk_manager.can_trade(symbol)
        
        if not can_trade:
            logger.warning(f"Pre-trade check failed for {symbol}: {reason}")
            return False, reason
        
        logger.debug(f"Pre-trade check passed for {symbol}")
        return True, "OK"
    
    async def on_trade_filled(
        self,
        symbol: str,
        side: str,
        shares: float,
        entry_price: float,
        exit_price: Optional[float] = None,
        pnl: Optional[float] = None,
        reason: str = "exit_signal"
    ) -> None:
        """
        Handle trade filled event from PyBroker.
        
        Args:
            symbol: Trading symbol
            side: 'long' or 'short'
            shares: Number of shares
            entry_price: Entry price
            exit_price: Exit price (if closed)
            pnl: Profit/loss amount
            reason: Reason for trade action
        """
        self.state.total_executions += 1
        self.state.last_execution_time = datetime.utcnow()
        
        if pnl is not None:
            # Trade closed
            self.risk_manager.close_position(symbol, pnl)
            logger.info(
                f"Trade closed: {symbol} {side} "
                f"{shares} @ {entry_price:.2f}/{exit_price:.2f} "
                f"PnL={pnl:.2f}"
            )
            
            # Send Telegram notification
            try:
                await self.alerts.trade_closed(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    reason=reason
                )
            except Exception as e:
                logger.warning(f"Failed to send trade closed alert: {e}")
        else:
            # Trade opened
            self.state.active_positions[symbol] = {
                'side': side,
                'shares': shares,
                'entry_price': entry_price,
                'opened_at': datetime.utcnow()
            }
            logger.info(
                f"Trade opened: {symbol} {side} "
                f"{shares} @ {entry_price:.2f}"
            )
            
            # Send Telegram notification
            try:
                await self.alerts.trade_opened(
                    symbol=symbol,
                    side=side,
                    amount=shares,
                    entry_price=entry_price
                )
            except Exception as e:
                logger.warning(f"Failed to send trade opened alert: {e}")
    
    async def on_execution_error(
        self,
        symbol: str,
        error: str
    ) -> None:
        """
        Handle execution error.
        
        Args:
            symbol: Trading symbol
            error: Error message
        """
        self.state.failed_executions += 1
        logger.error(f"Execution error for {symbol}: {error}")
        
        # Send alert for errors
        try:
            await self.alerts.risk_alert(
                event_type="Execution Error",
                details=f"{symbol}: {error}"
            )
        except Exception as e:
            logger.warning(f"Failed to send error alert: {e}")
    
    async def on_risk_breach(
        self,
        breach_type: str,
        details: str
    ) -> None:
        """
        Handle risk limit breach.
        
        Args:
            breach_type: Type of breach (e.g., 'max_drawdown', 'daily_loss')
            details: Breach details
        """
        logger.critical(f"Risk breach detected: {breach_type} - {details}")
        
        # Send alert
        try:
            await self.alerts.risk_alert(
                event_type=f"Risk Limit: {breach_type}",
                details=details
            )
        except Exception as e:
            logger.warning(f"Failed to send risk alert: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get execution status."""
        return {
            'active_positions': len(self.state.active_positions),
            'total_executions': self.state.total_executions,
            'failed_executions': self.state.failed_executions,
            'last_execution': self.state.last_execution_time,
            'success_rate': (
                (self.state.total_executions - self.state.failed_executions) / 
                self.state.total_executions
                if self.state.total_executions > 0 else 0
            )
        }
    
    def log_positions(self) -> None:
        """Log current positions."""
        if not self.state.active_positions:
            logger.info("No active positions")
            return
        
        for symbol, position in self.state.active_positions.items():
            logger.info(
                f"Position: {symbol} {position['side']} "
                f"{position['shares']} @ {position['entry_price']:.2f}"
            )
    
    async def close(self) -> None:
        """Close resources (e.g., Telegram session)."""
        await self.alerts.close()
