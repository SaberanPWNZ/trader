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
            "/stats": self._cmd_stats,
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

    async def _get_live_data(self):
        from exchange.factory import create_exchange
        
        ex = create_exchange(testnet=False)
        await ex.connect()
        
        balance = await ex.fetch_balance()
        ticker = await ex.fetch_ticker('ETH/USDT')
        eth_price = ticker['last']
        
        usdt_total = balance.get('USDT', {}).get('total', 0)
        usdt_free = balance.get('USDT', {}).get('free', 0)
        usdt_used = balance.get('USDT', {}).get('used', 0)
        eth_total = balance.get('ETH', {}).get('total', 0)
        eth_value = eth_total * eth_price
        total_value = usdt_total + eth_value
        
        state_file = "data/grid_live_balance.json"
        initial = total_value
        start_time = None
        trading_pnl = 0
        holding_pnl = 0
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                state = json.load(f)
                initial = state.get("initial_balance", total_value)
                start_time = state.get("start_time")
                trading_pnl = state.get("trading_pnl", 0)
                holding_pnl = state.get("holding_pnl", 0)
        
        orders = await ex.fetch_open_orders('ETH/USDT')
        
        all_trades = []
        since = None
        for _ in range(10):
            trades = await ex.fetch_my_trades('ETH/USDT', since=since, limit=1000)
            if not trades:
                break
            all_trades.extend(trades)
            if len(trades) < 100:
                break
            since = trades[-1]['timestamp'] + 1
        
        await ex.disconnect()
        
        total_pnl = total_value - initial
        pnl_percent = (total_pnl / initial * 100) if initial > 0 else 0
        
        return {
            'usdt_total': usdt_total,
            'usdt_balance': usdt_total,
            'usdt_free': usdt_free,
            'usdt_used': usdt_used,
            'eth_total': eth_total,
            'eth_value': eth_value,
            'eth_price': eth_price,
            'total_value': total_value,
            'initial_balance': initial,
            'total_pnl': total_pnl,
            'pnl_percent': pnl_percent,
            'trading_pnl': trading_pnl,
            'holding_pnl': holding_pnl,
            'start_time': start_time,
            'orders': orders,
            'trades': all_trades
        }

    async def _cmd_balance(self, args: list) -> None:
        try:
            data = await self._get_live_data()
            
            trading_pnl = data.get('trading_pnl', 0)
            holding_pnl = data.get('holding_pnl', 0)
            total_pnl = data['total_pnl']
            pnl_pct = data['pnl_percent']
            
            buy_count = sum(1 for t in data['trades'] if t['side'] == 'buy')
            sell_count = sum(1 for t in data['trades'] if t['side'] == 'sell')
            
            roi_emoji = "✅" if total_pnl >= 0 else "⚠️" if total_pnl >= -50 else "🚨"
            
            lines = [
                "💰 <b>Portfolio Balance (MAINNET 🔴)</b>",
                "",
                f"💎 <b>Total Value:</b> ${data['total_value']:,.2f}",
                f"   ├ 💵 USDT: ${data['usdt_total']:,.2f}",
                f"   └ 🪙 ETH: {data['eth_total']:.4f} (${data['eth_value']:,.2f})",
                "",
                f"{roi_emoji} <b>Performance:</b>",
                f"   Initial: ${data['initial_balance']:,.2f}",
                f"   Trading PnL: ${trading_pnl:+.2f}",
                f"   Holding PnL: ${holding_pnl:+.2f}",
                f"   Total: ${total_pnl:+,.2f} ({pnl_pct:+.2f}%)",
                "",
                f"<b>📈 Activity:</b> {len(data['trades'])} trades ({buy_count}↗ {sell_count}↘)",
                f"<b>📋 Open Orders:</b> {len(data['orders'])}",
                "",
                f"<i>ETH Price: ${data['eth_price']:,.2f}</i>"
            ]
            
            await self._send_message("\n".join(lines))
            
        except Exception as e:
            logger.error(f"Balance command error: {e}")
            await self._send_message(f"❌ Error: {e}")

    async def _cmd_grid(self, args: list) -> None:
        try:
            data = await self._get_live_data()
            
            lines = ["📊 <b>Grid Trading Status (MAINNET 🔴)</b>\n"]
            
            lines.append(f"<b>ETH/USDT</b>")
            lines.append(f"├ Price: ${data['eth_price']:,.2f}")
            lines.append(f"├ Position: {data['eth_total']:.4f} ETH (${data['eth_value']:,.2f})")
            lines.append(f"└ Orders: {len(data['orders'])}\n")
            
            if data['orders']:
                lines.append("<b>📋 Open Orders:</b>")
                for o in data['orders']:
                    side = o['side'].upper()
                    icon = "🟢" if side == "BUY" else "🔴"
                    lines.append(f"   {icon} {side} @ ${o['price']:,.2f}")
            
            await self._send_message("\n".join(lines))
            
        except Exception as e:
            logger.error(f"Grid command error: {e}")
            await self._send_message(f"❌ Error: {e}")

    async def _cmd_trades(self, args: list) -> None:
        try:
            data = await self._get_live_data()
            limit = int(args[0]) if args and args[0].isdigit() else 10
            
            trades = data['trades'][-limit:]
            
            if not trades:
                await self._send_message("❌ No trades yet")
                return
            
            lines = [f"📈 <b>Last {len(trades)} Trades (MAINNET 🔴)</b>\n"]
            
            from datetime import datetime
            for trade in trades:
                side_emoji = "🟢" if trade['side'] == 'buy' else "🔴"
                ts = datetime.fromtimestamp(trade['timestamp']/1000).strftime('%H:%M')
                price = float(trade['price'])
                cost = float(trade['cost'])
                
                if price >= 1000:
                    price_str = f"${price:,.0f}"
                elif price >= 1:
                    price_str = f"${price:,.2f}"
                else:
                    price_str = f"${price:.4f}"
                
                lines.append(
                    f"{side_emoji} <code>{ts}</code> ETH {price_str} ${cost:,.0f}"
                )
            
            await self._send_message("\n".join(lines))
        except Exception as e:
            logger.error(f"Trades command error: {e}")
            await self._send_message(f"❌ Error reading trades: {e}")
    
    async def _cmd_profit(self, args: list) -> None:
        try:
            data = await self._get_live_data()
            
            trading_pnl = data.get('trading_pnl', 0)
            holding_pnl = data.get('holding_pnl', 0)
            total_pnl = data['total_pnl']
            pnl_pct = data['pnl_percent']
            usdt = data['usdt_balance']
            eth = data['eth_total']
            eth_val = data['eth_value']
            total = usdt + eth_val
            
            lines = [
                "💰 <b>Profit Report (MAINNET 🔴)</b>",
                "",
                f"<b>Balance:</b> ${usdt:,.2f} USDT",
                f"<b>Position:</b> {eth:.4f} ETH (${eth_val:,.2f})",
                f"<b>Total Value:</b> ${total:,.2f}",
                "",
                f"<b>Trading PnL:</b> ${trading_pnl:+.2f}",
                f"<b>Holding PnL:</b> ${holding_pnl:+.2f}",
                f"<b>Total PnL:</b> ${total_pnl:+,.2f} ({pnl_pct:+.2f}%)",
                f"<b>Trades:</b> {len(data['trades'])}",
            ]
            
            await self._send_message("\n".join(lines))
            
        except Exception as e:
            logger.error(f"Profit command error: {e}")
            await self._send_message(f"❌ Error: {e}")
    
    async def _cmd_stats(self, args: list) -> None:
        try:
            state_file = "data/grid_live_balance.json"
            if not os.path.exists(state_file):
                await self._send_message("❌ No trading data yet")
                return
            
            with open(state_file, 'r') as f:
                state = json.load(f)
            
            initial = state.get('initial_balance', 0)
            initial_eth_price = state.get('initial_eth_price', 0)
            current_eth_price = state.get('eth_price', 0)
            total_value = state.get('total_value', 0)
            trading_pnl = state.get('trading_pnl', 0)
            holding_pnl = state.get('holding_pnl', 0)
            realized_pnl = state.get('realized_pnl', 0)
            total_fees = state.get('total_fees_paid', 0)
            
            cycles = state.get('completed_cycles', 0)
            wins = state.get('winning_trades', 0)
            losses = state.get('losing_trades', 0)
            win_rate = state.get('win_rate', 0)
            avg_profit = state.get('avg_profit_per_cycle', 0)
            
            eth_price_change = ((current_eth_price - initial_eth_price) / initial_eth_price * 100) if initial_eth_price > 0 else 0
            total_pnl = total_value - initial
            total_pnl_pct = (total_pnl / initial * 100) if initial > 0 else 0
            
            lines = [
                "📊 <b>Детальна статистика торгівлі (MAINNET 🔴)</b>",
                "",
                "<b>💵 ПРИБУТКИ:</b>",
                f"├ Trading PnL: <b>${trading_pnl:+.2f}</b>",
                f"├ Holding PnL: <b>${holding_pnl:+.2f}</b>",
                f"├ Total PnL: <b>${total_pnl:+.2f}</b> ({total_pnl_pct:+.2f}%)",
                f"└ Fees Paid: <code>-${total_fees:.2f}</code>",
                "",
                "<b>📈 ТОРГІВЛЯ:</b>",
                f"├ Cycles: <b>{cycles}</b>",
                f"├ Win Rate: <b>{win_rate:.1f}%</b> ({wins}W / {losses}L)",
                f"└ Avg per cycle: <b>${avg_profit:+.2f}</b>",
                "",
                "<b>💰 БАЛАНС:</b>",
                f"├ Initial: ${initial:.2f}",
                f"├ Current: <b>${total_value:.2f}</b>",
                f"└ ETH price: ${initial_eth_price:.0f} → ${current_eth_price:.0f} ({eth_price_change:+.1f}%)",
            ]
            
            if cycles > 0:
                lines.append("")
                lines.append("<b>📌 ПОЯСНЕННЯ:</b>")
                lines.append("• <b>Trading PnL</b> = прибуток від циклів купівлі-продажу")
                lines.append("• <b>Holding PnL</b> = зміна вартості через ціну ETH")
                lines.append("• <b>Win Rate</b> = % прибуткових циклів")
            
            await self._send_message("\n".join(lines))
            
        except Exception as e:
            logger.error(f"Stats command error: {e}")
            await self._send_message(f"❌ Error: {e}")

    async def _cmd_daily(self, args: list) -> None:
        try:
            data = await self._get_live_data()
            
            total_pnl = data['total_pnl']
            pnl_pct = data['pnl_percent']
            usdt = data['usdt_balance']
            eth = data['eth_total']
            eth_val = data['eth_value']
            total = usdt + eth_val
            trades = data['trades']
            
            from collections import defaultdict
            from datetime import datetime
            
            trades_by_date = defaultdict(list)
            for t in trades:
                date = datetime.fromtimestamp(t['timestamp']/1000).date()
                trades_by_date[date].append(t)
            
            lines = ["📅 <b>Daily Report (MAINNET 🔴)</b>", ""]
            
            for date in sorted(trades_by_date.keys()):
                day_trades = trades_by_date[date]
                buys = sum(1 for t in day_trades if t['side'] == 'buy')
                sells = sum(1 for t in day_trades if t['side'] == 'sell')
                date_str = date.strftime('%d.%m.%Y')
                
                lines.append(f"<b>{date_str}</b>")
                lines.append(f"   Trades: {len(day_trades)} (🟢{buys}↗ 🔴{sells}↘)")
                lines.append("")
            
            lines.append("━━━━━━━━━━━━━━━━")
            lines.append(f"<b>Total Value:</b> ${total:,.2f}")
            lines.append(f"<b>PnL:</b> ${total_pnl:+,.2f} ({pnl_pct:+.2f}%)")
            lines.append(f"<b>Total Trades:</b> {len(trades)}")
            
            await self._send_message("\n".join(lines))
            
        except Exception as e:
            logger.error(f"Daily command error: {e}")
            await self._send_message(f"❌ Error: {e}")

