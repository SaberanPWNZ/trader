"""
Trade execution engine.
"""
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from loguru import logger

from config.settings import settings
from config.constants import SignalType, OrderSide, OrderType
from data.models import Signal, Position
from risk.manager import RiskManager
from .order_manager import OrderManager, OrderRequest, OrderResult


class TradeExecutor:
    """
    Trade execution engine.
    
    Handles the complete trade lifecycle:
    - Signal processing
    - Risk validation
    - Order creation
    - Position management
    - Stop-loss / Take-profit monitoring
    """
    
    def __init__(self, exchange, risk_manager: RiskManager):
        """
        Initialize trade executor.
        
        Args:
            exchange: ccxt exchange instance
            risk_manager: Risk management instance
        """
        self.exchange = exchange
        self.risk_manager = risk_manager
        self.order_manager = OrderManager(exchange)
        self._positions: Dict[str, Position] = {}
        self._monitoring_tasks: Dict[str, asyncio.Task] = {}
    
    async def execute_signal(self, signal: Signal) -> Optional[OrderResult]:
        """
        Execute a trading signal.
        
        Args:
            signal: Trading signal
            
        Returns:
            Order result if executed, None otherwise
        """
        # Skip HOLD signals
        if signal.signal_type == SignalType.HOLD.value:
            logger.debug(f"HOLD signal for {signal.symbol}, no action")
            return None
        
        # Validate against risk rules
        valid, reason = self.risk_manager.validate_signal(signal)
        if not valid:
            logger.warning(f"Signal rejected by risk manager: {reason}")
            return None
        
        # Check for existing position
        if signal.symbol in self._positions:
            position = self._positions[signal.symbol]
            
            # Check if signal is opposite to current position
            if ((signal.signal_type == SignalType.BUY.value and position.side == 'short') or
                (signal.signal_type == SignalType.SELL.value and position.side == 'long')):
                # Close existing position first
                await self.close_position(signal.symbol, "Signal reversal")
            else:
                logger.debug(f"Already have {position.side} position for {signal.symbol}")
                return None
        
        # Calculate position size
        entry_price = signal.entry_price or await self._get_current_price(signal.symbol)
        stop_loss = signal.stop_loss
        
        if not stop_loss:
            logger.warning(f"Signal missing stop-loss for {signal.symbol}")
            return None
        
        position_size = self.risk_manager.calculate_position_size(
            entry_price, stop_loss, signal.symbol
        )
        
        if position_size <= 0:
            logger.warning(f"Calculated position size is zero for {signal.symbol}")
            return None
        
        # Create order
        side = OrderSide.BUY if signal.signal_type == SignalType.BUY.value else OrderSide.SELL
        
        order_request = OrderRequest(
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            amount=position_size,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit
        )
        
        result = await self.order_manager.create_order(order_request)
        
        if result.success:
            # Create position tracking
            position = Position(
                id=result.order_id,
                symbol=signal.symbol,
                side='long' if side == OrderSide.BUY else 'short',
                entry_price=result.average_price or entry_price,
                current_price=result.average_price or entry_price,
                amount=result.filled,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                opened_at=datetime.utcnow()
            )
            
            self._positions[signal.symbol] = position
            self.risk_manager.register_trade(position)
            
            # Start monitoring for SL/TP
            self._start_position_monitor(signal.symbol)
            
            logger.info(
                f"Opened {position.side} position for {signal.symbol}: "
                f"size={position.amount}, entry={position.entry_price}"
            )
        
        return result
    
    async def close_position(
        self,
        symbol: str,
        reason: str = "Manual close"
    ) -> Optional[OrderResult]:
        """
        Close an open position.
        
        Args:
            symbol: Trading pair
            reason: Reason for closing
            
        Returns:
            Order result if closed, None otherwise
        """
        if symbol not in self._positions:
            logger.warning(f"No open position for {symbol}")
            return None
        
        position = self._positions[symbol]
        
        # Stop monitoring
        self._stop_position_monitor(symbol)
        
        # Create closing order (opposite side)
        side = OrderSide.SELL if position.side == 'long' else OrderSide.BUY
        
        order_request = OrderRequest(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            amount=position.amount
        )
        
        result = await self.order_manager.create_order(order_request)
        
        if result.success:
            # Calculate realized PnL
            exit_price = result.average_price or position.current_price
            
            if position.side == 'long':
                realized_pnl = (exit_price - position.entry_price) * position.amount
            else:
                realized_pnl = (position.entry_price - exit_price) * position.amount
            
            # Account for fees
            realized_pnl -= result.fee
            
            # Update risk manager
            self.risk_manager.close_position(symbol, realized_pnl)
            
            # Remove position
            del self._positions[symbol]
            
            logger.info(
                f"Closed {position.side} position for {symbol}: "
                f"exit={exit_price}, PnL={realized_pnl:.2f} ({reason})"
            )
        
        return result
    
    async def close_all_positions(self, reason: str = "Close all") -> int:
        """
        Close all open positions.
        
        Args:
            reason: Reason for closing
            
        Returns:
            Number of positions closed
        """
        closed = 0
        symbols = list(self._positions.keys())
        
        for symbol in symbols:
            result = await self.close_position(symbol, reason)
            if result and result.success:
                closed += 1
        
        return closed
    
    async def update_position_price(self, symbol: str, current_price: float) -> None:
        """Update position's current price and unrealized PnL."""
        if symbol not in self._positions:
            return
        
        position = self._positions[symbol]
        position.current_price = current_price
        
        # Calculate unrealized PnL
        if position.side == 'long':
            position.unrealized_pnl = (current_price - position.entry_price) * position.amount
        else:
            position.unrealized_pnl = (position.entry_price - current_price) * position.amount
    
    def _start_position_monitor(self, symbol: str) -> None:
        """Start monitoring position for SL/TP."""
        if symbol in self._monitoring_tasks:
            return
        
        task = asyncio.create_task(self._monitor_position(symbol))
        self._monitoring_tasks[symbol] = task
    
    def _stop_position_monitor(self, symbol: str) -> None:
        """Stop monitoring position."""
        if symbol in self._monitoring_tasks:
            self._monitoring_tasks[symbol].cancel()
            del self._monitoring_tasks[symbol]
    
    async def _monitor_position(self, symbol: str) -> None:
        """Monitor position for stop-loss and take-profit."""
        while symbol in self._positions:
            try:
                position = self._positions[symbol]
                current_price = await self._get_current_price(symbol)
                
                await self.update_position_price(symbol, current_price)
                
                # Check stop-loss
                if self.risk_manager.check_stop_loss(position, current_price):
                    logger.warning(f"Stop-loss triggered for {symbol} @ {current_price}")
                    await self.close_position(symbol, "Stop-loss triggered")
                    break
                
                # Check take-profit
                if self.risk_manager.check_take_profit(position, current_price):
                    logger.info(f"Take-profit triggered for {symbol} @ {current_price}")
                    await self.close_position(symbol, "Take-profit triggered")
                    break
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring position {symbol}: {e}")
                await asyncio.sleep(10)
    
    async def _get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            raise
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a symbol."""
        return self._positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Position]:
        """Get all open positions."""
        return self._positions.copy()
    
    async def emergency_close_all(self) -> None:
        """Emergency close all positions (for kill switch)."""
        logger.critical("EMERGENCY: Closing all positions")
        
        # Cancel all open orders first
        await self.order_manager.cancel_all_orders()
        
        # Close all positions
        await self.close_all_positions("Emergency shutdown")
