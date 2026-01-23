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
from strategies.base import BaseStrategy
from risk.manager import RiskManager
from learning.database import LearningDatabase
from learning.prediction_tracker import PredictionTracker
from monitoring.alerts import TelegramAlert


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
    def __init__(
        self,
        strategy: BaseStrategy,
        initial_balance: float = None,
        fee_rate: float = None,
        db: Optional[LearningDatabase] = None,
        exchange_client = None,
        symbols: Optional[List[str]] = None
    ):
        self.strategy = strategy
        self.initial_balance = initial_balance or settings.backtest.initial_balance
        self.fee_rate = fee_rate or settings.backtest.trading_fee
        self.symbols = symbols or settings.trading.symbols
        
        self._balance = self.initial_balance
        self._positions: Dict[str, PaperPosition] = {}
        self._orders: List[PaperOrder] = []
        self._trade_history: List[Dict[str, Any]] = []
        
        self.stats = PaperTradingStats(peak_balance=self.initial_balance)
        
        self.exchange = exchange_client
        self.risk_manager = RiskManager(self.initial_balance)
        self.db = db
        self.prediction_tracker: Optional[PredictionTracker] = None
        if db:
            self.prediction_tracker = PredictionTracker(db)
        
        self.telegram = TelegramAlert()
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._model_ids: Dict[str, str] = {}
        self._last_summary_time = datetime.utcnow()
    
    async def start(self) -> None:
        logger.info("Starting paper trading simulator")
        
        if self.db:
            await self.db.initialize()
            for symbol in self.symbols:
                deployed = await self.db.get_deployed_model(symbol)
                if deployed:
                    self._model_ids[symbol] = deployed['id']
                    logger.info(f"Using deployed model {deployed['id']} for {symbol}")
        
        self._running = True
        
        for symbol in self.symbols:
            task = asyncio.create_task(self._trading_loop(symbol))
            self._tasks.append(task)
        
        logger.info(f"Paper trading started for {self.symbols}")
    
    async def stop(self) -> None:
        logger.info("Stopping paper trading simulator")
        
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        for symbol in list(self._positions.keys()):
            await self._close_position(symbol, "Simulation stopped")
        
        logger.info("Paper trading stopped")
        self._print_summary()
        
        await self._send_summary()
    
    async def _fetch_market_data(self, symbol: str, limit: int = 200):
        import yfinance as yf
        import pandas as pd
        
        yf_symbol = settings.get_symbol_for_pybroker(symbol)
        ticker = yf.Ticker(yf_symbol)
        data = ticker.history(period="7d", interval="1h")
        
        if data.empty:
            return pd.DataFrame()
        
        data = data.reset_index()
        data.columns = [c.lower() for c in data.columns]
        if 'datetime' in data.columns:
            data = data.rename(columns={'datetime': 'timestamp'})
        elif 'date' in data.columns:
            data = data.rename(columns={'date': 'timestamp'})
        
        data['symbol'] = symbol
        return data.tail(limit)
    
    async def _trading_loop(self, symbol: str) -> None:
        logger.info(f"Starting trading loop for {symbol}")
        
        from strategies.ai_strategy import AIStrategy
        if isinstance(self.strategy, AIStrategy) and self.db:
            await self.strategy.load_model_for_symbol(symbol)
        
        while self._running:
            try:
                data = await self._fetch_market_data(symbol, limit=200)
                
                if data.empty:
                    logger.warning(f"No data for {symbol}, waiting...")
                    await asyncio.sleep(60)
                    continue
                
                current_price = data['close'].iloc[-1]
                if symbol in self._positions:
                    self._update_position_price(symbol, current_price)
                    await self._check_exit_conditions(symbol, current_price)
                
                signal = self.strategy.generate_signal(data)
                await self._process_signal(signal, current_price)
                
                self._update_stats()
                
                await self._check_send_summary()
                
                await asyncio.sleep(300)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in trading loop for {symbol}: {e}")
                await asyncio.sleep(60)
    
    async def _process_signal(self, signal: Signal, current_price: float) -> None:
        symbol = signal.symbol
        
        if signal.signal_type == SignalType.HOLD.value:
            return
        
        can_trade, reason = self.risk_manager.can_trade(symbol)
        if not can_trade:
            logger.debug(f"Cannot trade {symbol}: {reason}")
            return
        
        if symbol in self._positions:
            position = self._positions[symbol]
            
            if ((signal.signal_type == SignalType.BUY.value and position.side == 'short') or
                (signal.signal_type == SignalType.SELL.value and position.side == 'long')):
                await self._close_position(symbol, "Signal reversal")
            else:
                return
        
        await self._open_position(signal, current_price)
    
    async def _open_position(self, signal: Signal, current_price: float) -> None:
        symbol = signal.symbol
        entry_price = current_price
        
        if signal.stop_loss:
            position_size = self.risk_manager.calculate_position_size(
                entry_price, signal.stop_loss, symbol
            )
        else:
            position_size = (self._balance * 0.1) / entry_price
        
        if position_size <= 0:
            return
        
        fee = position_size * entry_price * self.fee_rate
        
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
        
        if self.prediction_tracker and symbol in self._model_ids:
            try:
                await self.prediction_tracker.log_prediction(
                    symbol=symbol,
                    signal=signal,
                    model_id=self._model_ids[symbol]
                )
            except Exception as e:
                logger.error(f"Failed to log prediction: {e}")
        
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
            f"size={position_size:.6f} @ {entry_price:.2f} conf={signal.confidence:.1%}"
        )
        
        await self.telegram.send_message(
            f"📈 <b>Paper Position Opened</b>\n"
            f"Symbol: {symbol}\n"
            f"Side: {position.side.upper()}\n"
            f"Size: {position_size:.6f}\n"
            f"Entry: ${entry_price:,.2f}\n"
            f"Confidence: {signal.confidence:.1%}\n"
            f"Stop Loss: ${position.stop_loss:,.2f}\n"
            f"Take Profit: ${position.take_profit:,.2f}"
        )
    
    async def _close_position(self, symbol: str, reason: str) -> None:
        if symbol not in self._positions:
            return
        
        position = self._positions[symbol]
        exit_price = position.current_price
        
        if position.side == 'long':
            pnl = (exit_price - position.entry_price) * position.amount
        else:
            pnl = (position.entry_price - exit_price) * position.amount
        
        exit_fee = position.amount * exit_price * self.fee_rate
        pnl -= exit_fee
        
        self._balance += pnl
        self.stats.total_pnl += pnl
        self.stats.total_fees += exit_fee
        self.stats.total_trades += 1
        
        if pnl > 0:
            self.stats.winning_trades += 1
        else:
            self.stats.losing_trades += 1
        
        if self.prediction_tracker:
            try:
                actual_outcome = 1 if pnl > 0 else -1 if pnl < 0 else 0
                await self.prediction_tracker.update_prediction_outcome(
                    symbol=symbol,
                    actual_outcome=actual_outcome,
                    exit_price=exit_price,
                    pnl=pnl
                )
            except Exception as e:
                logger.error(f"Failed to update prediction outcome: {e}")
        
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
        
        del self._positions[symbol]
        
        pnl_emoji = "✅" if pnl > 0 else "❌"
        logger.info(
            f"{pnl_emoji} Paper position closed: {symbol} "
            f"PnL={pnl:.2f} ({reason})"
        )
        
        duration = (datetime.utcnow() - position.opened_at).total_seconds() / 3600
        await self.telegram.send_message(
            f"{pnl_emoji} <b>Paper Position Closed</b>\n"
            f"Symbol: {symbol}\n"
            f"Side: {position.side.upper()}\n"
            f"Entry: ${position.entry_price:,.2f}\n"
            f"Exit: ${exit_price:,.2f}\n"
            f"PnL: ${pnl:,.2f}\n"
            f"Duration: {duration:.1f}h\n"
            f"Reason: {reason}"
        )
    
    async def _check_exit_conditions(self, symbol: str, current_price: float) -> None:
        if symbol not in self._positions:
            return
        
        position = self._positions[symbol]
        
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
    
    async def _check_send_summary(self) -> None:
        """Send periodic summary to Telegram (every 6 hours)."""
        now = datetime.utcnow()
        hours_since_last = (now - self._last_summary_time).total_seconds() / 3600
        
        if hours_since_last >= 6:
            await self._send_summary()
            self._last_summary_time = now
    
    async def _send_summary(self) -> None:
        """Send trading summary to Telegram."""
        equity = self._balance
        for position in self._positions.values():
            equity += position.unrealized_pnl
        
        win_rate = (self.stats.winning_trades / self.stats.total_trades * 100 
                   if self.stats.total_trades > 0 else 0)
        
        pnl_pct = (self.stats.total_pnl / self.initial_balance) * 100
        
        open_positions = ""
        if self._positions:
            open_positions = "\\n\\n<b>Open Positions:</b>\\n"
            for symbol, pos in self._positions.items():
                pnl_emoji = "📈" if pos.unrealized_pnl > 0 else "📉"
                open_positions += (
                    f"{pnl_emoji} {symbol} {pos.side.upper()}\\n"
                    f"  Entry: ${pos.entry_price:,.2f}\\n"
                    f"  Current: ${pos.current_price:,.2f}\\n"
                    f"  Unrealized PnL: ${pos.unrealized_pnl:,.2f}\\n"
                )
        
        await self.telegram.send_message(
            f"📊 <b>Paper Trading Report</b>\\n\\n"
            f"💰 Balance: ${self._balance:,.2f}\\n"
            f"📈 Equity: ${equity:,.2f}\\n"
            f"💵 Total PnL: ${self.stats.total_pnl:,.2f} ({pnl_pct:+.2f}%)\\n\\n"
            f"📊 Trades: {self.stats.total_trades}\\n"
            f"✅ Wins: {self.stats.winning_trades}\\n"
            f"❌ Losses: {self.stats.losing_trades}\\n"
            f"🎯 Win Rate: {win_rate:.1f}%\\n"
            f"📉 Max DD: {self.stats.max_drawdown*100:.2f}%"
            f"{open_positions}"
        )
    
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
