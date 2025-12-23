"""
Trade execution engine.
"""
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from loguru import logger

from config.settings import settings
from config.constants import SignalType, OrderSide, OrderType
from data.models import Signal, Position
from risk.manager import RiskManager
from .order_manager import OrderManager, OrderRequest, OrderResult


class TradeExecutor:
    def __init__(self, exchange, risk_manager: RiskManager):
        self.exchange = exchange
        self.risk_manager = risk_manager
        self.order_manager = OrderManager(exchange)
        self._positions: Dict[str, Position] = {}
        self._monitoring_tasks: Dict[str, asyncio.Task] = {}
        self._prediction_ids: Dict[str, str] = {}
        self._learning_db = None
        self._on_trade_closed: Optional[Callable] = None

    def set_learning_db(self, db) -> None:
        self._learning_db = db

    def set_trade_closed_callback(self, callback: Callable) -> None:
        self._on_trade_closed = callback

    async def execute_signal(self, signal: Signal) -> Optional[OrderResult]:
        if signal.signal_type == SignalType.HOLD.value:
            logger.debug(f"HOLD signal for {signal.symbol}, no action")
            return None
        
        valid, reason = self.risk_manager.validate_signal(signal)
        if not valid:
            logger.warning(f"Signal rejected by risk manager: {reason}")
            return None
        
        if signal.symbol in self._positions:
            position = self._positions[signal.symbol]
            
            if ((signal.signal_type == SignalType.BUY.value and position.side == 'short') or
                (signal.signal_type == SignalType.SELL.value and position.side == 'long')):
                await self.close_position(signal.symbol, "Signal reversal")
            else:
                logger.debug(f"Already have {position.side} position for {signal.symbol}")
                return None
        
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
            
            await self._save_prediction(signal, entry_price)
            
            self._start_position_monitor(signal.symbol)
            
            logger.info(
                f"Opened {position.side} position for {signal.symbol}: "
                f"size={position.amount}, entry={position.entry_price}"
            )
        
        return result

    async def _save_prediction(self, signal: Signal, entry_price: float) -> None:
        if not self._learning_db:
            return
        try:
            deployed = await self._learning_db.get_deployed_model(signal.symbol)
            model_id = deployed["id"] if deployed else "unknown"
            
            pred_id = await self._learning_db.save_prediction(
                symbol=signal.symbol,
                model_version_id=model_id,
                predicted_signal=signal.signal_type,
                confidence=signal.confidence,
                entry_price=entry_price
            )
            self._prediction_ids[signal.symbol] = pred_id
        except Exception as e:
            logger.error(f"Failed to save prediction: {e}")
    
    async def close_position(
        self,
        symbol: str,
        reason: str = "Manual close"
    ) -> Optional[OrderResult]:
        if symbol not in self._positions:
            logger.warning(f"No open position for {symbol}")
            return None
        
        position = self._positions[symbol]
        
        self._stop_position_monitor(symbol)
        
        side = OrderSide.SELL if position.side == 'long' else OrderSide.BUY
        
        order_request = OrderRequest(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            amount=position.amount
        )
        
        result = await self.order_manager.create_order(order_request)
        
        if result.success:
            exit_price = result.average_price or position.current_price
            
            if position.side == 'long':
                realized_pnl = (exit_price - position.entry_price) * position.amount
            else:
                realized_pnl = (position.entry_price - exit_price) * position.amount
            
            realized_pnl -= result.fee
            
            self.risk_manager.close_position(symbol, realized_pnl)
            
            await self._update_prediction_outcome(symbol, exit_price, realized_pnl)
            
            del self._positions[symbol]
            
            logger.info(
                f"Closed {position.side} position for {symbol}: "
                f"exit={exit_price}, PnL={realized_pnl:.2f} ({reason})"
            )
            
            if self._on_trade_closed:
                try:
                    await self._on_trade_closed(symbol, realized_pnl, reason)
                except Exception as e:
                    logger.error(f"Trade closed callback error: {e}")
        
        return result

    async def _update_prediction_outcome(self, symbol: str, exit_price: float, pnl: float) -> None:
        if not self._learning_db or symbol not in self._prediction_ids:
            return
        try:
            actual_outcome = 1 if pnl > 0 else -1 if pnl < 0 else 0
            await self._learning_db.update_prediction_outcome(
                prediction_id=self._prediction_ids[symbol],
                actual_outcome=actual_outcome,
                exit_price=exit_price,
                pnl=pnl
            )
            del self._prediction_ids[symbol]
        except Exception as e:
            logger.error(f"Failed to update prediction outcome: {e}")
        
        return result
    
    async def close_all_positions(self, reason: str = "Close all") -> int:
        closed = 0
        symbols = list(self._positions.keys())
        
        for symbol in symbols:
            result = await self.close_position(symbol, reason)
            if result and result.success:
                closed += 1
        
        return closed
    
    async def update_position_price(self, symbol: str, current_price: float) -> None:
        if symbol not in self._positions:
            return
        
        position = self._positions[symbol]
        position.current_price = current_price
        
        if position.side == 'long':
            position.unrealized_pnl = (current_price - position.entry_price) * position.amount
        else:
            position.unrealized_pnl = (position.entry_price - current_price) * position.amount
    
    def _start_position_monitor(self, symbol: str) -> None:
        if symbol in self._monitoring_tasks:
            return
        
        task = asyncio.create_task(self._monitor_position(symbol))
        self._monitoring_tasks[symbol] = task
    
    def _stop_position_monitor(self, symbol: str) -> None:
        if symbol in self._monitoring_tasks:
            self._monitoring_tasks[symbol].cancel()
            del self._monitoring_tasks[symbol]
    
    async def _monitor_position(self, symbol: str) -> None:
        while symbol in self._positions:
            try:
                position = self._positions[symbol]
                current_price = await self._get_current_price(symbol)
                
                await self.update_position_price(symbol, current_price)
                
                if self.risk_manager.check_stop_loss(position, current_price):
                    logger.warning(f"Stop-loss triggered for {symbol} @ {current_price}")
                    await self.close_position(symbol, "Stop-loss triggered")
                    break
                
                if self.risk_manager.check_take_profit(position, current_price):
                    logger.info(f"Take-profit triggered for {symbol} @ {current_price}")
                    await self.close_position(symbol, "Take-profit triggered")
                    break
                
                await asyncio.sleep(5)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error monitoring position {symbol}: {e}")
                await asyncio.sleep(10)
    
    async def _get_current_price(self, symbol: str) -> float:
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            raise
    
    def get_position(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Position]:
        return self._positions.copy()
    
    async def emergency_close_all(self) -> None:
        logger.critical("EMERGENCY: Closing all positions")
        
        await self.order_manager.cancel_all_orders()
        
        await self.close_all_positions("Emergency shutdown")
