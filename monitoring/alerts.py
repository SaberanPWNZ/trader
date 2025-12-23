"""
Telegram alerts for trading notifications.
"""
import asyncio
from typing import Optional
from datetime import datetime
import aiohttp
from loguru import logger

from config.settings import settings


class TelegramAlert:
    """
    Telegram bot for trading alerts.
    
    Sends notifications for:
    - Trade executions
    - Risk limit breaches
    - Emergency shutdowns
    - Daily summaries
    """
    
    def __init__(self):
        self.enabled = settings.monitoring.telegram_enabled
        self.token = settings.monitoring.telegram_token
        self.chat_id = settings.monitoring.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a message to Telegram.
        
        Args:
            text: Message text
            parse_mode: HTML or Markdown
            
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            logger.debug(f"Telegram disabled, would send: {text[:50]}...")
            return False
        
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials not configured")
            return False
        
        try:
            session = await self._get_session()
            
            async with session.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode
                }
            ) as response:
                if response.status == 200:
                    return True
                else:
                    logger.error(f"Telegram API error: {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    async def trade_opened(
        self,
        symbol: str,
        side: str,
        amount: float,
        entry_price: float,
        stop_loss: float = None,
        take_profit: float = None
    ) -> None:
        """Send trade opened notification."""
        emoji = "🟢" if side == "long" else "🔴"
        
        message = f"""
{emoji} <b>Trade Opened</b>

<b>Symbol:</b> {symbol}
<b>Side:</b> {side.upper()}
<b>Amount:</b> {amount:.6f}
<b>Entry Price:</b> ${entry_price:,.2f}
"""
        
        if stop_loss:
            message += f"<b>Stop Loss:</b> ${stop_loss:,.2f}\n"
        if take_profit:
            message += f"<b>Take Profit:</b> ${take_profit:,.2f}\n"
        
        message += f"\n<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
        
        await self.send_message(message)
    
    async def trade_closed(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        reason: str
    ) -> None:
        """Send trade closed notification."""
        emoji = "✅" if pnl >= 0 else "❌"
        pnl_sign = "+" if pnl >= 0 else ""
        
        message = f"""
{emoji} <b>Trade Closed</b>

<b>Symbol:</b> {symbol}
<b>Side:</b> {side.upper()}
<b>Entry:</b> ${entry_price:,.2f}
<b>Exit:</b> ${exit_price:,.2f}
<b>PnL:</b> {pnl_sign}${pnl:,.2f}
<b>Reason:</b> {reason}

<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
        await self.send_message(message)
    
    async def risk_alert(self, event_type: str, details: str) -> None:
        """Send risk alert notification."""
        message = f"""
⚠️ <b>RISK ALERT</b>

<b>Event:</b> {event_type}
<b>Details:</b> {details}

<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
        await self.send_message(message)
    
    async def kill_switch_alert(self, reason: str) -> None:
        """Send kill switch activation alert."""
        message = f"""
🚨 <b>KILL SWITCH ACTIVATED</b> 🚨

<b>Reason:</b> {reason}

All trading has been halted. Manual intervention required.

<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
        await self.send_message(message)
    
    async def daily_summary(
        self,
        total_trades: int,
        winning_trades: int,
        daily_pnl: float,
        balance: float,
        open_positions: int
    ) -> None:
        """Send daily trading summary."""
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        pnl_sign = "+" if daily_pnl >= 0 else ""
        
        message = f"""
📊 <b>Daily Trading Summary</b>

<b>Total Trades:</b> {total_trades}
<b>Win Rate:</b> {win_rate:.1f}%
<b>Daily PnL:</b> {pnl_emoji} {pnl_sign}${daily_pnl:,.2f}
<b>Balance:</b> ${balance:,.2f}
<b>Open Positions:</b> {open_positions}

<i>{datetime.utcnow().strftime('%Y-%m-%d')} UTC</i>
"""
        await self.send_message(message)
    
    async def system_status(self, status: str, details: str = "") -> None:
        emoji = "✅" if status == "online" else "🔴"
        
        message = f"""
{emoji} <b>System Status: {status.upper()}</b>

{details}

<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
        await self.send_message(message)

    async def training_started(self, symbol: str) -> None:
        message = f"""
🔄 <b>Training Started</b>

<b>Symbol:</b> {symbol}
<b>Model:</b> {settings.strategy.model_type}

<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
        await self.send_message(message)

    async def training_complete(
        self,
        symbol: str,
        model_type: str,
        train_accuracy: float,
        test_accuracy: float,
        samples: int,
        duration_seconds: float,
        improvement: float = 0,
        deployed: bool = False
    ) -> None:
        emoji = "🤖" if test_accuracy >= 0.6 else "⚠️"
        improvement_text = f"+{improvement:.1%}" if improvement > 0 else f"{improvement:.1%}"
        deployed_text = "✅ Auto-deployed" if deployed else "⏸️ Pending review"

        message = f"""
{emoji} <b>Training Complete</b>

<b>Symbol:</b> {symbol}
<b>Model:</b> {model_type}
<b>Train Accuracy:</b> {train_accuracy:.1%}
<b>Test Accuracy:</b> {test_accuracy:.1%}
<b>Improvement:</b> {improvement_text}
<b>Samples:</b> {samples:,}
<b>Duration:</b> {duration_seconds:.1f}s
<b>Status:</b> {deployed_text}

<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
        await self.send_message(message)

    async def training_failed(self, symbol: str, error: str) -> None:
        message = f"""
❌ <b>Training Failed</b>

<b>Symbol:</b> {symbol}
<b>Error:</b> {error}

<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
        await self.send_message(message)

    async def model_deployed(self, symbol: str, model_id: str, accuracy: float) -> None:
        message = f"""
🚀 <b>Model Deployed</b>

<b>Symbol:</b> {symbol}
<b>Model ID:</b> <code>{model_id}</code>
<b>Accuracy:</b> {accuracy:.1%}

<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
        await self.send_message(message)

    async def performance_report(
        self,
        symbol: str,
        total_predictions: int,
        accuracy: float,
        total_pnl: float,
        period_days: int = 7
    ) -> None:
        emoji = "📈" if total_pnl >= 0 else "📉"
        pnl_sign = "+" if total_pnl >= 0 else ""

        message = f"""
📊 <b>Performance Report ({period_days}d)</b>

<b>Symbol:</b> {symbol}
<b>Predictions:</b> {total_predictions}
<b>Accuracy:</b> {accuracy:.1%}
<b>PnL:</b> {emoji} {pnl_sign}${total_pnl:,.2f}

<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</i>
"""
        await self.send_message(message)


telegram = TelegramAlert()
