"""
Order management system.
"""
import asyncio
from datetime import datetime
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
import uuid
from loguru import logger

from config.settings import settings
from config.constants import OrderSide, OrderType, OrderStatus, MAX_RETRIES, RETRY_DELAY_SECONDS


@dataclass
class OrderRequest:
    """Order request data."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    amount: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    client_order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class OrderResult:
    """Order execution result."""
    success: bool
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    order_type: Optional[str] = None
    amount: float = 0.0
    filled: float = 0.0
    price: Optional[float] = None
    average_price: Optional[float] = None
    status: Optional[str] = None
    fee: float = 0.0
    fee_currency: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


class OrderManager:
    """
    Order management and tracking system.
    
    Features:
    - Order creation and tracking
    - Pre-trade validations
    - Retry logic for API errors
    - Partial fill handling
    - Order duplication prevention
    """
    
    def __init__(self, exchange):
        """
        Initialize order manager.
        
        Args:
            exchange: ccxt exchange instance
        """
        self.exchange = exchange
        self._pending_orders: Dict[str, OrderRequest] = {}
        self._order_history: List[OrderResult] = []
        self._order_lock = asyncio.Lock()
    
    async def create_order(self, request: OrderRequest) -> OrderResult:
        """
        Create and submit an order to the exchange.
        
        Args:
            request: Order request details
            
        Returns:
            Order execution result
        """
        async with self._order_lock:
            # Check for duplicate orders
            if self._is_duplicate_order(request):
                logger.warning(f"Duplicate order detected for {request.symbol}")
                return OrderResult(
                    success=False,
                    client_order_id=request.client_order_id,
                    error="Duplicate order"
                )
            
            # Validate order
            validation_error = self._validate_order(request)
            if validation_error:
                return OrderResult(
                    success=False,
                    client_order_id=request.client_order_id,
                    error=validation_error
                )
            
            # Track pending order
            self._pending_orders[request.client_order_id] = request
            
            try:
                result = await self._execute_with_retry(request)
                return result
            finally:
                # Remove from pending
                self._pending_orders.pop(request.client_order_id, None)
    
    async def _execute_with_retry(self, request: OrderRequest) -> OrderResult:
        """Execute order with retry logic."""
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                result = await self._submit_order(request)
                
                if result.success:
                    self._order_history.append(result)
                    logger.info(
                        f"Order executed: {request.side.value} {request.amount} {request.symbol} "
                        f"@ {result.average_price or result.price}"
                    )
                    return result
                
                last_error = result.error
                
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Order attempt {attempt + 1} failed: {e}")
            
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
        
        logger.error(f"Order failed after {MAX_RETRIES} attempts: {last_error}")
        return OrderResult(
            success=False,
            client_order_id=request.client_order_id,
            error=f"Failed after {MAX_RETRIES} attempts: {last_error}"
        )
    
    async def _submit_order(self, request: OrderRequest) -> OrderResult:
        """Submit order to exchange."""
        try:
            order_params = {}
            
            # Create order based on type
            if request.order_type == OrderType.MARKET:
                order = await self.exchange.create_order(
                    symbol=request.symbol,
                    type='market',
                    side=request.side.value,
                    amount=request.amount,
                    params=order_params
                )
            else:  # LIMIT
                if request.price is None:
                    raise ValueError("Limit order requires price")
                
                order = await self.exchange.create_order(
                    symbol=request.symbol,
                    type='limit',
                    side=request.side.value,
                    amount=request.amount,
                    price=request.price,
                    params=order_params
                )
            
            return OrderResult(
                success=True,
                order_id=order['id'],
                client_order_id=request.client_order_id,
                symbol=order['symbol'],
                side=order['side'],
                order_type=order['type'],
                amount=order['amount'],
                filled=order.get('filled', 0),
                price=order.get('price'),
                average_price=order.get('average'),
                status=order['status'],
                fee=order.get('fee', {}).get('cost', 0),
                fee_currency=order.get('fee', {}).get('currency')
            )
            
        except Exception as e:
            return OrderResult(
                success=False,
                client_order_id=request.client_order_id,
                error=str(e)
            )
    
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: Exchange order ID
            symbol: Trading pair
            
        Returns:
            True if cancelled successfully
        """
        try:
            await self.exchange.cancel_order(order_id, symbol)
            logger.info(f"Order {order_id} cancelled")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    async def get_order_status(self, order_id: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current order status from exchange."""
        try:
            order = await self.exchange.fetch_order(order_id, symbol)
            return order
        except Exception as e:
            logger.error(f"Failed to fetch order {order_id}: {e}")
            return None
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all open orders."""
        try:
            orders = await self.exchange.fetch_open_orders(symbol)
            return orders
        except Exception as e:
            logger.error(f"Failed to fetch open orders: {e}")
            return []
    
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """
        Cancel all open orders.
        
        Args:
            symbol: Trading pair (None for all symbols)
            
        Returns:
            Number of orders cancelled
        """
        try:
            open_orders = await self.get_open_orders(symbol)
            cancelled = 0
            
            for order in open_orders:
                if await self.cancel_order(order['id'], order['symbol']):
                    cancelled += 1
            
            logger.info(f"Cancelled {cancelled} orders")
            return cancelled
            
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return 0
    
    def _validate_order(self, request: OrderRequest) -> Optional[str]:
        """Validate order request."""
        # Check amount
        if request.amount <= 0:
            return "Invalid order amount"
        
        # Check price for limit orders
        if request.order_type == OrderType.LIMIT and request.price is None:
            return "Limit order requires price"
        
        # Check price validity
        if request.price is not None and request.price <= 0:
            return "Invalid order price"
        
        return None
    
    def _is_duplicate_order(self, request: OrderRequest) -> bool:
        """Check if order is a duplicate of pending order."""
        for pending in self._pending_orders.values():
            if (pending.symbol == request.symbol and
                pending.side == request.side and
                pending.amount == request.amount and
                (datetime.utcnow() - pending.created_at).seconds < 5):
                return True
        return False
    
    def get_order_history(self, limit: int = 100) -> List[OrderResult]:
        """Get recent order history."""
        return self._order_history[-limit:]
