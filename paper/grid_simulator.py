import asyncio
import csv
import os
from datetime import datetime, timedelta
from typing import Dict, List
from dataclasses import dataclass, asdict
from loguru import logger

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
        self.balance = initial_balance
        self.strategies: Dict[str, GridStrategy] = {}
        self.positions: Dict[str, List[GridPosition]] = {s: [] for s in symbols}
        self.realized_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self._running = False
        self._start_time = None
        self._last_12h_report = None
        self._last_24h_report = None
        self._trades_file = "data/grid_trades.csv"
        self._snapshots_file = "data/grid_snapshots.csv"
        self._init_data_files()
        
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
    
    async def start(self):
        self._running = True
        self._start_time = datetime.utcnow()
        
        await telegram.send_message(
            f"🔲 Grid Trading Started\n"
            f"Symbols: {', '.join(self.symbols)}\n"
            f"Balance: ${self.initial_balance:.2f}\n"
            f"Investment per symbol: ${self.initial_balance/len(self.symbols):.2f}"
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
            
            if data is None or data.empty:
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
                data = await self._fetch_market_data(symbol)
                
                if data.empty:
                    await asyncio.sleep(30)
                    continue
                
                data = TechnicalIndicators.add_all_indicators(data)
                current_price = data['close'].iloc[-1]
                atr = data['atr'].iloc[-1] if 'atr' in data.columns else current_price * 0.02
                
                if not strategy.initialized:
                    strategy.initialize_grid(current_price, atr, investment_per_symbol)
                    await self._send_grid_init_message(symbol, strategy)
                
                fills = strategy.check_grid_fills(current_price)
                
                for fill in fills:
                    await self._process_fill(symbol, fill, current_price)
                
                if strategy.should_rebalance(current_price):
                    logger.warning(f"{symbol} price ${current_price:.2f} out of grid range, waiting...")
                
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in grid loop for {symbol}: {e}")
                await asyncio.sleep(60)
    
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
            profit = 0.0
            if self.positions[symbol]:
                pos = self.positions[symbol].pop(0)
                profit = (fill['price'] - pos.entry_price) * pos.amount
                self.realized_pnl += profit
                if profit > 0:
                    self.winning_trades += 1
            emoji = "🔴"
            action = "SELL"
        
        total_unrealized = 0.0
        for sym, strategy in self.strategies.items():
            if strategy.initialized:
                data = await self._fetch_market_data(sym)
                if not data.empty:
                    price = data['close'].iloc[-1]
                    total_unrealized += strategy.calculate_unrealized_pnl(price)
        
        total_value = self.initial_balance + self.realized_pnl + total_unrealized
        roi = ((total_value - self.initial_balance) / self.initial_balance) * 100
        
        trade_record = TradeRecord(
            timestamp=datetime.utcnow().isoformat(),
            symbol=symbol,
            side=action,
            price=fill['price'],
            amount=fill['amount'],
            value=fill['value'],
            realized_pnl=self.realized_pnl,
            unrealized_pnl=total_unrealized,
            balance=self.initial_balance,
            total_value=total_value,
            roi_percent=roi
        )
        self._save_trade(trade_record)
        
        msg = (
            f"{emoji} Grid {action}: {symbol}\n"
            f"Price: ${fill['price']:.2f}\n"
            f"Value: ${fill['value']:.2f}\n"
            f"Realized: ${self.realized_pnl:.2f}\n"
            f"Unrealized: ${total_unrealized:.2f}\n"
            f"Total: ${total_value:.2f}"
        )
        await telegram.send_message(msg)
        logger.info(f"Grid {action} {symbol} at ${fill['price']:.2f}, PnL: ${self.realized_pnl:.2f}")
    
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
        total_value = self.balance + total_unrealized
        roi = ((total_value - self.initial_balance) / self.initial_balance) * 100
        runtime = datetime.utcnow() - self._start_time
        hours = runtime.total_seconds() / 3600
        win_rate = (self.winning_trades / max(1, self.total_trades // 2)) * 100
        
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
        win_rate = (self.winning_trades / max(1, self.total_trades // 2)) * 100
        
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
