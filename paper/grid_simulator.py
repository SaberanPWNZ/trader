import asyncio
import csv
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from loguru import logger
import pandas as pd

from strategies.grid import GridStrategy
from strategies.indicators import TechnicalIndicators
from monitoring.alerts import telegram
from config.settings import settings


@dataclass
class TradeRecord:
    timestamp: str
    symbol: str
    side: str
    price: float
    amount: float
    value: float
    realized_pnl: float
    unrealized_pnl: float
    balance: float
    total_value: float
    roi_percent: float


@dataclass
class GridPosition:
    symbol: str
    side: str
    entry_price: float
    amount: float
    opened_at: datetime


class GridPaperSimulator:
    def __init__(self, symbols: List[str], initial_balance: float = 300.0):
        self.symbols = symbols
        self.initial_balance = initial_balance
        self._trades_file = "data/grid_trades.csv"
        self._snapshots_file = "data/grid_snapshots.csv"
        self._rebalances_file = "data/grid_rebalances.csv"
        self._state_file = "data/grid_state.json"
        self._init_data_files()
        self._load_state()
        
        self.balance = self._restore_balance_from_csv() or self.initial_balance
        self.realized_pnl = self._restore_realized_pnl() or 0.0
        
        self.strategies: Dict[str, GridStrategy] = {}
        self.positions: Dict[str, List[GridPosition]] = {s: [] for s in symbols}
        self.total_trades = 0
        self.winning_trades = 0
        self._running = False
        self._start_time = None
        self._last_12h_report = None
        self._last_24h_report = None
        self._trading_paused = False
        self._pause_until: Optional[datetime] = None
        
        for symbol in symbols:
            self.strategies[symbol] = GridStrategy(symbol)
    
    def _init_data_files(self):
        os.makedirs("data", exist_ok=True)
        
        if not os.path.exists(self._trades_file):
            with open(self._trades_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'symbol', 'side', 'price', 'amount', 'value',
                    'realized_pnl', 'unrealized_pnl', 'balance', 'total_value', 'roi_percent'
                ])
        
        if not os.path.exists(self._snapshots_file):
            with open(self._snapshots_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'balance', 'realized_pnl', 'unrealized_pnl',
                    'total_value', 'roi_percent', 'total_trades', 'win_rate',
                    'btc_price', 'eth_price', 'report_type'
                ])
        
        if not os.path.exists(self._rebalances_file):
            with open(self._rebalances_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'symbol', 'reason', 'old_range', 'new_range',
                    'open_positions', 'unrealized_pnl', 'positions_profitable', 'forced'
                ])
    
    def _save_trade(self, record: TradeRecord):
        with open(self._trades_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(asdict(record).values())
    
    def _save_snapshot(self, data: Dict, report_type: str = "periodic"):
        with open(self._snapshots_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat(),
                data.get('balance', 0),
                data.get('realized_pnl', 0),
                data.get('unrealized_pnl', 0),
                data.get('total_value', 0),
                data.get('roi_percent', 0),
                data.get('total_trades', 0),
                data.get('win_rate', 0),
                data.get('btc_price', 0),
                data.get('eth_price', 0),
                report_type
            ])
    
    def _save_rebalance_event(self, event_data: Dict):
        with open(self._rebalances_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                event_data['timestamp'],
                event_data['symbol'],
                event_data['reason'],
                event_data['old_range'],
                event_data['new_range'],
                event_data['open_positions'],
                event_data['unrealized_pnl'],
                event_data['positions_profitable'],
                event_data['forced']
            ])
    
    def _restore_balance_from_csv(self) -> Optional[float]:
        try:
            if os.path.exists(self._trades_file):
                with open(self._trades_file, 'r') as f:
                    lines = f.readlines()
                    if len(lines) > 1:
                        last_line = lines[-1].strip()
                        if last_line:
                            columns = last_line.split(',')
                            if len(columns) >= 9:
                                balance = float(columns[8])
                                logger.info(f"Відновлено баланс з CSV: ${balance:.2f}")
                                return balance
        except Exception as e:
            logger.warning(f"Не вдалося відновити баланс з CSV: {e}")
        return None
    
    def _restore_realized_pnl(self) -> Optional[float]:
        try:
            if os.path.exists(self._trades_file):
                with open(self._trades_file, 'r') as f:
                    lines = f.readlines()
                    if len(lines) > 1:
                        last_line = lines[-1].strip()
                        if last_line:
                            columns = last_line.split(',')
                            if len(columns) >= 7:
                                realized_pnl = float(columns[6])
                                logger.info(f"Відновлено realized PnL з CSV: ${realized_pnl:.2f}")
                                return realized_pnl
        except Exception as e:
            logger.warning(f"Не вдалося відновити realized PnL з CSV: {e}")
        return None

    def _load_state(self) -> None:
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, 'r') as f:
                    state = json.load(f)
                if isinstance(state, dict):
                    if "initial_balance" in state:
                        self.initial_balance = float(state["initial_balance"])
        except Exception as e:
            logger.warning(f"Не вдалося завантажити стан: {e}")

    def _save_state(self) -> None:
        try:
            state = {
                "initial_balance": self.initial_balance,
                "started_at": datetime.utcnow().isoformat()
            }
            with open(self._state_file, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.warning(f"Не вдалося зберегти стан: {e}")
    
    async def start(self):
        self._running = True
        self._start_time = datetime.utcnow()
        if not os.path.exists(self._state_file):
            self._save_state()
        
        await telegram.send_message(
            f"🔲 Grid Trading Started\n"
            f"Symbols: {', '.join(self.symbols)}\n"
            f"Balance: ${self.balance:.2f}\n"
            f"Realized PnL: ${self.realized_pnl:.2f}\n"
            f"Investment per symbol: ${self.balance/len(self.symbols):.2f}"
        )
        
        logger.info(f"Grid paper trading started for {self.symbols}")
        
        tasks = [self._trading_loop(symbol) for symbol in self.symbols]
        tasks.append(self._status_reporter())
        
        await asyncio.gather(*tasks)
    
    async def stop(self):
        self._running = False
        await self._send_final_report()
        logger.info("Grid paper trading stopped")
    
    async def _fetch_market_data(self, symbol: str, limit: int = 200):
        import yfinance as yf
        import pandas as pd
        
        try:
            yf_symbol = settings.get_symbol_for_pybroker(symbol)
            ticker = yf.Ticker(yf_symbol)
            data = ticker.history(period="7d", interval="1h")
            
            if data is None or not isinstance(data, pd.DataFrame) or data.empty:
                logger.warning(f"No data returned from yfinance for {symbol} ({yf_symbol})")
                return pd.DataFrame()
            
            data = data.reset_index()
            data.columns = [c.lower() for c in data.columns]
            if 'datetime' in data.columns:
                data = data.rename(columns={'datetime': 'timestamp'})
            elif 'date' in data.columns:
                data = data.rename(columns={'date': 'timestamp'})
            
            data['symbol'] = symbol
            return data.tail(limit)
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            import pandas as pd
            return pd.DataFrame()
    
    async def _trading_loop(self, symbol: str):
        logger.info(f"Starting grid trading loop for {symbol}")
        strategy = self.strategies[symbol]
        investment_per_symbol = self.initial_balance / len(self.symbols)
        
        while self._running:
            try:
                if self._trading_paused:
                    if datetime.utcnow() < self._pause_until:
                        await asyncio.sleep(60)
                        continue
                    else:
                        self._trading_paused = False
                        logger.info("Trading resumed")
                        await telegram.send_message("✅ Trading resumed")
                
                data = await self._fetch_market_data(symbol)
                
                if data.empty:
                    await asyncio.sleep(30)
                    continue
                
                data = TechnicalIndicators.add_all_indicators(data)
                current_price = data['close'].iloc[-1]
                atr = data['atr'].iloc[-1] if 'atr' in data.columns else current_price * 0.02
                
                if not strategy.initialized:
                    strategy.initialize_grid(current_price, atr, investment_per_symbol, data)
                    strategy.last_rebalance_time = datetime.utcnow()
                    await self._send_grid_init_message(symbol, strategy)
                
                action = await self.check_portfolio_health()
                
                if action == "stop_loss":
                    await self.close_all_positions("Portfolio stop loss triggered (-5%)")
                    break
                elif action == "take_profit":
                    await self.close_all_positions("Portfolio take profit reached (+10%)")
                    break
                elif action == "partial_profit":
                    await self.close_partial_positions(settings.grid.partial_close_ratio)
                elif action == "rebalance_warning":
                    logger.warning(f"{symbol}: Unrealized loss > -3%, monitoring closely")
                
                fills = strategy.check_grid_fills(current_price)
                
                for fill in fills:
                    await self._process_fill(symbol, fill, current_price)
                
                should_rebalance, reason = strategy.should_rebalance_hybrid(current_price)
                
                if should_rebalance:
                    await self._execute_rebalance(symbol, strategy, current_price, atr, reason, data)
                
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in grid loop for {symbol}: {e}")
                await asyncio.sleep(60)
    
    async def _execute_rebalance(
        self,
        symbol: str,
        strategy: GridStrategy,
        current_price: float,
        atr: float,
        reason: str,
        data: Optional[pd.DataFrame] = None
    ):
        old_config = strategy.config
        unrealized_pnl = strategy.calculate_unrealized_pnl(current_price)
        open_positions = len(self.positions[symbol])
        
        can_rebalance, profit_msg = strategy.can_rebalance_positions_profitable(current_price)
        
        strategy.rebalance(current_price, atr, reason, data)
        
        self._save_rebalance_event({
            'timestamp': datetime.utcnow().isoformat(),
            'symbol': symbol,
            'reason': reason,
            'old_range': f"${old_config.lower_price:.2f}-${old_config.upper_price:.2f}",
            'new_range': f"${strategy.config.lower_price:.2f}-${strategy.config.upper_price:.2f}",
            'open_positions': open_positions,
            'unrealized_pnl': unrealized_pnl,
            'positions_profitable': can_rebalance,
            'forced': not can_rebalance
        })
        
        await telegram.grid_rebalance_alert(
            symbol=symbol,
            reason=reason,
            old_range=f"${old_config.lower_price:.2f}-${old_config.upper_price:.2f}",
            new_range=f"${strategy.config.lower_price:.2f}-${strategy.config.upper_price:.2f}",
            open_positions=open_positions,
            unrealized_pnl=unrealized_pnl
        )
        
        logger.warning(f"✅ Rebalanced {symbol}: {profit_msg}")
    
    def _calculate_total_unrealized(self) -> float:
        total = 0.0
        for symbol, positions in self.positions.items():
            if not positions:
                continue
            strategy = self.strategies.get(symbol)
            if not strategy or not strategy.grid_levels:
                continue
            avg_price = sum(level.price for level in strategy.grid_levels if level.filled) / max(1, sum(1 for level in strategy.grid_levels if level.filled))
            for pos in positions:
                total += (avg_price - pos.entry_price) * pos.amount
        return total

    def _calculate_total_cost_basis(self) -> float:
        total = 0.0
        for positions in self.positions.values():
            for pos in positions:
                total += pos.entry_price * pos.amount
        return total
    
    async def check_portfolio_health(self) -> Optional[str]:
        if not settings.grid.enable_portfolio_protection:
            return None
        
        total_unrealized = self._calculate_total_unrealized()
        total_cost_basis = self._calculate_total_cost_basis()
        total_value = self.balance + total_cost_basis + total_unrealized
        unrealized_pnl_pct = ((total_value - self.initial_balance) / self.initial_balance) * 100
        
        if unrealized_pnl_pct <= -settings.grid.portfolio_stop_loss_percent:
            return "stop_loss"
        
        if unrealized_pnl_pct >= settings.grid.portfolio_take_profit_percent:
            return "take_profit"
        
        if unrealized_pnl_pct >= settings.grid.partial_close_profit_percent:
            return "partial_profit"
        
        if unrealized_pnl_pct <= -settings.grid.max_unrealized_loss_percent:
            return "rebalance_warning"
        
        return None
    
    async def close_all_positions(self, reason: str):
        logger.warning(f"🚨 CLOSING ALL POSITIONS: {reason}")
        
        closed_count = 0
        total_realized = 0.0
        
        for symbol in self.symbols:
            positions = self.positions[symbol]
            if not positions:
                continue
            
            data = await self._fetch_market_data(symbol)
            if data.empty:
                continue
            current_price = data['close'].iloc[-1]
            
            for position in positions:
                profit = (current_price - position.entry_price) * position.amount
                self.balance += position.entry_price * position.amount + profit
                self.realized_pnl += profit
                total_realized += profit
                closed_count += 1
            
            self.positions[symbol] = []
            
            strategy = self.strategies[symbol]
            for level in strategy.grid_levels:
                level.filled = False
                level.filled_at = None
        
        msg = (
            f"🚨 Portfolio Protection Activated\n"
            f"Reason: {reason}\n"
            f"Closed {closed_count} positions\n"
            f"Realized P&L: ${total_realized:.2f}\n"
            f"New Balance: ${self.balance:.2f}"
        )
        await telegram.send_message(msg)
        
        if "stop_loss" in reason.lower():
            self._trading_paused = True
            self._pause_until = datetime.utcnow() + timedelta(hours=settings.grid.pause_after_stop_loss_hours)
            logger.warning(f"Trading paused until {self._pause_until}")
    
    async def close_partial_positions(self, ratio: float = 0.5):
        logger.info(f"💰 Taking partial profits: closing {ratio:.0%} of positions")
        
        closed_count = 0
        total_profit = 0.0
        
        for symbol in self.symbols:
            positions = self.positions[symbol]
            if not positions:
                continue
            
            data = await self._fetch_market_data(symbol)
            if data.empty:
                continue
            current_price = data['close'].iloc[-1]
            
            profitable_positions = [
                p for p in positions 
                if (current_price - p.entry_price) > 0
            ]
            
            num_to_close = int(len(profitable_positions) * ratio)
            positions_to_close = profitable_positions[:num_to_close]
            
            for position in positions_to_close:
                profit = (current_price - position.entry_price) * position.amount
                self.balance += position.entry_price * position.amount + profit
                self.realized_pnl += profit
                total_profit += profit
                closed_count += 1
                
                self.positions[symbol].remove(position)
                
                strategy = self.strategies[symbol]
                for level in strategy.grid_levels:
                    if level.filled and abs(level.price - position.entry_price) < 0.01:
                        level.filled = False
                        level.filled_at = None
                        break
        
        if closed_count > 0:
            msg = (
                f"💰 Partial Profit Taking\n"
                f"Closed {closed_count} positions ({ratio:.0%})\n"
                f"Profit: ${total_profit:.2f}\n"
                f"Balance: ${self.balance:.2f}"
            )
            await telegram.send_message(msg)
    
    async def _send_grid_init_message(self, symbol: str, strategy: GridStrategy):
        status = strategy.get_status()
        msg = (
            f"🔲 Grid Initialized: {symbol}\n"
            f"Range: {status['range']}\n"
            f"Center: {status['center']}\n"
            f"Spacing: {status['grid_spacing']}\n"
            f"Active levels: {status['active_levels']}"
        )
        await telegram.send_message(msg)
    
    async def _process_fill(self, symbol: str, fill: Dict, current_price: float):
        self.total_trades += 1
        
        if fill['side'] == 'buy':
            self.balance -= fill['value']
            self.positions[symbol].append(GridPosition(
                symbol=symbol,
                side='long',
                entry_price=fill['price'],
                amount=fill['amount'],
                opened_at=datetime.utcnow()
            ))
            emoji = "🟢"
            action = "BUY"
        else:
            self.balance += fill['value']
            profit = 0.0
            if self.positions[symbol]:
                pos = self.positions[symbol].pop(0)
                profit = (fill['price'] - pos.entry_price) * pos.amount
                self.realized_pnl += profit
                if profit > 0:
                    self.winning_trades += 1
            emoji = "🔴"
            action = "SELL"
        
        total_unrealized = self._calculate_total_unrealized()
        total_cost_basis = self._calculate_total_cost_basis()
        total_value = self.balance + total_cost_basis + total_unrealized
        roi_percent = ((total_value - self.initial_balance) / self.initial_balance) * 100
        
        health_emoji = "✅" if roi_percent >= 0 else "⚠️" if roi_percent >= -2 else "🚨"
        
        trade_record = TradeRecord(
            timestamp=datetime.utcnow().isoformat(),
            symbol=symbol,
            side=action,
            price=fill['price'],
            amount=fill['amount'],
            value=fill['value'],
            realized_pnl=self.realized_pnl,
            unrealized_pnl=total_unrealized,
            balance=self.balance,
            total_value=total_value,
            roi_percent=roi_percent
        )
        self._save_trade(trade_record)
        
        msg = (
            f"{emoji} Grid {action}: {symbol}\n"
            f"Price: ${fill['price']:.2f}\n"
            f"Amount: {fill['amount']:.4f}\n"
            f"Value: ${fill['value']:.2f}\n"
        )
        
        if fill['side'] == 'sell' and 'profit' in locals():
            profit_emoji = "✅" if profit > 0 else "❌"
            msg += f"{profit_emoji} Profit: ${profit:.2f}\n"
        
        msg += (
            f"\n{health_emoji} Portfolio:\n"
            f"ROI: {roi_percent:+.2f}%\n"
            f"Balance: ${self.balance:.2f}\n"
            f"Total Value: ${total_value:.2f}"
        )
        
        await telegram.send_message(msg)
        logger.info(f"Grid {action} {symbol} at ${fill['price']:.2f}, Portfolio ROI: {roi_percent:+.2f}%")
    
    async def _status_reporter(self):
        self._last_12h_report = datetime.utcnow()
        self._last_24h_report = datetime.utcnow()
        
        while self._running:
            await asyncio.sleep(300)
            
            now = datetime.utcnow()
            
            if now - self._last_12h_report >= timedelta(hours=12):
                await self._send_scheduled_report("12h")
                self._last_12h_report = now
            
            if now - self._last_24h_report >= timedelta(hours=24):
                await self._send_scheduled_report("24h")
                self._last_24h_report = now
    
    async def _send_scheduled_report(self, report_type: str):
        total_unrealized = 0.0
        grid_status = []
        prices = {}
        
        for symbol, strategy in self.strategies.items():
            if strategy.initialized:
                data = await self._fetch_market_data(symbol)
                if not data.empty:
                    current_price = data['close'].iloc[-1]
                    prices[symbol] = current_price
                    unrealized = strategy.calculate_unrealized_pnl(current_price)
                    total_unrealized += unrealized
                    status = strategy.get_status()
                    grid_status.append(
                        f"  {symbol}: {status['active_levels']} levels, ${unrealized:.2f}"
                    )
        
        total_pnl = self.realized_pnl + total_unrealized
        total_cost_basis = self._calculate_total_cost_basis()
        total_value = self.balance + total_cost_basis + total_unrealized
        roi = ((total_value - self.initial_balance) / self.initial_balance) * 100
        runtime = datetime.utcnow() - self._start_time
        hours = runtime.total_seconds() / 3600
        sell_trades = sum(1 for sym in self.symbols for pos in self.positions.get(sym, []))
        completed_pairs = self.total_trades - sell_trades
        win_rate = (self.winning_trades / max(1, completed_pairs)) * 100 if completed_pairs > 0 else 0
        
        snapshot_data = {
            'balance': self.balance,
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': total_unrealized,
            'total_value': total_value,
            'roi_percent': roi,
            'total_trades': self.total_trades,
            'win_rate': win_rate,
            'btc_price': prices.get('BTC/USDT', 0),
            'eth_price': prices.get('ETH/USDT', 0)
        }
        self._save_snapshot(snapshot_data, report_type)
        
        emoji = "📊" if report_type == "12h" else "📈"
        period = "12 Hour" if report_type == "12h" else "24 Hour"
        
        msg = (
            f"{emoji} Grid {period} Report\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏱ Runtime: {hours:.1f}h\n"
            f"💰 Initial: ${self.initial_balance:.2f}\n"
            f"💵 Current: ${total_value:.2f}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📈 Realized PnL: ${self.realized_pnl:.2f}\n"
            f"📊 Unrealized: ${total_unrealized:.2f}\n"
            f"💹 Total PnL: ${total_pnl:.2f}\n"
            f"📉 ROI: {roi:+.2f}%\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🔄 Trades: {self.total_trades}\n"
            f"🎯 Win Rate: {win_rate:.1f}%\n"
            f"━━━━━━━━━━━━━━━━\n"
            + "\n".join(grid_status)
        )
        await telegram.send_message(msg)
        logger.info(f"Sent {report_type} scheduled report")
    
    async def _send_status_report(self):
        total_unrealized = 0.0
        grid_status = []
        prices = {}
        
        for symbol, strategy in self.strategies.items():
            if strategy.initialized:
                data = await self._fetch_market_data(symbol)
                if not data.empty:
                    current_price = data['close'].iloc[-1]
                    prices[symbol] = current_price
                    unrealized = strategy.calculate_unrealized_pnl(current_price)
                    total_unrealized += unrealized
                    status = strategy.get_status()
                    grid_status.append(
                        f"  {symbol}: {status['active_levels']} active, "
                        f"${unrealized:.2f} unrealized"
                    )
        
        total_pnl = self.realized_pnl + total_unrealized
        total_value = self.initial_balance + total_pnl
        roi = ((total_value - self.initial_balance) / self.initial_balance) * 100
        runtime = datetime.utcnow() - self._start_time
        hours = runtime.total_seconds() / 3600
        open_positions = sum(len(positions) for positions in self.positions.values())
        completed_pairs = (self.total_trades - open_positions) // 2
        win_rate = (self.winning_trades / max(1, completed_pairs)) * 100 if completed_pairs > 0 else 0
        
        snapshot_data = {
            'balance': self.initial_balance,
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': total_unrealized,
            'total_value': total_value,
            'roi_percent': roi,
            'total_trades': self.total_trades,
            'win_rate': win_rate,
            'btc_price': prices.get('BTC/USDT', 0),
            'eth_price': prices.get('ETH/USDT', 0)
        }
        self._save_snapshot(snapshot_data, "status")
        
        msg = (
            f"📊 Grid Status Report\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏱ Runtime: {hours:.1f}h\n"
            f"💰 Initial: ${self.initial_balance:.2f}\n"
            f"📈 Realized PnL: ${self.realized_pnl:.2f}\n"
            f"📊 Unrealized PnL: ${total_unrealized:.2f}\n"
            f"💵 Total Value: ${total_value:.2f}\n"
            f"📉 ROI: {roi:+.2f}%\n"
            f"🔄 Trades: {self.total_trades}\n"
            f"🎯 Win Rate: {win_rate:.1f}%\n"
            f"━━━━━━━━━━━━━━━━\n"
            + "\n".join(grid_status)
        )
        await telegram.send_message(msg)
    
    async def _send_final_report(self):
        total_unrealized = 0.0
        for symbol, strategy in self.strategies.items():
            if strategy.initialized:
                data = await self._fetch_market_data(symbol)
                if not data.empty:
                    current_price = data['close'].iloc[-1]
                    total_unrealized += strategy.calculate_unrealized_pnl(current_price)
        
        total_pnl = self.realized_pnl + total_unrealized
        total_value = self.initial_balance + total_pnl
        roi = ((total_value - self.initial_balance) / self.initial_balance) * 100
        runtime = datetime.utcnow() - self._start_time
        
        msg = (
            f"🏁 Grid Trading Final Report\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏱ Total Runtime: {runtime}\n"
            f"💰 Initial: ${self.initial_balance:.2f}\n"
            f"💵 Final Value: ${total_value:.2f}\n"
            f"📈 Total PnL: ${total_value - self.initial_balance:.2f}\n"
            f"📉 ROI: {roi:+.2f}%\n"
            f"🔄 Total Trades: {self.total_trades}"
        )
        await telegram.send_message(msg)
    
    def get_stats(self) -> Dict:
        total_unrealized = sum(
            strategy.calculate_unrealized_pnl(0) 
            for strategy in self.strategies.values() 
            if strategy.initialized
        )
        return {
            "initial_balance": self.initial_balance,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": total_unrealized,
            "total_value": self.initial_balance + self.realized_pnl + total_unrealized,
            "total_trades": self.total_trades,
            "positions": sum(len(p) for p in self.positions.values()),
            "winning_trades": self.winning_trades
        }
