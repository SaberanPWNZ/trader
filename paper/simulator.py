"""
Paper trading simulator for live market testing without real money.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import uuid
from loguru import logger

from config.settings import settings
from config.constants import OrderSide, OrderType, SignalType
from data.models import Signal, Position
from data.collector import DataCollector
from strategies.base import BaseStrategy
from risk.manager import RiskManager


@dataclass
class PaperOrder:
    """Paper trading order."""
    id: str
    symbol: str
    side: str
    order_type: str
    amount: float
    price: Optional[float]
    filled: float = 0.0
    status: str = "pending"
    fee: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None


@dataclass
class PaperPosition:
    """Paper trading position."""
    id: str
    symbol: str
    side: str
    entry_price: float
    current_price: float
    amount: float
    unrealized_pnl: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PaperTradingStats:
    """Paper trading statistics."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    max_drawdown: float = 0.0
    peak_balance: float = 0.0


class PaperTradingSimulator:
    """
    Paper trading simulator for strategy testing in live market conditions.
    
    Features:
    - Simulated account balance
    - Virtual order execution
    - Fee accounting
    - Performance tracking
    - Comparison with live results
    """
    
    def __init__(
        self,
        strategy: BaseStrategy,
        initial_balance: float = None,
        fee_rate: float = None
    ):
        """
        Initialize paper trading simulator.
        
        Args:
            strategy: Trading strategy to simulate
            initial_balance: Starting balance
            fee_rate: Trading fee rate
        """
        self.strategy = strategy
        self.initial_balance = initial_balance or settings.backtest.initial_balance
        self.fee_rate = fee_rate or settings.backtest.trading_fee
        
        # Account state
        self._balance = self.initial_balance
        self._positions: Dict[str, PaperPosition] = {}
        self._orders: List[PaperOrder] = []
        self._trade_history: List[Dict[str, Any]] = []
        
        # Statistics
        self.stats = PaperTradingStats(peak_balance=self.initial_balance)
        
        # Components
        self.data_collector: Optional[DataCollector] = None
        self.risk_manager = RiskManager(self.initial_balance)
        
        # Control
        self._running = False
        self._tasks: List[asyncio.Task] = []
    
    async def start(self) -> None:
        """Start paper trading simulation."""
        logger.info("Starting paper trading simulator")
        
        # Initialize data collector
        self.data_collector = DataCollector()
        await self.data_collector.connect()
        
        self._running = True
        
        # Start trading loop for each symbol
        for symbol in settings.trading.symbols:
            task = asyncio.create_task(self._trading_loop(symbol))
            self._tasks.append(task)
        
        logger.info(f"Paper trading started for {settings.trading.symbols}")
    
    async def stop(self) -> None:
        """Stop paper trading simulation."""
        logger.info("Stopping paper trading simulator")
        
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Close all positions
        for symbol in list(self._positions.keys()):
            await self._close_position(symbol, "Simulation stopped")
        
        # Disconnect
        if self.data_collector:
            await self.data_collector.disconnect()
        
        logger.info("Paper trading stopped")
        self._print_summary()
    
    async def _trading_loop(self, symbol: str) -> None:
        """Main trading loop for a symbol."""
        logger.info(f"Starting trading loop for {symbol}")
        
        while self._running:
            try:
                # Fetch current data
                data = await self.data_collector.fetch_ohlcv(
                    symbol,
                    settings.trading.default_timeframe,
                    limit=200
                )
                
                if data.empty:
                    await asyncio.sleep(60)
                    continue
                
                # Update position prices
                current_price = data['close'].iloc[-1]
                if symbol in self._positions:
                    self._update_position_price(symbol, current_price)
                    
                    # Check stop-loss / take-profit
                    await self._check_exit_conditions(symbol, current_price)
                
                # Generate and process signal
                signal = self.strategy.generate_signal(data)
                await self._process_signal(signal, current_price)
                
                # Update statistics
                self._update_stats()
                
                # Wait for next iteration
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in trading loop for {symbol}: {e}")
                await asyncio.sleep(60)
    
    async def _process_signal(self, signal: Signal, current_price: float) -> None:
        """Process trading signal."""
        symbol = signal.symbol
        
        # Skip HOLD signals
        if signal.signal_type == SignalType.HOLD.value:
            return
        
        # Check risk management
        can_trade, reason = self.risk_manager.can_trade(symbol)
        if not can_trade:
            logger.debug(f"Cannot trade {symbol}: {reason}")
            return
        
        # Handle existing position
        if symbol in self._positions:
            position = self._positions[symbol]
            
            # Close on opposite signal
            if ((signal.signal_type == SignalType.BUY.value and position.side == 'short') or
                (signal.signal_type == SignalType.SELL.value and position.side == 'long')):
                await self._close_position(symbol, "Signal reversal")
            else:
                return  # Already have position in same direction
        
        # Open new position
        await self._open_position(signal, current_price)
    
    async def _open_position(self, signal: Signal, current_price: float) -> None:
        """Open a new paper position."""
        symbol = signal.symbol
        entry_price = current_price
        
        # Calculate position size
        if signal.stop_loss:
            position_size = self.risk_manager.calculate_position_size(
                entry_price, signal.stop_loss, symbol
            )
        else:
            position_size = (self._balance * 0.1) / entry_price
        
        if position_size <= 0:
            return
        
        # Calculate fee
        fee = position_size * entry_price * self.fee_rate
        
        # Create position
        position = PaperPosition(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side='long' if signal.signal_type == SignalType.BUY.value else 'short',
            entry_price=entry_price,
            current_price=entry_price,
            amount=position_size,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit
        )
        
        self._positions[symbol] = position
        self._balance -= fee
        self.stats.total_fees += fee
        
        # Create order record
        order = PaperOrder(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side=position.side,
            order_type='market',
            amount=position_size,
            price=entry_price,
            filled=position_size,
            status='filled',
            fee=fee,
            filled_at=datetime.utcnow()
        )
        self._orders.append(order)
        
        logger.info(
            f"📈 Paper {position.side.upper()} opened: {symbol} "
            f"size={position_size:.6f} @ {entry_price:.2f}"
        )
    
    async def _close_position(self, symbol: str, reason: str) -> None:
        """Close a paper position."""
        if symbol not in self._positions:
            return
        
        position = self._positions[symbol]
        exit_price = position.current_price
        
        # Calculate PnL
        if position.side == 'long':
            pnl = (exit_price - position.entry_price) * position.amount
        else:
            pnl = (position.entry_price - exit_price) * position.amount
        
        # Calculate exit fee
        exit_fee = position.amount * exit_price * self.fee_rate
        pnl -= exit_fee
        
        # Update balance and stats
        self._balance += pnl
        self.stats.total_pnl += pnl
        self.stats.total_fees += exit_fee
        self.stats.total_trades += 1
        
        if pnl > 0:
            self.stats.winning_trades += 1
        else:
            self.stats.losing_trades += 1
        
        # Record trade
        self._trade_history.append({
            'symbol': symbol,
            'side': position.side,
            'entry_price': position.entry_price,
            'exit_price': exit_price,
            'amount': position.amount,
            'pnl': pnl,
            'entry_time': position.opened_at,
            'exit_time': datetime.utcnow(),
            'reason': reason
        })
        
        # Create closing order
        order = PaperOrder(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side='sell' if position.side == 'long' else 'buy',
            order_type='market',
            amount=position.amount,
            price=exit_price,
            filled=position.amount,
            status='filled',
            fee=exit_fee,
            filled_at=datetime.utcnow()
        )
        self._orders.append(order)
        
        # Remove position
        del self._positions[symbol]
        
        pnl_emoji = "✅" if pnl > 0 else "❌"
        logger.info(
            f"{pnl_emoji} Paper position closed: {symbol} "
            f"PnL={pnl:.2f} ({reason})"
        )
    
    async def _check_exit_conditions(self, symbol: str, current_price: float) -> None:
        """Check stop-loss and take-profit conditions."""
        if symbol not in self._positions:
            return
        
        position = self._positions[symbol]
        
        # Check stop-loss
        if position.stop_loss:
            if position.side == 'long' and current_price <= position.stop_loss:
                await self._close_position(symbol, "Stop-loss triggered")
                return
            elif position.side == 'short' and current_price >= position.stop_loss:
                await self._close_position(symbol, "Stop-loss triggered")
                return
        
        # Check take-profit
        if position.take_profit:
            if position.side == 'long' and current_price >= position.take_profit:
                await self._close_position(symbol, "Take-profit triggered")
                return
            elif position.side == 'short' and current_price <= position.take_profit:
                await self._close_position(symbol, "Take-profit triggered")
                return
    
    def _update_position_price(self, symbol: str, current_price: float) -> None:
        """Update position's current price and unrealized PnL."""
        if symbol not in self._positions:
            return
        
        position = self._positions[symbol]
        position.current_price = current_price
        
        if position.side == 'long':
            position.unrealized_pnl = (current_price - position.entry_price) * position.amount
        else:
            position.unrealized_pnl = (position.entry_price - current_price) * position.amount
    
    def _update_stats(self) -> None:
        """Update trading statistics."""
        # Calculate current equity
        equity = self._balance
        for position in self._positions.values():
            equity += position.unrealized_pnl
        
        # Update peak and drawdown
        if equity > self.stats.peak_balance:
            self.stats.peak_balance = equity
        
        drawdown = (self.stats.peak_balance - equity) / self.stats.peak_balance
        if drawdown > self.stats.max_drawdown:
            self.stats.max_drawdown = drawdown
    
    def _print_summary(self) -> None:
        """Print paper trading summary."""
        win_rate = (self.stats.winning_trades / self.stats.total_trades * 100 
                   if self.stats.total_trades > 0 else 0)
        
        summary = f"""
╔══════════════════════════════════════════════════════════╗
║              PAPER TRADING SUMMARY                       ║
╠══════════════════════════════════════════════════════════╣
║  Initial Balance:    ${self.initial_balance:>12,.2f}               ║
║  Final Balance:      ${self._balance:>12,.2f}               ║
║  Total PnL:          ${self.stats.total_pnl:>12,.2f}               ║
║  Total Trades:       {self.stats.total_trades:>12}               ║
║  Winning Trades:     {self.stats.winning_trades:>12}               ║
║  Losing Trades:      {self.stats.losing_trades:>12}               ║
║  Win Rate:           {win_rate:>11.1f}%               ║
║  Max Drawdown:       {self.stats.max_drawdown*100:>11.1f}%               ║
║  Total Fees:         ${self.stats.total_fees:>12,.2f}               ║
╚══════════════════════════════════════════════════════════╝
"""
        logger.info(summary)
    
    @property
    def current_equity(self) -> float:
        """Get current equity including unrealized PnL."""
        equity = self._balance
        for position in self._positions.values():
            equity += position.unrealized_pnl
        return equity
    
    def get_status(self) -> Dict[str, Any]:
        """Get current simulator status."""
        return {
            'running': self._running,
            'balance': self._balance,
            'equity': self.current_equity,
            'open_positions': len(self._positions),
            'total_trades': self.stats.total_trades,
            'total_pnl': self.stats.total_pnl,
            'win_rate': (self.stats.winning_trades / self.stats.total_trades 
                        if self.stats.total_trades > 0 else 0),
            'max_drawdown': self.stats.max_drawdown
        }
