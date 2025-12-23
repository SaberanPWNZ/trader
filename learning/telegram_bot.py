import asyncio
from datetime import datetime
from typing import Optional, Callable, Dict, Any
import aiohttp
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

        if not text or not chat_id:
            return

        if str(chat_id) != str(self.chat_id):
            logger.warning(f"Unauthorized chat: {chat_id}")
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
🤖 <b>Trading Bot Learning System</b>

Commands:
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
