import asyncio
from datetime import datetime
from typing import Optional, Callable, Dict, Any
import aiohttp
import os
import csv
import json
from loguru import logger

from config.settings import settings
from learning.database import LearningDatabase


class LearningTelegramBot:
    def __init__(
        self,
        db: Optional[LearningDatabase] = None,
        on_train_command: Optional[Callable] = None
    ):
        self.token = settings.monitoring.telegram_token
        self.chat_id = settings.monitoring.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.db = db or LearningDatabase()
        self.on_train_command = on_train_command
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._last_update_id = 0
        self._commands = {
            "/start": self._cmd_start,
            "/help": self._cmd_help,
            "/status": self._cmd_status,
            "/models": self._cmd_models,
            "/performance": self._cmd_performance,
            "/train": self._cmd_train,
            "/lastrun": self._cmd_lastrun,
            "/deploy": self._cmd_deploy,
            "/balance": self._cmd_balance,
            "/grid": self._cmd_grid,
            "/trades": self._cmd_trades,
            "/profit": self._cmd_profit,
            "/daily": self._cmd_daily,
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def start(self) -> None:
        if not settings.monitoring.telegram_commands_enabled:
            logger.warning("Telegram commands not enabled in settings")
            return

        await self.db.initialize()
        self._running = True
        logger.info("Telegram bot started, listening for commands...")
        await self._polling_loop()

    async def stop(self) -> None:
        self._running = False
        await self.close()

    async def _polling_loop(self) -> None:
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._handle_update(update)
                    self._last_update_id = update.get("update_id", 0) + 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
            await asyncio.sleep(settings.monitoring.telegram_polling_interval)

    async def _get_updates(self) -> list:
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/getUpdates",
                params={"offset": self._last_update_id, "timeout": 30}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("result", [])
        except Exception as e:
            logger.error(f"Failed to get updates: {e}")
        return []

    async def _handle_update(self, update: dict) -> None:
        message = update.get("message", {})
        text = message.get("text", "")
        chat_id = message.get("chat", {}).get("id")
        chat_type = message.get("chat", {}).get("type")  # 'private', 'group', 'supergroup'

        if not text or not chat_id:
            return

        # Only accept commands from the configured chat or private messages
        if str(chat_id) != str(self.chat_id):
            if chat_type != "private":
                logger.debug(f"Ignoring message from unauthorized chat: {chat_id} (type: {chat_type})")
                return

        parts = text.strip().split()
        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if command in self._commands:
            try:
                await self._commands[command](args)
            except Exception as e:
                logger.error(f"Command error: {e}")
                await self._send_message(f"❌ Error: {e}")

    async def _send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode}
            ) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    async def _cmd_start(self, args: list) -> None:
        await self._send_message("""
🤖 <b>Trading Bot System</b>

<b>Grid Trading:</b>
/balance - Portfolio balance & ROI
/profit [hours] - Profit in last N hours (default 5)
/daily - Daily profit report by dates
/grid - Grid ranges & prices
/trades [N] - Last N trades (default 10)

<b>AI Models:</b>
/status - System status
/models - List trained models
/performance - Performance stats
/train &lt;symbol&gt; - Force training
/lastrun - Last training details
/deploy &lt;model_id&gt; - Deploy model

/help - Show this help
""")

    async def _cmd_help(self, args: list) -> None:
        await self._cmd_start(args)

    async def _cmd_status(self, args: list) -> None:
        symbols = settings.trading.symbols
        status_lines = ["📊 <b>System Status</b>\n"]

        for symbol in symbols:
            deployed = await self.db.get_deployed_model(symbol)
            if deployed:
                status_lines.append(
                    f"<b>{symbol}:</b> Model {deployed['id'][:8]} "
                    f"({deployed['test_accuracy']:.1%})"
                )
            else:
                status_lines.append(f"<b>{symbol}:</b> No model deployed")

        status_lines.append(f"\n<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>")
        await self._send_message("\n".join(status_lines))

    async def _cmd_models(self, args: list) -> None:
        symbol = args[0] if args else None
        models = await self.db.get_models(symbol, limit=5)

        if not models:
            await self._send_message("No models found")
            return

        lines = ["📦 <b>Trained Models</b>\n"]
        for m in models:
            deployed = "✅" if m["is_deployed"] else ""
            lines.append(
                f"<code>{m['id'][:8]}</code> {m['symbol']} "
                f"Acc: {m['test_accuracy']:.1%} {deployed}"
            )

        await self._send_message("\n".join(lines))

    async def _cmd_performance(self, args: list) -> None:
        days = int(args[0]) if args else 30
        summary = await self.db.get_performance_summary(days)

        if not summary:
            await self._send_message(f"No training data in last {days} days")
            return

        lines = [f"📈 <b>Performance ({days}d)</b>\n"]
        for symbol, stats in summary.items():
            lines.append(
                f"<b>{symbol}:</b>\n"
                f"  Runs: {stats['total_runs']}\n"
                f"  Avg Accuracy: {stats['avg_accuracy']:.1%}\n"
                f"  Best: {stats['best_accuracy']:.1%}"
            )

        await self._send_message("\n".join(lines))

    async def _cmd_train(self, args: list) -> None:
        if not args:
            await self._send_message("Usage: /train <symbol>\nExample: /train BTC/USDT")
            return

        symbol = args[0].upper()
        if "/" not in symbol:
            symbol = f"{symbol}/USDT"

        if self.on_train_command:
            await self._send_message(f"🔄 Starting training for {symbol}...")
            try:
                result = await self.on_train_command(symbol)
                if result.get("status") == "success":
                    await self._send_message(
                        f"✅ Training complete!\n"
                        f"Accuracy: {result['test_accuracy']:.1%}\n"
                        f"Model ID: <code>{result['model_id']}</code>"
                    )
                else:
                    await self._send_message(f"❌ Training failed: {result.get('error', 'Unknown')}")
            except Exception as e:
                await self._send_message(f"❌ Error: {e}")
        else:
            await self._send_message("⚠️ Training handler not configured")

    async def _cmd_lastrun(self, args: list) -> None:
        symbol = args[0].upper() if args else None
        if symbol and "/" not in symbol:
            symbol = f"{symbol}/USDT"

        runs = await self.db.get_training_runs(symbol, limit=1)
        if not runs:
            await self._send_message("No training runs found")
            return

        run = runs[0]
        status_emoji = "✅" if run["status"] == "success" else "❌"
        
        message = f"""
{status_emoji} <b>Last Training Run</b>

<b>Symbol:</b> {run['symbol']}
<b>Time:</b> {run['timestamp']}
<b>Status:</b> {run['status']}
<b>Samples:</b> {run['samples']:,}
<b>Train Acc:</b> {run['train_accuracy']:.1%}
<b>Test Acc:</b> {run['test_accuracy']:.1%}
<b>Improvement:</b> {run['improvement']:.1%}
<b>Duration:</b> {run['duration_seconds']:.1f}s
"""
        await self._send_message(message)

    async def _cmd_deploy(self, args: list) -> None:
        if len(args) < 2:
            await self._send_message("Usage: /deploy <model_id> <symbol>")
            return

        model_id = args[0]
        symbol = args[1].upper()
        if "/" not in symbol:
            symbol = f"{symbol}/USDT"

        try:
            await self.db.deploy_model(model_id, symbol)
            await self._send_message(f"🚀 Model {model_id} deployed for {symbol}")
        except Exception as e:
            await self._send_message(f"❌ Deploy failed: {e}")

    def _read_initial_balance(self) -> float:
        state_file = "data/grid_state.json"
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                state = json.load(f)
                if isinstance(state, dict) and "initial_balance" in state:
                    return float(state["initial_balance"])
        return 2000.0

    def _count_open_positions(self, trades: list) -> dict:
        positions = {}
        for trade in trades:
            symbol = trade['symbol']
            if trade['side'] == 'BUY':
                if symbol not in positions:
                    positions[symbol] = []
                positions[symbol].append(float(trade['value']))
            elif trade['side'] == 'SELL':
                if symbol in positions and positions[symbol]:
                    positions[symbol].pop(0)
        return {s: sum(vals) for s, vals in positions.items() if vals}

    async def _cmd_balance(self, args: list) -> None:
        trades_file = "data/grid_trades.csv"
        initial_balance = self._read_initial_balance()
        
        if not os.path.exists(trades_file):
            await self._send_message("❌ No trading data found")
            return
        
        try:
            with open(trades_file, 'r') as f:
                reader = csv.DictReader(f)
                trades = list(reader)
            
            if not trades:
                lines = [
                    "💰 <b>Portfolio Balance</b>",
                    "",
                    f"💎 <b>Total Value:</b> ${initial_balance:,.2f}",
                    f"   └ 💵 Cash: ${initial_balance:,.2f}",
                    "",
                    "✅ <b>Performance:</b>",
                    f"   Initial: ${initial_balance:,.2f}",
                    f"   Profit: $0.00",
                    f"   ROI: 0.00%",
                    "",
                    "<b>📊 PnL Breakdown:</b>",
                    "   ├ Realized: $0.00",
                    "   └ Unrealized: $0.00",
                    "",
                    "<b>📈 Activity:</b> 0 trades (0↗ 0↘)",
                    "",
                    "<i>Waiting for first trade...</i>"
                ]
                await self._send_message("\n".join(lines))
                return
            
            last_trade = trades[-1]
            balance = float(last_trade['balance'])
            total_value = float(last_trade['total_value'])
            realized_pnl = float(last_trade['realized_pnl'])
            unrealized_pnl = float(last_trade['unrealized_pnl'])
            roi_percent = float(last_trade['roi_percent'])
            
            positions = self._count_open_positions(trades)
            total_invested = sum(positions.values())
            
            roi_emoji = "✅" if roi_percent >= 0 else "⚠️" if roi_percent >= -2 else "🚨"
            
            total_trades = len(trades)
            buy_trades = sum(1 for t in trades if t['side'] == 'BUY')
            sell_trades = sum(1 for t in trades if t['side'] == 'SELL')
            
            lines = [
                "💰 <b>Portfolio Balance</b>",
                "",
                f"💎 <b>Total Value:</b> ${total_value:,.2f}",
                f"   ├ 💵 Cash: ${balance:,.2f}",
                f"   └ 📦 Positions: ${total_invested:,.2f}",
                "",
                f"{roi_emoji} <b>Performance:</b>",
                f"   Initial: ${initial_balance:,.2f}",
                f"   Profit: ${total_value - initial_balance:+,.2f}",
                f"   ROI: {roi_percent:+.2f}%",
                "",
                "<b>📊 PnL Breakdown:</b>",
                f"   ├ Realized: ${realized_pnl:+,.2f}",
                f"   └ Unrealized: ${unrealized_pnl:+,.2f}",
            ]
            
            if positions:
                lines.append("")
                lines.append("<b>📦 Open Positions:</b>")
                for symbol, cost in sorted(positions.items()):
                    symbol_short = symbol.split('/')[0]
                    count = sum(1 for t in trades if t['symbol'] == symbol and t['side'] == 'BUY') - sum(1 for t in trades if t['symbol'] == symbol and t['side'] == 'SELL')
                    lines.append(f"   • <b>{symbol_short}</b>: ${cost:,.2f} ({count} pos)")
            
            lines.append("")
            lines.append(f"<b>📈 Activity:</b> {total_trades} trades ({buy_trades}↗ {sell_trades}↘)")
            lines.append("")
            lines.append(f"<i>{last_trade['timestamp'][:19]} UTC</i>")
            
            await self._send_message("\n".join(lines))
            
        except Exception as e:
            logger.error(f"Balance command error: {e}")
            await self._send_message(f"❌ Error reading balance: {e}")

    async def _cmd_grid(self, args: list) -> None:
        import yfinance as yf
        
        trades_file = "data/grid_trades.csv"
        
        symbols_map = {
            'BTC/USDT': 'BTC-USD',
            'ETH/USDT': 'ETH-USD',
            'SOL/USDT': 'SOL-USD',
            'DOGE/USDT': 'DOGE-USD'
        }
        
        positions = {}
        if os.path.exists(trades_file):
            with open(trades_file, 'r') as f:
                reader = csv.DictReader(f)
                trades = list(reader)
            positions = self._count_open_positions(trades)
        
        lines = ["📊 <b>Grid Trading Status</b>\n"]
        
        for symbol, yf_symbol in symbols_map.items():
            try:
                ticker = yf.Ticker(yf_symbol)
                data = ticker.history(period='1d', interval='1m')
                if not data.empty:
                    price = data['Close'].iloc[-1]
                    sym = symbol.split('/')[0]
                    pos_cost = positions.get(symbol, 0)
                    pos_count = 0
                    if os.path.exists(trades_file):
                        pos_count = sum(1 for t in trades if t['symbol'] == symbol and t['side'] == 'BUY') - sum(1 for t in trades if t['symbol'] == symbol and t['side'] == 'SELL')
                    
                    lines.append(f"<b>{sym}</b>")
                    lines.append(f"├ Price: ${price:,.2f}")
                    if pos_count > 0:
                        lines.append(f"├ Positions: {pos_count} (${pos_cost:,.2f})")
                    else:
                        lines.append(f"├ Positions: none")
                    lines.append(f"└ Status: {'🟢 Active' if pos_count > 0 else '⚪ Waiting'}\n")
            except Exception as e:
                lines.append(f"<b>{symbol}</b>: ❌ Error: {e}\n")
        
        await self._send_message("\n".join(lines))

    async def _cmd_trades(self, args: list) -> None:
        limit = int(args[0]) if args and args[0].isdigit() else 10
        trades_file = "data/grid_trades.csv"
        
        if not os.path.exists(trades_file):
            await self._send_message("❌ No trading data found")
            return
        
        try:
            with open(trades_file, 'r') as f:
                reader = csv.DictReader(f)
                trades = list(reader)[-limit:]
            
            if not trades:
                await self._send_message("❌ No trades yet")
                return
            
            lines = [f"📈 <b>Last {len(trades)} Trades</b>\n"]
            
            for trade in trades:
                side_emoji = "🟢" if trade['side'] == 'BUY' else "🔴"
                timestamp = trade['timestamp'][11:16]
                symbol = trade['symbol'].split('/')[0]
                price = float(trade['price'])
                value = float(trade['value'])
                roi = float(trade['roi_percent'])
                
                if price >= 1000:
                    price_str = f"${price:,.0f}"
                elif price >= 1:
                    price_str = f"${price:,.2f}"
                else:
                    price_str = f"${price:.4f}"
                
                lines.append(
                    f"{side_emoji} <code>{timestamp}</code> <b>{symbol}</b> "
                    f"{price_str} ${value:,.0f} "
                    f"ROI: {roi:+.1f}%"
                )
            
            await self._send_message("\n".join(lines))
        except Exception as e:
            logger.error(f"Trades command error: {e}")
            await self._send_message(f"❌ Error reading trades: {e}")
    
    async def _cmd_profit(self, args: list) -> None:
        trades_file = "data/grid_trades.csv"
        
        if not os.path.exists(trades_file):
            await self._send_message("❌ No trading data found")
            return
        
        try:
            hours = int(args[0]) if args else 5
            
            with open(trades_file, 'r') as f:
                reader = csv.DictReader(f)
                trades = list(reader)
            
            if not trades:
                await self._send_message("❌ No trades yet")
                return
            
            from datetime import datetime, timedelta
            
            now = datetime.utcnow()
            cutoff = now - timedelta(hours=hours)
            
            positions = {}
            profit_before = 0.0
            profit_after = 0.0
            trades_in_period = []
            
            for trade in trades:
                timestamp = datetime.fromisoformat(trade['timestamp'].replace('Z', '+00:00').replace('+00:00', ''))
                symbol = trade['symbol']
                side = trade['side']
                price = float(trade['price'])
                amount = float(trade['amount'])
                
                if side == 'BUY':
                    if symbol not in positions:
                        positions[symbol] = []
                    positions[symbol].append({'price': price, 'amount': amount})
                else:
                    profit = 0.0
                    if symbol in positions and positions[symbol]:
                        pos = positions[symbol].pop(0)
                        profit = (price - pos['price']) * pos['amount']
                        
                        if timestamp < cutoff:
                            profit_before += profit
                        else:
                            profit_after += profit
                            if profit != 0:
                                trades_in_period.append({
                                    'timestamp': trade['timestamp'],
                                    'symbol': symbol,
                                    'profit': profit,
                                    'price': price,
                                    'buy_price': pos['price']
                                })
            
            total_profit = profit_before + profit_after
            
            lines = [
                f"💰 <b>Profit Report ({hours}h)</b>",
                "",
                f"<b>Period:</b> Last {hours} hours",
                f"<b>Profit in period:</b> ${profit_after:+.2f}",
                f"<b>Total profit:</b> ${total_profit:+.2f}",
                ""
            ]
            
            if trades_in_period:
                lines.append(f"<b>Trades in period:</b> {len(trades_in_period)}")
                lines.append("")
                
                by_symbol = {}
                for t in trades_in_period:
                    sym = t['symbol'].split('/')[0]
                    if sym not in by_symbol:
                        by_symbol[sym] = 0
                    by_symbol[sym] += t['profit']
                
                for sym, profit in sorted(by_symbol.items(), key=lambda x: x[1], reverse=True):
                    emoji = "✅" if profit > 0 else "❌"
                    lines.append(f"{emoji} <b>{sym}:</b> ${profit:+.2f}")
                
                lines.append("")
                lines.append("<b>Last 5 trades:</b>")
                for t in trades_in_period[-5:]:
                    time = t['timestamp'][11:16]
                    sym = t['symbol'].split('/')[0]
                    emoji = "✅" if t['profit'] > 0 else "❌"
                    pct = ((t['price'] - t['buy_price']) / t['buy_price']) * 100
                    
                    if t['price'] >= 1000:
                        bp = f"${t['buy_price']:,.0f}"
                        sp = f"${t['price']:,.0f}"
                    elif t['price'] >= 1:
                        bp = f"${t['buy_price']:,.2f}"
                        sp = f"${t['price']:,.2f}"
                    else:
                        bp = f"${t['buy_price']:.4f}"
                        sp = f"${t['price']:.4f}"
                    
                    lines.append(
                        f"{emoji} <code>{time}</code> {sym} "
                        f"{bp}→{sp} "
                        f"${t['profit']:+.2f} ({pct:+.1f}%)"
                    )
            else:
                lines.append(f"<i>No trades in last {hours} hours</i>")
            
            await self._send_message("\n".join(lines))
            
        except Exception as e:
            logger.error(f"Profit command error: {e}")
            await self._send_message(f"❌ Error: {e}")

    async def _cmd_daily(self, args: list) -> None:
        from collections import defaultdict
        
        trades_file = "data/grid_trades.csv"
        initial_balance = self._read_initial_balance()
        
        if not os.path.exists(trades_file):
            await self._send_message("❌ Файл grid_trades.csv не знайдено!")
            return
        
        try:
            with open(trades_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                trades = []
                for row in reader:
                    row['timestamp'] = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00').replace('+00:00', ''))
                    row['date'] = row['timestamp'].date()
                    row['realized_pnl'] = float(row['realized_pnl'])
                    row['unrealized_pnl'] = float(row['unrealized_pnl'])
                    row['balance'] = float(row['balance'])
                    row['total_value'] = float(row['total_value'])
                    row['roi_percent'] = float(row['roi_percent'])
                    trades.append(row)
            
            if not trades:
                await self._send_message("📊 Поки що немає трейдів!")
                return
            
            trades_by_date = defaultdict(list)
            for trade in trades:
                trades_by_date[trade['date']].append(trade)
            
            daily_stats = []
            dates = sorted(trades_by_date.keys())
            
            for date in dates:
                day_trades = trades_by_date[date]
                last_trade = day_trades[-1]
                
                if daily_stats:
                    prev_total_value = daily_stats[-1]['total_value']
                    daily_profit = last_trade['total_value'] - prev_total_value
                else:
                    daily_profit = last_trade['total_value'] - initial_balance
                
                buy_count = len([t for t in day_trades if t['side'] == 'BUY'])
                sell_count = len([t for t in day_trades if t['side'] == 'SELL'])
                
                daily_stats.append({
                    'date': date,
                    'trades_count': len(day_trades),
                    'daily_profit': daily_profit,
                    'total_value': last_trade['total_value'],
                    'roi_percent': last_trade['roi_percent'],
                    'ending_balance': last_trade['balance'],
                    'buy_trades': buy_count,
                    'sell_trades': sell_count
                })
            
            lines = ["📅 <b>Денний звіт по прибутку</b>", ""]
            
            total_profit = 0
            for stat in daily_stats:
                total_profit += stat['daily_profit']
                emoji = "✅" if stat['daily_profit'] >= 0 else "❌"
                date_str = stat['date'].strftime('%d.%m.%Y')
                
                lines.append(
                    f"<b>{date_str}</b> {emoji} ${stat['daily_profit']:+,.2f}\n"
                    f"   Трейдів: {stat['trades_count']} (🟢{stat['buy_trades']}↗ 🔴{stat['sell_trades']}↘)\n"
                    f"   ROI: {stat['roi_percent']:+.2f}% | Value: ${stat['total_value']:,.2f}"
                )
                lines.append("")
            
            lines.append(f"━━━━━━━━━━━━━━━━")
            last_stat = daily_stats[-1]
            current_value = last_stat['total_value']
            total_profit_actual = current_value - initial_balance
            lines.append(f"<b>ВСЬОГО:</b> ${total_profit_actual:+,.2f} (Value: ${current_value:,.2f})")
            lines.append("")
            
            best_day = max(daily_stats, key=lambda x: x['daily_profit'])
            worst_day = min(daily_stats, key=lambda x: x['daily_profit'])
            avg_daily = total_profit / len(daily_stats)
            profitable_days = len([s for s in daily_stats if s['daily_profit'] > 0])
            win_rate = (profitable_days / len(daily_stats)) * 100
            
            lines.append("<b>🏆 Статистика:</b>")
            lines.append(f"   Найкращий: {best_day['date'].strftime('%d.%m')} (${best_day['daily_profit']:+,.2f})")
            lines.append(f"   Найгірший: {worst_day['date'].strftime('%d.%m')} (${worst_day['daily_profit']:+,.2f})")
            lines.append(f"   Середній: ${avg_daily:+,.2f}/день")
            lines.append(f"   Прибуткових днів: {profitable_days}/{len(daily_stats)} ({win_rate:.0f}%)")
            
            await self._send_message("\n".join(lines))
            
        except Exception as e:
            logger.error(f"Daily command error: {e}")
            await self._send_message(f"❌ Помилка: {e}")

