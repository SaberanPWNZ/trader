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
from strategies.ml_grid_advisor import MLGridAdvisor
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
        self.initial_base_price: Dict[str, float] = {}
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
        self._ml_advisor = MLGridAdvisor()
        self._grid_init_times: Dict[str, datetime] = {}
        self._last_rebalance_times: Dict[str, datetime] = {}
        self._grid_init_prices: Dict[str, float] = {}
        
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
                    'realized_pnl', 'balance', 'total_value', 'base_held'
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
            saved_initial = state.get('initial_balance', 0)
            if saved_initial > 0:
                self.initial_balance = saved_initial
            saved_prices = state.get('initial_base_prices', {})
            if saved_prices:
                self.initial_base_price.update(saved_prices)
            elif state.get('initial_eth_price'):
                self.initial_base_price['ETH'] = state['initial_eth_price']
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
                        best_i = 0
                        best_p = -float('inf')
                        for qi, qpos in enumerate(q):
                            p = (price - qpos['price']) * amount
                            if p > best_p:
                                best_p = p
                                best_i = qi
                        q.pop(best_i)

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

    async def _reconcile_positions(self):
        try:
            balance_info = await self.exchange.fetch_balance()
            for symbol in self.symbols:
                base = symbol.split('/')[0]
                actual_balance = balance_info.get(base, {}).get('total', 0)
                tracked_amount = sum(p.amount for p in self.positions[symbol])
                untracked = actual_balance - tracked_amount

                if untracked > 0.001:
                    ticker = await self.exchange.fetch_ticker(symbol)
                    current_price = ticker['last']
                    untracked_value = untracked * current_price

                    if untracked_value > settings.grid.min_order_value:
                        self.positions[symbol].append(LiveGridPosition(
                            symbol=symbol,
                            side='long',
                            entry_price=current_price,
                            amount=untracked,
                            order_id=f"reconciled_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                            opened_at=datetime.now()
                        ))
                        logger.info(f"🔄 Reconciled {untracked:.4f} {base} (${untracked_value:.2f}) as position @ ${current_price:.2f}")
                        await telegram.send_message(
                            f"🔄 Position reconciled: {symbol}\n"
                            f"Untracked: {untracked:.4f} {base} (${untracked_value:.2f})\n"
                            f"Added as position @ ${current_price:.2f}"
                        )
                elif tracked_amount > actual_balance + 0.001:
                    logger.warning(f"⚠️ {symbol}: Tracked {tracked_amount:.4f} > actual {actual_balance:.4f}, adjusting")
                    while self.positions[symbol] and sum(p.amount for p in self.positions[symbol]) > actual_balance + 0.001:
                        self.positions[symbol].pop()
        except Exception as e:
            logger.warning(f"Error reconciling positions: {e}")

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
        base_info = ', '.join(f"{k}: {v['total']:.4f} (${v['value']:.2f})" for k, v in validation.get('base_details', {}).items())
        logger.info(f"💰 Total account value: ${self.balance:.2f} (USDT: ${validation['usdt_total']:.2f} + {base_info or 'no base'})")
        
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
        if self.initial_balance <= 0:
            self.initial_balance = self.balance
            logger.info(f"📌 Initial balance set from validation: ${self.initial_balance:.2f}")
        self._restore_positions()
        await self._reconcile_positions()

        for sym in self.symbols:
            if sym not in self.initial_base_price:
                base = sym.split('/')[0]
                try:
                    t = await self.exchange.fetch_ticker(sym)
                    self.initial_base_price[base] = t['last']
                    logger.info(f"📌 Initial {base} price: ${t['last']:.6f}")
                except Exception:
                    pass

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

            base_value = 0.0
            base_details = {}
            for symbol in self.symbols:
                base = symbol.split('/')[0]
                base_total = balance_info.get(base, {}).get('total', 0)
                if base_total > 0:
                    ticker = await self.exchange.fetch_ticker(symbol)
                    val = base_total * ticker['last']
                    base_value += val
                    base_details[base] = {'total': base_total, 'value': val}

            total_value = usdt_total + base_value
            return {
                'success': True,
                'balance': total_value,
                'usdt_total': usdt_total,
                'usdt_free': balance_info.get('USDT', {}).get('free', 0),
                'base_details': base_details,
                'base_value': base_value
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _sync_trades_from_exchange(self, symbol: str):
        try:
            trades = await self.exchange.fetch_my_trades(symbol, limit=100)
            new_fills = []

            for trade in trades:
                trade_id = str(trade['id'])
                if trade_id in self._processed_trade_ids:
                    continue
                self._processed_trade_ids.add(trade_id)
                new_fills.append(trade)

            if not new_fills:
                return

            aggregated: Dict[str, dict] = {}
            for fill in new_fills:
                order_id = str(fill.get('order', fill['id']))
                if order_id in aggregated:
                    agg = aggregated[order_id]
                    old_cost = agg['price'] * agg['amount']
                    new_cost = fill['price'] * fill['amount']
                    agg['amount'] += fill['amount']
                    agg['cost'] += fill['cost']
                    agg['price'] = (old_cost + new_cost) / agg['amount'] if agg['amount'] > 0 else fill['price']
                    agg_fee = agg.get('fee', {}).get('cost', 0)
                    fill_fee = fill.get('fee', {}).get('cost', 0)
                    agg['fee'] = {'cost': agg_fee + fill_fee, 'currency': fill.get('fee', {}).get('currency', 'BNB')}
                    agg['fill_count'] += 1
                else:
                    aggregated[order_id] = {
                        **fill,
                        'id': order_id,
                        'fill_count': 1,
                        'fee': dict(fill.get('fee', {'cost': 0, 'currency': 'BNB'}))
                    }

            new_trades = sorted(aggregated.values(), key=lambda t: t.get('timestamp', 0))

            for trade in new_trades:
                trade_id = str(trade['id'])
                side = trade['side'].upper()
                price = trade['price']
                amount = trade['amount']
                value = trade['cost']
                fill_count = trade.get('fill_count', 1)

                logger.info(f"{'='*60}")
                logger.info(f"📝 NEW TRADE DETECTED: {symbol}")
                logger.info(f"   Order ID: {trade_id}{f' ({fill_count} fills aggregated)' if fill_count > 1 else ''}")
                logger.info(f"   Side: {side}")
                logger.info(f"   Price: ${price:.2f}")
                logger.info(f"   Amount: {amount:.6f}")
                logger.info(f"   Value: ${value:.2f}")
                logger.info(f"   Time: {datetime.fromtimestamp(trade['timestamp']/1000).strftime('%Y-%m-%d %H:%M:%S')}")

                fee = trade.get('fee', {}).get('cost', 0)
                self.total_fees_paid += fee

                trading_pnl = 0.0
                holding_pnl = 0.0

                logger.info(f"   Current positions: {len(self.positions[symbol])}")
                if side == 'SELL' and self.positions[symbol]:
                    best_idx = 0
                    best_profit = -float('inf')
                    for idx, p in enumerate(self.positions[symbol]):
                        profit = (price - p.entry_price) * amount
                        if profit > best_profit:
                            best_profit = profit
                            best_idx = idx
                    pos = self.positions[symbol].pop(best_idx)

                    gross_pnl = (price - pos.entry_price) * amount
                    trading_pnl = gross_pnl - fee
                    holding_pnl = (self.current_prices.get(symbol, price) - pos.entry_price) * amount if pos.entry_price != price else 0

                    pnl_pct = (gross_pnl / (pos.entry_price * amount)) * 100 if (pos.entry_price * amount) > 0 else 0
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
                base = symbol.split('/')[0]
                base_balance = balance_info.get(base, {}).get('total', 0)
                ticker = await self.exchange.fetch_ticker(symbol)
                base_value = base_balance * ticker['last']
                total_value = usdt_balance + base_value

                self.total_trades += 1
                logger.info(f"   Total Trades: {self.total_trades}")
                logger.info(f"   Balance: ${usdt_balance:.2f} USDT + {base_balance:.2f} {base} (${base_value:.2f})")
                logger.info(f"   Total Value: ${total_value:.2f}")
                logger.info(f"{'='*60}")

                self._log_trade_from_exchange(
                    symbol, side, price, amount, value,
                    trade_id, fee, trading_pnl, holding_pnl, usdt_balance, total_value, base_balance
                )

                await self._send_trade_notification(
                    symbol, side, price, amount, value, fee,
                    trading_pnl, total_value, usdt_balance, base_balance, base
                )

                logger.info(f"📝 Synced trade: {side} {symbol} @ ${price:.2f}, Trading PnL: ${trading_pnl:.2f}")

            logger.info(f"Synced {len(new_trades)} new trades for {symbol} ({len(new_fills)} fills)")

        except Exception as e:
            logger.error(f"Error syncing trades for {symbol}: {e}")
    
    async def _send_trade_notification(self, symbol: str, side: str, price: float,
                                       amount: float, value: float, fee: float,
                                       trading_pnl: float, total_value: float,
                                       usdt_balance: float, base_balance: float, base: str):
        try:
            win_rate = (self.winning_trades / self.completed_cycles * 100) if self.completed_cycles > 0 else 0
            open_pos = len(self.positions.get(symbol, []))

            if side == 'SELL':
                pnl_emoji = "✅" if trading_pnl >= 0 else "❌"
                msg = (
                    f"{pnl_emoji} <b>SELL {symbol}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Price: ${price:,.2f}\n"
                    f"📦 Amount: {amount:.4f} {base}\n"
                    f"💵 Value: ${value:,.2f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>PnL: ${trading_pnl:+.2f}</b>\n"
                    f"📈 Total Trading PnL: ${self.trading_pnl:+.2f}\n"
                    f"🏆 Win Rate: {self.winning_trades}/{self.completed_cycles} ({win_rate:.0f}%)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💎 Portfolio: ${total_value:,.2f}\n"
                    f"   💵 {usdt_balance:,.2f} USDT\n"
                    f"   🪙 {base_balance:.4f} {base}\n"
                    f"📋 Open: {open_pos} pos"
                )
            else:
                msg = (
                    f"🟢 <b>BUY {symbol}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Price: ${price:,.2f}\n"
                    f"📦 Amount: {amount:.4f} {base}\n"
                    f"💵 Value: ${value:,.2f}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💎 Portfolio: ${total_value:,.2f}\n"
                    f"   💵 {usdt_balance:,.2f} USDT\n"
                    f"   🪙 {base_balance:.4f} {base}\n"
                    f"📋 Open: {open_pos} pos"
                )

            await telegram.send_message(msg)
        except Exception as e:
            logger.error(f"Failed to send trade notification: {e}")

    def _log_trade_from_exchange(self, symbol: str, side: str, price: float, amount: float, 
                                  value: float, order_id: str, fee: float, trading_pnl: float,
                                  holding_pnl: float, balance: float, total_value: float, base_held: float):
        with open(self._trades_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat(),
                symbol, side, price, amount, value,
                order_id, 'filled', fee, trading_pnl, holding_pnl,
                self.realized_pnl, balance, total_value, base_held
            ])
    
    async def _update_balance_state(self):
        try:
            balance_info = await self.exchange.fetch_balance()
            usdt_total = balance_info.get('USDT', {}).get('total', 0)

            total_value = usdt_total
            base_balances = {}
            holding_pnl = 0
            for symbol in self.symbols:
                base = symbol.split('/')[0]
                base_total = balance_info.get(base, {}).get('total', 0)
                current_price = self.current_prices.get(symbol, 0)
                if base_total > 0 and current_price > 0:
                    base_value = base_total * current_price
                    total_value += base_value
                    base_balances[base] = {'total': base_total, 'price': current_price, 'value': base_value}
                    init_price = self.initial_base_price.get(base, 0)
                    if init_price > 0:
                        holding_pnl += base_total * (current_price - init_price)

            win_rate = (self.winning_trades / self.completed_cycles * 100) if self.completed_cycles > 0 else 0
            avg_profit_per_cycle = (self.trading_pnl / self.completed_cycles) if self.completed_cycles > 0 else 0

            persisted_initial = self.initial_balance
            persisted_start_time = datetime.now().isoformat()

            if os.path.exists(self._balance_file):
                with open(self._balance_file, 'r') as f:
                    old_state = json.load(f)
                    saved_initial = old_state.get('initial_balance', 0)
                    if saved_initial > 0:
                        persisted_initial = saved_initial
                    persisted_start_time = old_state.get('start_time', persisted_start_time)

            if persisted_initial <= 0:
                persisted_initial = total_value
                logger.warning(f"⚠️ initial_balance was 0, setting to current total_value: ${total_value:.2f}")

            state = {
                'initial_balance': persisted_initial,
                'initial_base_prices': self.initial_base_price,
                'start_time': persisted_start_time,
                'usdt_balance': usdt_total,
                'base_balances': base_balances,
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
                'symbols': self.symbols,
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
                    backoff = min(15 * (2 ** min(self._error_count - 1, 4)), 300)
                    logger.error(f"Error processing {symbol} (error {self._error_count}/{self._max_errors}): {e}")
                    
                    if self._error_count >= self._max_errors:
                        logger.warning(f"⚠️ {self._error_count} consecutive errors, reconnecting exchange...")
                        await telegram.send_message(f"⚠️ Reconnecting after {self._error_count} errors...")
                        try:
                            if self.exchange:
                                await self.exchange.disconnect()
                            self.exchange = create_exchange(testnet=self.testnet)
                            await self.exchange.connect()
                            self._error_count = 0
                            logger.info("✅ Exchange reconnected successfully")
                        except Exception as reconnect_err:
                            logger.error(f"Reconnect failed: {reconnect_err}")
                            await asyncio.sleep(backoff)
                    else:
                        await asyncio.sleep(backoff)
                    continue
            
            try:
                await self._update_balance_state()
            except Exception as e:
                logger.error(f"Error updating balance: {e}")
            
            await asyncio.sleep(15)
    
    async def _get_ml_advice(self, symbol: str):
        if not settings.grid.ml_advisor_enabled:
            return self._ml_advisor._default_advice("ML advisor disabled in config")
        try:
            ohlcv_raw = await self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            if not ohlcv_raw or len(ohlcv_raw) < 50:
                return self._ml_advisor._default_advice("not enough OHLCV data")
            df = pd.DataFrame(ohlcv_raw, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return self._ml_advisor.get_advice(symbol, df)
        except Exception as e:
            logger.warning(f"ML advice fetch failed for {symbol}: {e}")
            return self._ml_advisor._default_advice(f"fetch error: {e}")

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
        base = symbol.split('/')[0]

        if base not in self.initial_base_price:
            self.initial_base_price[base] = current_price
            logger.info(f"📌 Initial {base} price recorded: ${current_price:.6f}")

        advice = await self._get_ml_advice(symbol)
        grid_range_pct = advice.grid_range_pct
        center = current_price * (1 + advice.trend_bias)
        upper_price = center * (1 + grid_range_pct)
        lower_price = center * (1 - grid_range_pct)

        balance_info = await self.exchange.fetch_balance()
        usdt_free = balance_info.get('USDT', {}).get('free', 0)
        investment_per_symbol = usdt_free * settings.grid.investment_ratio

        num_grids = advice.recommended_grids
        if investment_per_symbol / max(num_grids, 1) < settings.grid.min_order_value:
            num_grids = max(1, int(investment_per_symbol / settings.grid.min_order_value))
        
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
        self._grid_init_times[symbol] = datetime.utcnow()
        self._grid_init_prices[symbol] = current_price
        
        ml_tag = f"🤖 ML: {advice.reason}" if advice.confidence > 0 else "📊 Default params"
        logger.info(f"Grid initialized for {symbol}:")
        logger.info(f"  {ml_tag}")
        logger.info(f"  Price: ${current_price:.2f}")
        logger.info(f"  Range: ${config.lower_price:.2f} - ${config.upper_price:.2f} ({grid_range_pct:.1%})")
        logger.info(f"  Spacing: ${config.grid_spacing:.2f}")
        logger.info(f"  Amount per grid: ${config.amount_per_grid:.2f}")
        
        await telegram.send_message(
            f"📊 Grid initialized: {symbol}\n"
            f"{ml_tag}\n"
            f"Price: ${current_price:.2f}\n"
            f"Range: ${config.lower_price:.2f} - ${config.upper_price:.2f} ({grid_range_pct:.1%})\n"
            f"Spacing: ${config.grid_spacing:.2f}\n"
            f"Order size: ${config.amount_per_grid:.2f}"
        )
        
        await self._place_grid_orders(symbol)
    
    async def _place_grid_orders(self, symbol: str):
        strategy = self.strategies[symbol]
        active_levels = strategy.get_active_levels()
        base = symbol.split('/')[0]

        balance_info = await self.exchange.fetch_balance()
        base_available = balance_info.get(base, {}).get('free', 0)

        market = await self._get_market_info(symbol)

        for level in active_levels:
            if level.order_id:
                continue

            try:
                side = level.side
                notional = level.amount * level.price

                if notional < market['min_notional']:
                    level.amount = (market['min_notional'] * 1.05) / level.price

                level.amount = self._round_amount(level.amount, market['amount_precision'])

                if side == 'sell' and base_available < level.amount:
                    logger.debug(f"Skipping SELL at ${level.price:.4f}: need {level.amount:.2f} {base}, have {base_available:.2f}")
                    continue

                level.price = self._round_price(level.price, market['price_precision'])

                order = await self.exchange.create_order(
                    symbol=symbol,
                    type='limit',
                    side=side,
                    amount=level.amount,
                    price=level.price
                )
                level.order_id = order['id']
                logger.info(f"Placed {side.upper()} order at ${level.price:.4f}, amount={level.amount:.2f} {base}, value=${level.amount * level.price:.2f}, id={order['id']}")

                if side == 'sell':
                    base_available -= level.amount

            except Exception as e:
                logger.error(f"Failed to place {side.upper()} order at ${level.price:.4f}: {e}")

    async def _get_market_info(self, symbol: str) -> dict:
        try:
            exchange = self.exchange._exchange if hasattr(self.exchange, '_exchange') else self.exchange
            market = exchange.market(symbol)
            return {
                'min_notional': market.get('limits', {}).get('cost', {}).get('min', 5.0) or 5.0,
                'min_amount': market.get('limits', {}).get('amount', {}).get('min', 1.0) or 1.0,
                'amount_precision': market.get('precision', {}).get('amount', 0.01),
                'price_precision': market.get('precision', {}).get('price', 0.0001),
            }
        except Exception:
            return {'min_notional': 5.0, 'min_amount': 1.0, 'amount_precision': 1.0, 'price_precision': 0.0001}

    def _round_amount(self, amount: float, precision: float) -> float:
        if precision <= 0:
            return round(amount)
        if precision >= 1:
            return round(amount / precision) * precision
        import math
        decimals = max(0, -int(math.log10(precision)))
        return round(math.floor(amount * 10**decimals) / 10**decimals, decimals)

    def _round_price(self, price: float, precision: float) -> float:
        if precision <= 0:
            return round(price, 6)
        if precision >= 1:
            return round(price / precision) * precision
        import math
        decimals = max(0, -int(math.log10(precision)))
        return round(price, decimals)
    
    async def _process_symbol(self, symbol: str):
        ticker = await self.exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        previous_price = self.current_prices.get(symbol, current_price)
        self.current_prices[symbol] = current_price
        
        strategy = self.strategies[symbol]
        
        if self._check_trailing_stop_loss(symbol, current_price):
            await self._emergency_close_all_positions(symbol, current_price)
            await self._reinitialize_grid(symbol, current_price)
            return
        
        open_positions = len(self.positions[symbol])
        if open_positions >= settings.grid.max_open_positions:
            await self._rebalance_excess_positions(symbol, current_price)
            return
        
        active_levels = strategy.get_active_levels()
        if len(active_levels) == 0:
            logger.info(f"{symbol}: All grid levels filled, reinitializing grid...")
            await self._reinitialize_grid(symbol, current_price)
            return
        
        if self._should_rebalance_grid(symbol, current_price, active_levels):
            logger.info(f"{symbol}: Grid rebalance triggered — price drifted from active levels")
            await self._reinitialize_grid(symbol, current_price)
            return
        
        fills = strategy.check_grid_fills(current_price)
        
        for fill in fills:
            await self._process_fill(symbol, fill)
        
        await self._check_and_replace_orders(symbol)
    
    def _should_rebalance_grid(self, symbol: str, current_price: float, active_levels: List[GridLevel]) -> bool:
        if not settings.grid.auto_rebalance_enabled:
            return False

        init_time = self._grid_init_times.get(symbol)
        if not init_time:
            return False

        cooldown = timedelta(minutes=settings.grid.rebalance_cooldown_minutes)
        if datetime.utcnow() - init_time < cooldown:
            return False

        buy_levels = [l for l in active_levels if l.side == "buy"]
        sell_levels = [l for l in active_levels if l.side == "sell"]

        nearest_buy = max((l.price for l in buy_levels), default=0)
        nearest_sell = min((l.price for l in sell_levels), default=float('inf'))

        if nearest_buy > 0 and nearest_sell < float('inf'):
            gap_pct = (nearest_sell - nearest_buy) / current_price
            if gap_pct > 0.04:
                in_gap = nearest_buy < current_price < nearest_sell
                if in_gap:
                    hours_since_init = (datetime.utcnow() - init_time).total_seconds() / 3600
                    force_hours = settings.grid.force_rebalance_after_hours
                    if hours_since_init >= force_hours:
                        logger.info(f"{symbol}: Force rebalance after {hours_since_init:.1f}h, gap={gap_pct:.1%}")
                        return True
                    if gap_pct > 0.06:
                        logger.info(f"{symbol}: Wide gap rebalance, gap={gap_pct:.1%}")
                        return True

        config = self.strategies[symbol].config
        if config:
            if current_price < config.lower_price or current_price > config.upper_price:
                logger.info(f"{symbol}: Price ${current_price:.2f} outside grid range ${config.lower_price:.2f}-${config.upper_price:.2f}")
                return True

        return False
    
    def _check_trailing_stop_loss(self, symbol: str, current_price: float) -> bool:
        """Перевірка trailing stop loss для захисту від downtrend."""
        if not settings.grid.trailing_stop_loss_enabled:
            return False
        
        init_price = self._grid_init_prices.get(symbol)
        if not init_price:
            return False
        
        price_drop_pct = (init_price - current_price) / init_price
        
        if price_drop_pct > settings.grid.trailing_stop_loss_trigger_percent / 100:
            logger.warning(
                f"{symbol}: Trailing stop loss triggered! "
                f"Price dropped {price_drop_pct*100:.1f}% "
                f"(${init_price:.2f} → ${current_price:.2f})"
            )
            return True
        
        return False
    
    async def _emergency_close_all_positions(self, symbol: str, current_price: float):
        """Екстрене закриття всіх позицій market ордером."""
        if not self.positions.get(symbol):
            return
        
        base = symbol.split('/')[0]
        total_amount = sum(p.amount for p in self.positions[symbol])
        
        if total_amount <= 0:
            return
        
        logger.warning(f"🚨 EMERGENCY CLOSE: Selling {total_amount} {base} @ market price")
        
        try:
            existing_orders = await self.exchange.fetch_open_orders(symbol)
            for order in existing_orders:
                try:
                    await self.exchange.cancel_order(order['id'], symbol)
                except Exception as e:
                    logger.warning(f"Failed to cancel order {order['id']}: {e}")
            
            await asyncio.sleep(0.5)
            
            market = await self._get_market_info(symbol)
            amount = self._round_amount(total_amount, market.get('amount_precision', 0.001))
            
            if amount > 0:
                order = await self.exchange.create_order(
                    symbol=symbol,
                    type='market',
                    side='sell',
                    amount=amount
                )
                logger.info(f"✅ Emergency sell executed: {amount} {base}")
                
                await telegram.send_message(
                    f"🚨 EMERGENCY STOP LOSS\n"
                    f"{symbol}\n"
                    f"Sold {amount} {base} @ market\n"
                    f"Reason: Price dropped > {settings.grid.trailing_stop_loss_trigger_percent}%"
                )
                
                self.positions[symbol] = []
                
        except Exception as e:
            logger.error(f"Emergency close failed: {e}")
    
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

        advice = await self._get_ml_advice(symbol)
        grid_range_pct = advice.grid_range_pct
        center = current_price * (1 + advice.trend_bias)
        upper_price = center * (1 + grid_range_pct)
        lower_price = center * (1 - grid_range_pct)

        self._grid_init_prices[symbol] = current_price
        
        balance_info = await self.exchange.fetch_balance()
        usdt_free = balance_info.get('USDT', {}).get('free', 0)
        investment = usdt_free * settings.grid.investment_ratio
        num_grids = advice.recommended_grids
        if investment / max(num_grids, 1) < settings.grid.min_order_value:
            num_grids = max(1, int(investment / settings.grid.min_order_value))
        
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
        self._grid_init_times[symbol] = datetime.utcnow()
        
        ml_tag = f"🤖 {advice.reason}" if advice.confidence > 0 else ""
        logger.info(f"Grid reinitialized for {symbol}:")
        logger.info(f"  Price: ${current_price:.2f}")
        logger.info(f"  Range: ${config.lower_price:.2f} - ${config.upper_price:.2f} ({grid_range_pct:.1%})")
        if ml_tag:
            logger.info(f"  {ml_tag}")
        
        await telegram.send_message(
            f"🔄 Grid rebalanced: {symbol}\n"
            f"Price: ${current_price:.2f}\n"
            f"Range: ${config.lower_price:.2f} - ${config.upper_price:.2f} ({grid_range_pct:.1%})"
            + (f"\n{ml_tag}" if ml_tag else "")
        )
        
        await self._place_grid_orders(symbol)
    
    async def _rebalance_excess_positions(self, symbol: str, current_price: float):
        open_positions = len(self.positions[symbol])
        max_positions = settings.grid.max_open_positions
        threshold = settings.grid.rebalance_threshold_positions

        if open_positions < threshold:
            return

        last_rebalance = self._last_rebalance_times.get(symbol)
        if last_rebalance:
            cooldown = timedelta(minutes=5)
            if datetime.utcnow() - last_rebalance < cooldown:
                return

        positions_to_close = open_positions - (max_positions - 1)
        if positions_to_close <= 0:
            return

        sorted_positions = sorted(
            enumerate(self.positions[symbol]),
            key=lambda x: x[1].entry_price,
            reverse=True
        )
        worst_positions = sorted_positions[:positions_to_close]

        avg_entry = sum(p.entry_price for _, p in worst_positions) / len(worst_positions)
        sell_price = max(avg_entry * 1.002, current_price * 1.001)

        total_amount = sum(p.amount for _, p in worst_positions)
        order_value = total_amount * sell_price
        
        if order_value < settings.grid.min_order_value:
            logger.debug(f"Rebalance order value ${order_value:.2f} below min ${settings.grid.min_order_value}, skipping")
            return

        logger.warning(f"⚠️ {symbol}: {open_positions} positions, placing limit sell for {positions_to_close} worst @ ${sell_price:.2f} (avg entry ${avg_entry:.2f})")

        base = symbol.split('/')[0]
        balance_info = await self.exchange.fetch_balance()
        base_available = balance_info.get(base, {}).get('free', 0)

        if total_amount > base_available:
            total_amount = base_available * 0.99

        if total_amount > 0:
            try:
                market = await self._get_market_info(symbol)
                amount = self._round_amount(total_amount, market.get('amount_precision', 0.001))
                sell_price = self._round_price(sell_price, market.get('price_precision', 0.01))

                if amount > 0:
                    order = await self.exchange.create_order(
                        symbol=symbol,
                        type='limit',
                        side='sell',
                        amount=amount,
                        price=sell_price
                    )
                    logger.info(f"📉 Limit SELL placed: {amount} {base} @ ${sell_price:.2f} (break-even rebalance)")
                    
                    self._last_rebalance_times[symbol] = datetime.utcnow()
                    
                    await telegram.send_message(
                        f"⚠️ REBALANCING {symbol}\n"
                        f"Open positions: {open_positions}\n"
                        f"Closed {positions_to_close} worst positions\n"
                        f"Avg entry: ${avg_entry:.2f}\n"
                        f"Limit sell: ${sell_price:.2f}\n"
                        f"Amount: {amount} {base}"
                    )
            except Exception as e:
                logger.error(f"Failed to execute rebalance sell: {e}")
    
    async def _process_fill(self, symbol: str, fill: dict):
        logger.debug(f"Grid fill detected: {fill['side']} @ ${fill['price']:.2f} - will be synced from exchange")
    
    async def _check_and_replace_orders(self, symbol: str):
        try:
            open_orders = await self.exchange.fetch_open_orders(symbol)
            base = symbol.split('/')[0]

            strategy = self.strategies[symbol]
            active_levels = strategy.get_active_levels()

            order_ids = {o['id'] for o in open_orders}

            for level in active_levels:
                if level.order_id and level.order_id not in order_ids:
                    level.filled = True
                    level.order_id = None

            balance = await self.exchange.fetch_balance()
            base_available = balance.get(base, {}).get('free', 0)
            market = await self._get_market_info(symbol)

            for level in active_levels:
                if not level.order_id and not level.filled:
                    notional = level.amount * level.price
                    if notional < market['min_notional']:
                        level.amount = (market['min_notional'] * 1.05) / level.price
                    level.amount = self._round_amount(level.amount, market['amount_precision'])
                    level.price = self._round_price(level.price, market['price_precision'])

                    if level.side == 'sell' and base_available < level.amount:
                        logger.debug(f"Skipping SELL: need {level.amount:.2f} {base}, have {base_available:.2f}")
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
                        logger.debug(f"Placed new {level.side} order at ${level.price:.4f}")

                        if level.side == 'sell':
                            base_available -= level.amount
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
