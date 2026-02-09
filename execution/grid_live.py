import asyncio
import csv
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
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
    def __init__(self, symbols: List[str], testnet: bool = True):
        self.symbols = symbols
        self.testnet = testnet
        self.exchange = None
        self._trades_file = "data/grid_live_trades.csv"
        self._state_file = "data/grid_live_state.json"
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
        
        for symbol in symbols:
            self.strategies[symbol] = GridStrategy(symbol)
    
    def _init_data_files(self):
        os.makedirs("data", exist_ok=True)
        
        if not os.path.exists(self._trades_file):
            with open(self._trades_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'symbol', 'side', 'price', 'amount', 'value',
                    'order_id', 'status', 'realized_pnl', 'balance'
                ])
    
    async def start(self):
        self.exchange = create_exchange(testnet=self.testnet)
        await self.exchange.connect()
        
        validation = await self._validate_connection()
        if not validation['success']:
            logger.error(f"Exchange connection failed: {validation['error']}")
            return
        
        self.balance = validation['balance']
        self.initial_balance = self.balance
        
        logger.info(f"✅ Connected to Binance {'Testnet' if self.testnet else 'Mainnet'}")
        logger.info(f"💰 Balance: ${self.balance:.2f} USDT")
        
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
    
    async def _trading_loop(self):
        for symbol in self.symbols:
            await self._initialize_grid(symbol)
        
        while self._running:
            for symbol in self.symbols:
                try:
                    await self._process_symbol(symbol)
                except Exception as e:
                    logger.error(f"Error processing {symbol}: {e}")
            
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
        
        fills = strategy.check_grid_fills(current_price)
        
        for fill in fills:
            await self._process_fill(symbol, fill)
        
        await self._check_and_replace_orders(symbol)
    
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
