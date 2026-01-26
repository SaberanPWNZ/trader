import asyncio
from datetime import datetime, timedelta
from typing import Dict, List
from dataclasses import dataclass
from loguru import logger

from strategies.grid import GridStrategy
from strategies.indicators import TechnicalIndicators
from monitoring.alerts import telegram
from config.settings import settings


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
        
        for symbol in symbols:
            self.strategies[symbol] = GridStrategy(symbol)
    
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
                    await asyncio.sleep(60)
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
                
                await asyncio.sleep(300)
                
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
        
        strategy = self.strategies[symbol]
        unrealized = strategy.calculate_unrealized_pnl(current_price)
        
        msg = (
            f"{emoji} Grid {action}: {symbol}\n"
            f"Price: ${fill['price']:.2f}\n"
            f"Value: ${fill['value']:.2f}\n"
            f"Realized: ${self.realized_pnl:.2f}\n"
            f"Unrealized: ${unrealized:.2f}\n"
            f"Balance: ${self.balance:.2f}"
        )
        await telegram.send_message(msg)
        logger.info(f"Grid {action} {symbol} at ${fill['price']:.2f}, PnL: ${self.realized_pnl:.2f}")
    
    async def _status_reporter(self):
        last_report = datetime.utcnow()
        report_interval = timedelta(hours=4)
        
        while self._running:
            await asyncio.sleep(60)
            
            if datetime.utcnow() - last_report >= report_interval:
                await self._send_status_report()
                last_report = datetime.utcnow()
    
    async def _send_status_report(self):
        total_unrealized = 0.0
        grid_status = []
        
        for symbol, strategy in self.strategies.items():
            if strategy.initialized:
                data = await self._fetch_market_data(symbol)
                if not data.empty:
                    current_price = data['close'].iloc[-1]
                    unrealized = strategy.calculate_unrealized_pnl(current_price)
                    total_unrealized += unrealized
                    status = strategy.get_status()
                    grid_status.append(
                        f"  {symbol}: {status['active_levels']} active, "
                        f"${unrealized:.2f} unrealized"
                    )
        
        total_pnl = self.realized_pnl + total_unrealized
        total_value = self.balance + total_unrealized
        roi = ((total_value - self.initial_balance) / self.initial_balance) * 100
        runtime = datetime.utcnow() - self._start_time
        hours = runtime.total_seconds() / 3600
        win_rate = (self.winning_trades / max(1, self.total_trades // 2)) * 100
        
        msg = (
            f"📊 Grid Status Report\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"⏱ Runtime: {hours:.1f}h\n"
            f"💰 Balance: ${self.balance:.2f}\n"
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
        
        total_value = self.balance + total_unrealized
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
        return {
            "balance": self.balance,
            "realized_pnl": self.realized_pnl,
            "total_trades": self.total_trades,
            "positions": sum(len(p) for p in self.positions.values()),
            "winning_trades": self.winning_trades
        }
