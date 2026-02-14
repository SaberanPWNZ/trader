#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
from loguru import logger

class LiveReadinessCheck:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
    
    def check(self, name: str, result: bool, error: str = "", warning: bool = False):
        if result:
            print(f"  ✅ {name}")
            self.passed.append(name)
        else:
            if warning:
                print(f"  ⚠️  {name}: {error}")
                self.warnings.append((name, error))
            else:
                print(f"  ❌ {name}: {error}")
                self.failed.append((name, error))
    
    async def run_all(self):
        print("\n" + "=" * 60)
        print("  LIVE TRADING READINESS VERIFICATION")
        print("=" * 60 + "\n")
        
        await self.check_telegram_commands()
        await self.check_error_handling()
        await self.check_portfolio_protection()
        await self.check_monitoring()
        await self.check_risk_management()
        
        self.print_summary()
        return len(self.failed) == 0
    
    async def check_telegram_commands(self):
        print("1️⃣  TELEGRAM COMMANDS:")
        
        try:
            from learning.telegram_bot import LearningTelegramBot
            bot = LearningTelegramBot()
            
            required_commands = [
                '/start', '/help', '/status', '/balance', '/grid',
                '/trades', '/profit', '/daily'
            ]
            
            for cmd in required_commands:
                exists = cmd in bot._commands
                self.check(f"Command {cmd}", exists, "Missing")
            
            from config.settings import settings
            self.check(
                "Telegram enabled",
                settings.monitoring.telegram_enabled,
                "Disabled in settings",
                warning=True
            )
            
            self.check(
                "Telegram token configured",
                bool(settings.monitoring.telegram_token),
                "No token"
            )
            
            self.check(
                "Telegram chat_id configured",
                bool(settings.monitoring.telegram_chat_id),
                "No chat_id"
            )
            
        except Exception as e:
            self.check("Telegram module", False, str(e))
        
        print()
    
    async def check_error_handling(self):
        print("2️⃣  ERROR HANDLING:")
        
        files_to_check = [
            "execution/grid_live.py",
            "exchange/client.py",
            "monitoring/alerts.py",
            "learning/telegram_bot.py"
        ]
        
        for file in files_to_check:
            path = Path(file)
            if path.exists():
                content = path.read_text()
                has_try_except = "try:" in content and "except" in content
                self.check(
                    f"Error handling in {file}",
                    has_try_except,
                    "No try-except blocks found"
                )
        
        print()
    
    async def check_portfolio_protection(self):
        print("3️⃣  PORTFOLIO PROTECTION:")
        
        try:
            from config.settings import settings
            from risk.manager import RiskManager
            from risk.kill_switch import KillSwitch
            
            self.check("Risk manager available", True, "")
            self.check("Kill switch available", True, "")
            
            self.check(
                "Max risk per trade",
                settings.risk.max_risk_per_trade <= 0.05,
                f"Too high: {settings.risk.max_risk_per_trade*100:.1f}%"
            )
            
            self.check(
                "Max daily loss",
                settings.risk.max_daily_loss <= 0.20,
                f"Too high: {settings.risk.max_daily_loss*100:.1f}%"
            )
            
            self.check(
                "Max drawdown",
                settings.risk.max_drawdown <= 0.30,
                f"Too high: {settings.risk.max_drawdown*100:.1f}%"
            )
            
            self.check(
                "Kill switch enabled",
                settings.risk.kill_switch_enabled,
                "Should be enabled for safety",
                warning=True
            )
            
            rm = RiskManager(10000)
            can_trade, reason = rm.can_trade("ETH/USDT")
            self.check("Risk manager operational", can_trade, reason)
            
        except Exception as e:
            self.check("Risk management", False, str(e))
        
        print()
    
    async def check_monitoring(self):
        print("4️⃣  MONITORING & LOGGING:")
        
        try:
            from monitoring.alerts import telegram
            self.check("Telegram alerts available", True, "")
            
            log_dir = Path("logs")
            self.check("Logs directory", log_dir.exists(), "Missing")
            
            data_dir = Path("data")
            self.check("Data directory", data_dir.exists(), "Missing")
            
            trades_file = Path("data/grid_live_trades.csv")
            self.check(
                "Trades logging",
                trades_file.exists(),
                "File will be created on first trade",
                warning=True
            )
            
            from loguru import logger
            self.check("Loguru available", True, "")
            
        except Exception as e:
            self.check("Monitoring setup", False, str(e))
        
        print()
    
    async def check_risk_management(self):
        print("5️⃣  ADDITIONAL SAFETY:")
        
        try:
            files_exist = [
                ("pre_live_check.py", "Pre-launch checks"),
                ("execution/grid_live.py", "Live trading engine"),
                ("analyze_real_status.py", "Status analysis"),
            ]
            
            for file, desc in files_exist:
                self.check(desc, Path(file).exists(), f"{file} not found")
            
            from execution.grid_live import GridLiveTrader
            self.check("GridLiveTrader available", True, "")
            
            trader_code = Path("execution/grid_live.py").read_text()
            self.check(
                "Balance tracking",
                "_update_balance_state" in trader_code,
                "Missing"
            )
            
            self.check(
                "Trade sync from exchange",
                "_sync_trades_from_exchange" in trader_code,
                "Missing"
            )
            
            self.check(
                "Position tracking",
                "LiveGridPosition" in trader_code,
                "Missing"
            )
            
        except Exception as e:
            self.check("Safety features", False, str(e))
        
        print()
    
    def print_summary(self):
        print("=" * 60)
        print("  SUMMARY")
        print("=" * 60)
        print(f"  ✅ Passed: {len(self.passed)}")
        print(f"  ❌ Failed: {len(self.failed)}")
        print(f"  ⚠️  Warnings: {len(self.warnings)}")
        print()
        
        if self.failed:
            print("  🚨 CRITICAL ISSUES:")
            for name, error in self.failed:
                print(f"     • {name}: {error}")
            print()
        
        if self.warnings:
            print("  ⚠️  WARNINGS:")
            for name, error in self.warnings:
                print(f"     • {name}: {error}")
            print()
        
        if not self.failed:
            print("  ✅ ALL SYSTEMS READY FOR LIVE TRADING!")
            print()
            print("  📝 FINAL CHECKLIST:")
            print("     1. Run: python main.py pre-live-check")
            print("     2. Test commands in Telegram")
            print("     3. Start with small balance ($100-200)")
            print("     4. Monitor closely first 24h")
        else:
            print("  ❌ RESOLVE ISSUES BEFORE LIVE TRADING")
        
        print("=" * 60)

async def main():
    checker = LiveReadinessCheck()
    success = await checker.run_all()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
