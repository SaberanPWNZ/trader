import asyncio
import csv
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from loguru import logger
import pandas as pd

from strategies.grid import GridStrategy, GridLevel, GridConfig
from monitoring.alerts import telegram
from config.settings import settings
from exchange.factory import create_exchange


@dataclass
class LiveGridPosition:
    symbol: str
    side: str
    entry_price: float
    amount: float
    order_id: str
    opened_at: datetime


class GridLiveTrader:
    def __init__(self, symbols: List[str], testnet: bool = True, max_balance: Optional[float] = None):
        self.symbols = symbols
        self.testnet = testnet
        self.max_balance = max_balance
        self.exchange = None
        self._trades_file = "data/grid_live_trades.csv"
        self._state_file = "data/grid_live_state.json"
        self._balance_file = "data/grid_live_balance.json"
        self._init_data_files()
        
        self.strategies: Dict[str, GridStrategy] = {}
        self.positions: Dict[str, List[LiveGridPosition]] = {s: [] for s in symbols}
        self.open_orders: Dict[str, List[dict]] = {s: [] for s in symbols}
        self.current_prices: Dict[str, float] = {}
        self.balance = 0.0
        self.initial_balance = 0.0
        self.realized_pnl = 0.0
        self.total_trades = 0
        self._running = False
        self._processed_trade_ids: Set[str] = set()
        self._last_trade_sync: datetime = datetime.min
        self._max_loss_pct = 0.15
        self._stop_loss_pct = 0.10
        self._error_count = 0
        self._max_errors = 10
        self._emergency_stop = False
        
        for symbol in symbols:
            self.strategies[symbol] = GridStrategy(symbol)
    
    def _init_data_files(self):
        os.makedirs("data", exist_ok=True)
        
        if not os.path.exists(self._trades_file):
            with open(self._trades_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'symbol', 'side', 'price', 'amount', 'value',
                    'order_id', 'status', 'realized_pnl', 'balance', 'total_value', 'eth_held'
                ])
        
        self._load_processed_trade_ids()
    
    def _load_processed_trade_ids(self):
        if os.path.exists(self._trades_file):
            try:
                df = pd.read_csv(self._trades_file)
                if 'order_id' in df.columns:
                    self._processed_trade_ids = set(df['order_id'].dropna().astype(str))
            except Exception:
                pass
    
    async def start(self):
        try:
            self.exchange = create_exchange(testnet=self.testnet)
            await self.exchange.connect()
        except Exception as e:
            logger.error(f"Failed to create exchange: {e}")
            await telegram.send_message(f"❌ Exchange connection failed: {e}")
            return
        
        validation = await self._validate_connection()
        if not validation['success']:
            logger.error(f"Exchange connection failed: {validation['error']}")
            await telegram.send_message(f"❌ Validation failed: {validation['error']}")
            return
        
        actual_balance = validation['balance']
        if self.max_balance and self.max_balance < actual_balance:
            self.balance = self.max_balance
            logger.info(f"⚠️ Using limited balance: ${self.balance:.2f} (available: ${actual_balance:.2f})")
        else:
            self.balance = actual_balance
        self.initial_balance = self.balance
        
        logger.info(f"✅ Connected to Binance {'Testnet' if self.testnet else 'Mainnet'}")
        logger.info(f"💰 Balance: ${self.balance:.2f} USDT")
        logger.info(f"🛡️ Protection: Max loss {self._max_loss_pct*100:.0f}%, Stop-loss {self._stop_loss_pct*100:.0f}%")
        
        await telegram.send_message(
            f"🚀 GRID LIVE TRADING STARTED\n"
            f"Exchange: Binance {'Testnet' if self.testnet else '⚠️ MAINNET'}\n"
            f"Balance: ${self.balance:.2f}\n"
            f"Symbols: {', '.join(self.symbols)}"
        )
        
        self._running = True
        
        try:
            await self._trading_loop()
        except Exception as e:
            logger.error(f"Trading error: {e}")
            await telegram.send_message(f"❌ Grid trading error: {e}")
        finally:
            await self.stop()
    
    async def _validate_connection(self) -> dict:
        try:
            balance = await self.exchange.get_available_balance('USDT')
            return {'success': True, 'balance': balance}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _sync_trades_from_exchange(self, symbol: str):
        try:
            trades = await self.exchange.fetch_my_trades(symbol, limit=100)
            new_trades = []
            
            for trade in trades:
                trade_id = str(trade['id'])
                if trade_id in self._processed_trade_ids:
                    continue
                
                self._processed_trade_ids.add(trade_id)
                new_trades.append(trade)
                
                side = trade['side'].upper()
                price = trade['price']
                amount = trade['amount']
                value = trade['cost']
                
                pnl = 0.0
                if side == 'SELL' and self.positions[symbol]:
                    pos = self.positions[symbol].pop(0)
                    pnl = (price - pos.entry_price) * amount
                    self.realized_pnl += pnl
                elif side == 'BUY':
                    self.positions[symbol].append(LiveGridPosition(
                        symbol=symbol,
                        side='long',
                        entry_price=price,
                        amount=amount,
                        order_id=trade_id,
                        opened_at=datetime.fromisoformat(trade['datetime'].replace('Z', '+00:00'))
                    ))
                
                balance_info = await self.exchange.fetch_balance()
                usdt_balance = balance_info.get('USDT', {}).get('total', 0)
                eth_balance = balance_info.get('ETH', {}).get('total', 0)
                ticker = await self.exchange.fetch_ticker(symbol)
                eth_value = eth_balance * ticker['last']
                total_value = usdt_balance + eth_value
                
                self._log_trade_from_exchange(
                    symbol, side, price, amount, value, 
                    trade_id, pnl, usdt_balance, total_value, eth_balance
                )
                
                self.total_trades += 1
                logger.info(f"📝 Synced trade: {side} {symbol} @ ${price:.2f}, PnL: ${pnl:.2f}")
            
            if new_trades:
                logger.info(f"Synced {len(new_trades)} new trades for {symbol}")
                
        except Exception as e:
            logger.error(f"Error syncing trades for {symbol}: {e}")
    
    def _log_trade_from_exchange(self, symbol: str, side: str, price: float, amount: float, 
                                  value: float, order_id: str, pnl: float, balance: float, 
                                  total_value: float, eth_held: float):
        with open(self._trades_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat(),
                symbol, side, price, amount, value,
                order_id, 'filled', pnl, balance, total_value, eth_held
            ])
    
    async def _update_balance_state(self):
        try:
            balance_info = await self.exchange.fetch_balance()
            usdt_total = balance_info.get('USDT', {}).get('total', 0)
            eth_total = balance_info.get('ETH', {}).get('total', 0)
            
            total_value = usdt_total
            for symbol in self.symbols:
                if symbol in self.current_prices:
                    base_currency = symbol.split('/')[0]
                    if base_currency == 'ETH':
                        total_value += eth_total * self.current_prices[symbol]
            
            state = {
                'initial_balance': self.initial_balance,
                'start_time': datetime.now().isoformat(),
                'usdt_balance': usdt_total,
                'eth_balance': eth_total,
                'total_value': total_value,
                'realized_pnl': self.realized_pnl,
                'total_trades': self.total_trades,
                'last_update': datetime.utcnow().isoformat()
            }
            
            if os.path.exists(self._balance_file):
                with open(self._balance_file, 'r') as f:
                    old_state = json.load(f)
                    state['initial_balance'] = old_state.get('initial_balance', self.initial_balance)
                    state['start_time'] = old_state.get('start_time', datetime.now().isoformat())
            
            with open(self._balance_file, 'w') as f:
                json.dump(state, f, indent=2)
            
            await self._check_portfolio_protection(total_value)
                
        except Exception as e:
            logger.error(f"Error updating balance state: {e}")
    
    async def _check_portfolio_protection(self, current_value: float):
        try:
            loss = self.initial_balance - current_value
            loss_pct = (loss / self.initial_balance) if self.initial_balance > 0 else 0
            
            if loss_pct >= self._stop_loss_pct:
                warning_msg = (
                    f"⚠️ STOP-LOSS TRIGGERED\n"
                    f"Loss: ${loss:.2f} ({loss_pct*100:.1f}%)\n"
                    f"Initial: ${self.initial_balance:.2f}\n"
                    f"Current: ${current_value:.2f}"
                )
                logger.warning(warning_msg)
                await telegram.send_message(warning_msg)
                
                if loss_pct >= self._max_loss_pct:
                    emergency_msg = (
                        f"🚨 EMERGENCY STOP\n"
                        f"Max loss reached: {loss_pct*100:.1f}%\n"
                        f"Stopping trading..."
                    )
                    logger.critical(emergency_msg)
                    await telegram.send_message(emergency_msg)
                    self._emergency_stop = True
                    self._running = False
                    
        except Exception as e:
            logger.error(f"Error checking portfolio protection: {e}")
    
    async def _trading_loop(self):
        try:
            for symbol in self.symbols:
                await self._initialize_grid(symbol)
        except Exception as e:
            logger.error(f"Failed to initialize grids: {e}")
            await telegram.send_message(f"❌ Initialization failed: {e}")
            self._running = False
            return
        
        while self._running:
            if self._emergency_stop:
                logger.critical("Emergency stop activated, exiting trading loop")
                break
            
            for symbol in self.symbols:
                try:
                    await self._sync_trades_from_exchange(symbol)
                    await self._process_symbol(symbol)
                    self._error_count = 0
                except Exception as e:
                    self._error_count += 1
                    logger.error(f"Error processing {symbol} (error {self._error_count}/{self._max_errors}): {e}")
                    
                    if self._error_count >= self._max_errors:
                        error_msg = f"🚨 Too many errors ({self._error_count}), stopping trader"
                        logger.critical(error_msg)
                        await telegram.send_message(error_msg)
                        self._running = False
                        break
            
            try:
                await self._update_balance_state()
            except Exception as e:
                logger.error(f"Error updating balance: {e}")
            
            await asyncio.sleep(60)
    
    async def _initialize_grid(self, symbol: str):
        ticker = await self.exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        self.current_prices[symbol] = current_price
        
        grid_range_pct = 0.03
        upper_price = current_price * (1 + grid_range_pct)
        lower_price = current_price * (1 - grid_range_pct)
        
        investment_per_symbol = min(self.balance * 0.8, 2000.0)
        
        from strategies.grid import GridConfig
        config = GridConfig(
            symbol=symbol,
            upper_price=upper_price,
            lower_price=lower_price,
            num_grids=5,
            total_investment=investment_per_symbol
        )
        
        self.strategies[symbol].config = config
        self.strategies[symbol].center_price = current_price
        self.strategies[symbol]._create_grid_levels(current_price)
        self.strategies[symbol].initialized = True
        
        logger.info(f"Grid initialized for {symbol}:")
        logger.info(f"  Price: ${current_price:.2f}")
        logger.info(f"  Range: ${config.lower_price:.2f} - ${config.upper_price:.2f}")
        logger.info(f"  Spacing: ${config.grid_spacing:.2f}")
        logger.info(f"  Amount per grid: ${config.amount_per_grid:.2f}")
        
        await telegram.send_message(
            f"📊 Grid initialized: {symbol}\n"
            f"Price: ${current_price:.2f}\n"
            f"Range: ${config.lower_price:.2f} - ${config.upper_price:.2f}\n"
            f"Spacing: ${config.grid_spacing:.2f}\n"
            f"Order size: ${config.amount_per_grid:.2f}"
        )
        
        await self._place_grid_orders(symbol)
    
    async def _place_grid_orders(self, symbol: str):
        strategy = self.strategies[symbol]
        active_levels = strategy.get_active_levels()
        
        for level in active_levels:
            if level.order_id:
                continue
            
            try:
                side = 'buy' if level.side == 'buy' else 'sell'
                
                if side == 'buy':
                    order = await self.exchange.create_order(
                        symbol=symbol,
                        type='limit',
                        side=side,
                        amount=level.amount,
                        price=level.price
                    )
                    level.order_id = order['id']
                    logger.info(f"Placed {side.upper()} order at ${level.price:.2f}, id={order['id']}")
                
            except Exception as e:
                logger.error(f"Failed to place order at ${level.price:.2f}: {e}")
    
    async def _process_symbol(self, symbol: str):
        ticker = await self.exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        previous_price = self.current_prices.get(symbol, current_price)
        self.current_prices[symbol] = current_price
        
        strategy = self.strategies[symbol]
        
        active_levels = strategy.get_active_levels()
        if len(active_levels) == 0:
            logger.info(f"{symbol}: All grid levels filled, reinitializing grid...")
            await self._reinitialize_grid(symbol, current_price)
            return
        
        fills = strategy.check_grid_fills(current_price)
        
        for fill in fills:
            await self._process_fill(symbol, fill)
        
        await self._check_and_replace_orders(symbol)
    
    async def _reinitialize_grid(self, symbol: str, current_price: float):
        grid_range_pct = 0.03
        upper_price = current_price * (1 + grid_range_pct)
        lower_price = current_price * (1 - grid_range_pct)
        
        balance = await self.exchange.get_available_balance('USDT')
        investment = min(balance * 0.8, 2000.0)
        
        from strategies.grid import GridConfig
        config = GridConfig(
            symbol=symbol,
            upper_price=upper_price,
            lower_price=lower_price,
            num_grids=5,
            total_investment=investment
        )
        
        self.strategies[symbol].config = config
        self.strategies[symbol].center_price = current_price
        self.strategies[symbol].grid_levels = []
        self.strategies[symbol]._create_grid_levels(current_price)
        self.strategies[symbol].last_price = current_price
        
        logger.info(f"Grid reinitialized for {symbol}:")
        logger.info(f"  Price: ${current_price:.2f}")
        logger.info(f"  Range: ${config.lower_price:.2f} - ${config.upper_price:.2f}")
        
        await telegram.send_message(
            f"🔄 Grid rebalanced: {symbol}\n"
            f"Price: ${current_price:.2f}\n"
            f"Range: ${config.lower_price:.2f} - ${config.upper_price:.2f}"
        )
        
        await self._place_grid_orders(symbol)
    
    async def _process_fill(self, symbol: str, fill: dict):
        side = fill['side'].upper()
        price = fill['price']
        amount = fill['amount']
        value = fill['value']
        
        if side == 'BUY':
            self.positions[symbol].append(LiveGridPosition(
                symbol=symbol,
                side='long',
                entry_price=price,
                amount=amount,
                order_id=fill.get('order_id', ''),
                opened_at=datetime.utcnow()
            ))
            logger.info(f"📥 BUY filled: {symbol} @ ${price:.2f}")
        else:
            pnl = 0.0
            if self.positions[symbol]:
                pos = self.positions[symbol].pop(0)
                pnl = (price - pos.entry_price) * amount
                self.realized_pnl += pnl
            logger.info(f"📤 SELL filled: {symbol} @ ${price:.2f}, PnL: ${pnl:.2f}")
        
        self.total_trades += 1
        
        self._log_trade(symbol, side, price, amount, value, pnl)
        
        await telegram.send_message(
            f"{'📥' if side == 'BUY' else '📤'} {side}: {symbol}\n"
            f"Price: ${price:.2f}\n"
            f"Amount: {amount:.6f}\n"
            f"Value: ${value:.2f}"
        )
    
    async def _check_and_replace_orders(self, symbol: str):
        try:
            open_orders = await self.exchange.fetch_open_orders(symbol)
            
            strategy = self.strategies[symbol]
            active_levels = strategy.get_active_levels()
            
            order_ids = {o['id'] for o in open_orders}
            
            for level in active_levels:
                if level.order_id and level.order_id not in order_ids:
                    level.filled = True
                    level.order_id = None
            
            for level in active_levels:
                if not level.order_id and not level.filled:
                    try:
                        order = await self.exchange.create_order(
                            symbol=symbol,
                            type='limit',
                            side=level.side,
                            amount=level.amount,
                            price=level.price
                        )
                        level.order_id = order['id']
                        logger.debug(f"Placed new {level.side} order at ${level.price:.2f}")
                    except Exception as e:
                        logger.error(f"Failed to place order: {e}")
                        
        except Exception as e:
            logger.error(f"Error checking orders for {symbol}: {e}")
    
    def _log_trade(self, symbol: str, side: str, price: float, amount: float, value: float, pnl: float):
        with open(self._trades_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat(),
                symbol, side, price, amount, value,
                '', 'filled', pnl, self.balance
            ])
    
    async def stop(self):
        self._running = False
        
        for symbol in self.symbols:
            try:
                orders = await self.exchange.fetch_open_orders(symbol)
                for order in orders:
                    await self.exchange.cancel_order(order['id'], symbol)
                    logger.info(f"Cancelled order {order['id']}")
            except Exception as e:
                logger.error(f"Error cancelling orders for {symbol}: {e}")
        
        if self.exchange:
            await self.exchange.disconnect()
        
        pnl_pct = (self.realized_pnl / self.initial_balance) * 100 if self.initial_balance > 0 else 0
        
        await telegram.send_message(
            f"🛑 GRID LIVE TRADING STOPPED\n"
            f"Total trades: {self.total_trades}\n"
            f"Realized PnL: ${self.realized_pnl:.2f} ({pnl_pct:+.2f}%)"
        )
        
        logger.info("Grid live trading stopped")
