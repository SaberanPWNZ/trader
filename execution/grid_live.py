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
    def __init__(self, symbols: List[str], testnet: bool = True):
        self.symbols = symbols
        self.testnet = testnet
        self.exchange = None
        self._trades_file = "data/grid_live_trades.csv"
        self._state_file = "data/grid_live_state.json"
        self._balance_file = "data/grid_live_balance.json"
        self._processed_trade_ids: Set[str] = set()
        self._init_data_files()
        
        self.strategies: Dict[str, GridStrategy] = {}
        self.positions: Dict[str, List[LiveGridPosition]] = {s: [] for s in symbols}
        self.open_orders: Dict[str, List[dict]] = {s: [] for s in symbols}
        self.current_prices: Dict[str, float] = {}
        self.balance = 0.0
        self.initial_balance = 0.0
        self.initial_eth_price = 0.0
        self.realized_pnl = 0.0
        self.trading_pnl = 0.0
        self.total_fees_paid = 0.0
        self.completed_cycles = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_trades = 0
        self._running = False
        self._last_trade_sync: datetime = datetime.min
        self._max_loss_pct = 0.15
        self._stop_loss_pct = 0.10
        self._error_count = 0
        self._max_errors = 10
        self._emergency_stop = False
        self._buy_positions: Dict[str, List[Dict]] = {s: [] for s in symbols}
        
        for symbol in symbols:
            self.strategies[symbol] = GridStrategy(symbol)
    
    def _init_data_files(self):
        os.makedirs("data", exist_ok=True)
        
        if not os.path.exists(self._trades_file):
            with open(self._trades_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'symbol', 'side', 'price', 'amount', 'value',
                    'order_id', 'status', 'fee', 'trading_pnl', 'holding_pnl', 
                    'realized_pnl', 'balance', 'total_value', 'eth_held'
                ])
        
        self._load_processed_trade_ids()
    
    def _load_processed_trade_ids(self):
        if os.path.exists(self._trades_file):
            try:
                with open(self._trades_file, 'r') as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    if not header:
                        return
                    for row in reader:
                        if len(row) >= 7 and row[6]:
                            self._processed_trade_ids.add(str(row[6]))
                logger.info(f"Loaded {len(self._processed_trade_ids)} processed trade IDs")
            except Exception as e:
                logger.warning(f"Error loading trade IDs: {e}")
    
    def _restore_state(self):
        if not os.path.exists(self._balance_file):
            return
        try:
            with open(self._balance_file, 'r') as f:
                state = json.load(f)
            self.initial_balance = state.get('initial_balance', self.initial_balance)
            self.initial_eth_price = state.get('initial_eth_price', self.initial_eth_price)
            self.trading_pnl = state.get('trading_pnl', 0)
            self.realized_pnl = state.get('realized_pnl', 0)
            self.total_fees_paid = state.get('total_fees_paid', 0)
            self.completed_cycles = state.get('completed_cycles', 0)
            self.winning_trades = state.get('winning_trades', 0)
            self.losing_trades = state.get('losing_trades', 0)
            self.total_trades = state.get('total_trades', 0)
            logger.info(f"📂 State restored: {self.completed_cycles} cycles, Trading PnL: ${self.trading_pnl:+.2f}")
        except Exception as e:
            logger.warning(f"Error restoring state: {e}")

    def _restore_positions(self):
        if not os.path.exists(self._trades_file):
            return
        try:
            with open(self._trades_file, 'r') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return
                rows = []
                seen = set()
                for row in reader:
                    if len(row) >= 7 and row[6] and row[6] not in seen:
                        seen.add(row[6])
                        rows.append(row)

            rows.sort(key=lambda x: x[0])
            buy_queue: Dict[str, List] = {s: [] for s in self.symbols}
            for row in rows:
                symbol = row[1] if len(row) > 1 else self.symbols[0]
                side = row[2].upper()
                price = float(row[3])
                amount = float(row[4])
                order_id = row[6]
                ts = row[0]
                if side == 'BUY':
                    buy_queue.setdefault(symbol, []).append({
                        'price': price, 'amount': amount, 'order_id': order_id, 'ts': ts
                    })
                elif side == 'SELL':
                    q = buy_queue.get(symbol, [])
                    if q:
                        q.pop(0)

            for symbol in self.symbols:
                for pos in buy_queue.get(symbol, []):
                    self.positions[symbol].append(LiveGridPosition(
                        symbol=symbol,
                        side='long',
                        entry_price=pos['price'],
                        amount=pos['amount'],
                        order_id=pos['order_id'],
                        opened_at=datetime.fromisoformat(pos['ts']) if pos['ts'] else datetime.now()
                    ))
                if self.positions[symbol]:
                    logger.info(f"📂 Restored {len(self.positions[symbol])} open positions for {symbol}")
        except Exception as e:
            logger.warning(f"Error restoring positions: {e}")

    async def _ensure_bnb_for_fees(self):
        try:
            balance_info = await self.exchange.fetch_balance()
            bnb_free = balance_info.get('BNB', {}).get('free', 0)

            ticker = await self.exchange.fetch_ticker('BNB/USDT')
            bnb_price = ticker['last']
            bnb_value = bnb_free * bnb_price

            if bnb_value < 3.0:
                usdt_free = balance_info.get('USDT', {}).get('free', 0)
                bnb_buy_usdt = 6.0
                if usdt_free >= bnb_buy_usdt:
                    bnb_qty = round(bnb_buy_usdt / bnb_price, 3)
                    bnb_qty = max(bnb_qty, 0.01)
                    order = await self.exchange.create_order(
                        symbol='BNB/USDT',
                        type='market',
                        side='buy',
                        amount=bnb_qty
                    )
                    logger.info(f"🔶 Bought {bnb_qty} BNB for fee discount (${bnb_qty * bnb_price:.2f})")
                    await telegram.send_message(f"🔶 Bought BNB for fee discount: {bnb_qty} BNB (${bnb_qty * bnb_price:.2f})")
                else:
                    logger.info(f"⏭️ Not enough free USDT for BNB (${usdt_free:.2f}), will buy after freeing capital")
            else:
                logger.info(f"🔶 BNB available for fees: {bnb_free:.4f} BNB (${bnb_value:.2f})")

            try:
                exchange = self.exchange._exchange if hasattr(self.exchange, '_exchange') else self.exchange
                resp = await exchange.sapiGetBnbBurn()
                if not resp.get('spotBNBBurn', False):
                    await exchange.sapiPostBnbBurn({'spotBNBBurn': 'true'})
                    logger.info("🔶 BNB burn enabled for spot fees (0.075% instead of 0.1%)")
                else:
                    logger.info("🔶 BNB burn already enabled")
            except Exception as e:
                logger.warning(f"Could not check/enable BNB burn: {e}")
        except Exception as e:
            logger.warning(f"Error ensuring BNB for fees: {e}")
    
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
        
        self.balance = validation['balance']
        self.initial_balance = self.balance
        logger.info(f"💰 Total account value: ${self.balance:.2f} (USDT: ${validation['usdt_total']:.2f} + ETH: ${validation['eth_value']:.2f})")
        
        mode = '🧪 TESTNET' if self.testnet else '🚀 MAINNET - REAL MONEY'
        logger.info(f"{'='*60}")
        logger.info(f"✅ Connected to Binance {mode}")
        logger.info(f"💰 Initial Balance: ${self.balance:.2f} USDT")
        logger.info(f"🛡️ Protection: Stop-loss {self._stop_loss_pct*100:.0f}%, Emergency {self._max_loss_pct*100:.0f}%")
        logger.info(f"📊 Trading Symbols: {', '.join(self.symbols)}")
        logger.info(f"{'='*60}")
        
        mode_emoji = '🧪' if self.testnet else '⚠️'
        mode_text = 'TESTNET' if self.testnet else '🔴 MAINNET (REAL MONEY)'
        await telegram.send_message(
            f"{mode_emoji} GRID LIVE TRADING STARTED\n"
            f"Exchange: Binance {mode_text}\n"
            f"Balance: ${self.balance:.2f} USDT\n"
            f"Symbols: {', '.join(self.symbols)}\n"
            f"Protection: {self._stop_loss_pct*100:.0f}% stop-loss"
        )
        
        self._running = True
        self._restore_state()
        self._restore_positions()
        
        try:
            await self._trading_loop()
        except Exception as e:
            logger.error(f"Trading error: {e}")
            await telegram.send_message(f"❌ Grid trading error: {e}")
        finally:
            await self.stop()
    
    async def _validate_connection(self) -> dict:
        try:
            balance_info = await self.exchange.fetch_balance()
            usdt_total = balance_info.get('USDT', {}).get('total', 0)
            eth_total = balance_info.get('ETH', {}).get('total', 0)

            eth_value = 0.0
            if eth_total > 0:
                ticker = await self.exchange.fetch_ticker(self.symbols[0])
                eth_value = eth_total * ticker['last']

            total_value = usdt_total + eth_value
            return {
                'success': True,
                'balance': total_value,
                'usdt_total': usdt_total,
                'usdt_free': balance_info.get('USDT', {}).get('free', 0),
                'eth_total': eth_total,
                'eth_value': eth_value
            }
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
                
                logger.info(f"{'='*60}")
                logger.info(f"📝 NEW TRADE DETECTED: {symbol}")
                logger.info(f"   Order ID: {trade_id}")
                logger.info(f"   Side: {side}")
                logger.info(f"   Price: ${price:.2f}")
                logger.info(f"   Amount: {amount:.6f}")
                logger.info(f"   Value: ${value:.2f}")
                logger.info(f"   Time: {datetime.fromtimestamp(trade['timestamp']/1000).strftime('%Y-%m-%d %H:%M:%S')}")
                
                pnl = 0.0
                fee = trade.get('fee', {}).get('cost', 0)
                self.total_fees_paid += fee
                
                trading_pnl = 0.0
                holding_pnl = 0.0
                
                logger.info(f"   Current positions: {len(self.positions[symbol])}")
                if side == 'SELL' and self.positions[symbol]:
                    pos = self.positions[symbol].pop(0)
                    
                    gross_pnl = (price - pos.entry_price) * amount
                    trading_pnl = gross_pnl - fee
                    holding_pnl = (self.current_prices.get(symbol, price) - pos.entry_price) * amount if pos.entry_price != price else 0
                    
                    pnl_pct = (gross_pnl / (pos.entry_price * amount)) * 100
                    self.realized_pnl += gross_pnl
                    self.trading_pnl += trading_pnl
                    self.completed_cycles += 1
                    
                    if trading_pnl > 0:
                        self.winning_trades += 1
                    else:
                        self.losing_trades += 1
                    
                    logger.info(f"   ✅ POSITION CLOSED (Cycle #{self.completed_cycles})")
                    logger.info(f"   Entry Price: ${pos.entry_price:.2f}")
                    logger.info(f"   Exit Price: ${price:.2f}")
                    logger.info(f"   Gross PnL: ${gross_pnl:+.2f} ({pnl_pct:+.2f}%)")
                    logger.info(f"   Trading PnL: ${trading_pnl:+.2f} (after ${fee:.4f} fee)")
                    logger.info(f"   Win Rate: {self.winning_trades}/{self.completed_cycles} ({self.winning_trades/self.completed_cycles*100:.1f}%)")
                    logger.info(f"   Total Trading PnL: ${self.trading_pnl:+.2f}")
                elif side == 'BUY':
                    self.positions[symbol].append(LiveGridPosition(
                        symbol=symbol,
                        side='long',
                        entry_price=price,
                        amount=amount,
                        order_id=trade_id,
                        opened_at=datetime.fromisoformat(trade['datetime'].replace('Z', '+00:00'))
                    ))
                    logger.info(f"   🟢 POSITION OPENED")
                    logger.info(f"   Entry Price: ${price:.2f}")
                    logger.info(f"   Amount: {amount:.6f} {symbol.split('/')[0]}")
                    logger.info(f"   Value: ${value:.2f} USDT")
                    logger.info(f"   Fee: ${fee:.4f}")
                    logger.info(f"   Total Open Positions: {len(self.positions[symbol])}")
                
                balance_info = await self.exchange.fetch_balance()
                usdt_balance = balance_info.get('USDT', {}).get('total', 0)
                eth_balance = balance_info.get('ETH', {}).get('total', 0)
                ticker = await self.exchange.fetch_ticker(symbol)
                eth_value = eth_balance * ticker['last']
                total_value = usdt_balance + eth_value
                
                self.total_trades += 1
                logger.info(f"   Total Trades: {self.total_trades}")
                logger.info(f"   Balance: ${usdt_balance:.2f} USDT + {eth_balance:.6f} ETH (${eth_value:.2f})")
                logger.info(f"   Total Value: ${total_value:.2f}")
                logger.info(f"{'='*60}")
                
                self._log_trade_from_exchange(
                    symbol, side, price, amount, value, 
                    trade_id, fee, trading_pnl, holding_pnl, usdt_balance, total_value, eth_balance
                )
                
                logger.info(f"📝 Synced trade: {side} {symbol} @ ${price:.2f}, Trading PnL: ${trading_pnl:.2f}")
            
            if new_trades:
                logger.info(f"Synced {len(new_trades)} new trades for {symbol}")
                
        except Exception as e:
            logger.error(f"Error syncing trades for {symbol}: {e}")
    
    def _log_trade_from_exchange(self, symbol: str, side: str, price: float, amount: float, 
                                  value: float, order_id: str, fee: float, trading_pnl: float,
                                  holding_pnl: float, balance: float, total_value: float, eth_held: float):
        with open(self._trades_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat(),
                symbol, side, price, amount, value,
                order_id, 'filled', fee, trading_pnl, holding_pnl,
                self.realized_pnl, balance, total_value, eth_held
            ])
    
    async def _update_balance_state(self):
        try:
            balance_info = await self.exchange.fetch_balance()
            usdt_total = balance_info.get('USDT', {}).get('total', 0)
            eth_total = balance_info.get('ETH', {}).get('total', 0)
            
            total_value = usdt_total
            current_eth_price = 0
            for symbol in self.symbols:
                if symbol in self.current_prices:
                    base_currency = symbol.split('/')[0]
                    if base_currency == 'ETH':
                        current_eth_price = self.current_prices[symbol]
                        total_value += eth_total * current_eth_price
            
            holding_pnl = 0
            if self.initial_eth_price > 0 and eth_total > 0:
                holding_pnl = eth_total * (current_eth_price - self.initial_eth_price)
            
            win_rate = (self.winning_trades / self.completed_cycles * 100) if self.completed_cycles > 0 else 0
            avg_profit_per_cycle = (self.trading_pnl / self.completed_cycles) if self.completed_cycles > 0 else 0
            
            persisted_initial = self.initial_balance
            persisted_eth_price = self.initial_eth_price
            persisted_start_time = datetime.now().isoformat()
            
            if os.path.exists(self._balance_file):
                with open(self._balance_file, 'r') as f:
                    old_state = json.load(f)
                    persisted_initial = old_state.get('initial_balance', self.initial_balance)
                    persisted_eth_price = old_state.get('initial_eth_price', self.initial_eth_price)
                    persisted_start_time = old_state.get('start_time', persisted_start_time)
            
            state = {
                'initial_balance': persisted_initial,
                'initial_eth_price': persisted_eth_price,
                'start_time': persisted_start_time,
                'usdt_balance': usdt_total,
                'eth_balance': eth_total,
                'eth_price': current_eth_price,
                'total_value': total_value,
                'trading_pnl': self.trading_pnl,
                'holding_pnl': holding_pnl,
                'realized_pnl': self.realized_pnl,
                'total_fees_paid': self.total_fees_paid,
                'total_trades': self.total_trades,
                'completed_cycles': self.completed_cycles,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'win_rate': win_rate,
                'avg_profit_per_cycle': avg_profit_per_cycle,
                'last_update': datetime.utcnow().isoformat()
            }
            
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
        try:
            existing_orders = await self.exchange.fetch_open_orders(symbol)
            if existing_orders:
                logger.info(f"Cancelling {len(existing_orders)} existing orders before grid init...")
                for order in existing_orders:
                    try:
                        await self.exchange.cancel_order(order['id'], symbol)
                    except Exception as e:
                        logger.warning(f"Failed to cancel order {order['id']}: {e}")
                await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Error cancelling old orders: {e}")

        await self._ensure_bnb_for_fees()

        ticker = await self.exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        self.current_prices[symbol] = current_price
        
        if self.initial_eth_price == 0.0 and symbol == 'ETH/USDT':
            self.initial_eth_price = current_price
            logger.info(f"📌 Initial ETH price recorded: ${current_price:.2f}")
        
        grid_range_pct = 0.03
        upper_price = current_price * (1 + grid_range_pct)
        lower_price = current_price * (1 - grid_range_pct)
        
        balance_info = await self.exchange.fetch_balance()
        usdt_free = balance_info.get('USDT', {}).get('free', 0)
        investment_per_symbol = usdt_free * 0.95
        
        num_grids = max(2, min(4, int(investment_per_symbol / 50)))
        if investment_per_symbol / max(num_grids, 1) < 5.5:
            num_grids = max(1, int(investment_per_symbol / 5.5))
        
        from strategies.grid import GridConfig
        config = GridConfig(
            symbol=symbol,
            upper_price=upper_price,
            lower_price=lower_price,
            num_grids=num_grids,
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
        
        balance_info = await self.exchange.fetch_balance()
        eth_available = balance_info.get('ETH', {}).get('free', 0)
        
        for level in active_levels:
            if level.order_id:
                continue
            
            try:
                side = level.side
                
                if side == 'sell' and eth_available < level.amount:
                    logger.debug(f"Skipping SELL at ${level.price:.2f}: need {level.amount:.6f} ETH, have {eth_available:.6f}")
                    continue
                
                order = await self.exchange.create_order(
                    symbol=symbol,
                    type='limit',
                    side=side,
                    amount=level.amount,
                    price=level.price
                )
                level.order_id = order['id']
                logger.info(f"Placed {side.upper()} order at ${level.price:.2f}, amount={level.amount:.6f}, id={order['id']}")
                
                if side == 'sell':
                    eth_available -= level.amount
                
            except Exception as e:
                logger.error(f"Failed to place {side.upper()} order at ${level.price:.2f}: {e}")
    
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
        try:
            existing_orders = await self.exchange.fetch_open_orders(symbol)
            if existing_orders:
                logger.info(f"Cancelling {len(existing_orders)} orders before rebalance...")
                for order in existing_orders:
                    try:
                        await self.exchange.cancel_order(order['id'], symbol)
                    except Exception as e:
                        logger.warning(f"Failed to cancel order {order['id']}: {e}")
                await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Error cancelling old orders: {e}")

        grid_range_pct = 0.03
        upper_price = current_price * (1 + grid_range_pct)
        lower_price = current_price * (1 - grid_range_pct)
        
        balance_info = await self.exchange.fetch_balance()
        usdt_free = balance_info.get('USDT', {}).get('free', 0)
        investment = usdt_free * 0.95
        num_grids = max(2, min(4, int(investment / 50)))
        if investment / max(num_grids, 1) < 5.5:
            num_grids = max(1, int(investment / 5.5))
        
        from strategies.grid import GridConfig
        config = GridConfig(
            symbol=symbol,
            upper_price=upper_price,
            lower_price=lower_price,
            num_grids=num_grids,
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
        logger.debug(f"Grid fill detected: {fill['side']} @ ${fill['price']:.2f} - will be synced from exchange")
    
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
            
            balance = await self.exchange.fetch_balance()
            eth_available = balance.get('ETH', {}).get('free', 0)
            
            for level in active_levels:
                if not level.order_id and not level.filled:
                    if level.side == 'sell' and eth_available < level.amount:
                        logger.debug(f"Skipping SELL order: need {level.amount:.6f} ETH, have {eth_available:.6f}")
                        continue
                    
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
                        
                        if level.side == 'sell':
                            eth_available -= level.amount
                    except Exception as e:
                        logger.error(f"Failed to place order: {e}")
                        
        except Exception as e:
            logger.error(f"Error checking orders for {symbol}: {e}")
    
    def _log_trade(self, symbol: str, side: str, price: float, amount: float, value: float, pnl: float):
        pass
    
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
