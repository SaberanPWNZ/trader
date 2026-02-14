#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

class PreLiveChecker:
    def __init__(self):
        self.checks_passed = 0
        self.checks_failed = 0
        self.warnings = []
        self.errors = []
        
    def check(self, name: str, condition: bool, error_msg: str = "", warning_only: bool = False):
        if condition:
            print(f"  ✅ {name}")
            self.checks_passed += 1
            return True
        else:
            if warning_only:
                print(f"  ⚠️  {name}: {error_msg}")
                self.warnings.append(f"{name}: {error_msg}")
            else:
                print(f"  ❌ {name}: {error_msg}")
                self.errors.append(f"{name}: {error_msg}")
                self.checks_failed += 1
            return False

    async def run_all_checks(self):
        print("=" * 60)
        print("    PRE-LIVE TRADING CHECKLIST")
        print("=" * 60)
        print()
        
        await self.check_environment()
        await self.check_api_keys()
        await self.check_testnet_performance()
        await self.check_exchange_connection()
        await self.check_balance()
        await self.check_risk_settings()
        
        self.print_summary()
        return self.checks_failed == 0

    async def check_environment(self):
        print("1️⃣  ENVIRONMENT:")
        
        self.check(
            "Python version",
            sys.version_info >= (3, 10),
            f"Python 3.10+ required, got {sys.version_info.major}.{sys.version_info.minor}"
        )
        
        required_files = [
            "config/settings.py",
            "execution/grid_live.py",
            "exchange/factory.py",
            ".env"
        ]
        for f in required_files:
            self.check(
                f"File exists: {f}",
                Path(f).exists(),
                "File not found"
            )
        
        required_dirs = ["data", "logs"]
        for d in required_dirs:
            Path(d).mkdir(exist_ok=True)
            self.check(f"Directory: {d}", Path(d).exists(), "Cannot create")
        
        print()

    async def check_api_keys(self):
        print("2️⃣  API KEYS:")
        
        from dotenv import load_dotenv
        load_dotenv()
        
        testnet_key = os.getenv("BINANCE_TESTNET_API_KEY", "") or os.getenv("BINANCE_API_KEY", "")
        testnet_secret = os.getenv("BINANCE_TESTNET_API_SECRET", "") or os.getenv("BINANCE_API_SECRET", "")
        
        self.check(
            "Testnet API Key configured",
            len(testnet_key) > 10,
            "No API key for testnet"
        )
        self.check(
            "Testnet API Secret configured",
            len(testnet_secret) > 10,
            "No API secret for testnet"
        )
        
        live_key = os.getenv("BINANCE_API_KEY", "")
        live_secret = os.getenv("BINANCE_API_SECRET", "")
        
        has_separate_keys = bool(os.getenv("BINANCE_TESTNET_API_KEY"))
        
        if has_separate_keys:
            self.check("Live API Key configured", len(live_key) > 10, "BINANCE_API_KEY not set")
            self.check("Live API Secret configured", len(live_secret) > 10, "BINANCE_API_SECRET not set")
        else:
            print("  ⚠️  Using same keys for testnet and live (OK for now)")
            print("     For mainnet: create separate BINANCE_API_KEY on binance.com")
        
        print()

    async def check_testnet_performance(self):
        print("3️⃣  TESTNET PERFORMANCE:")
        
        balance_file = Path("data/grid_live_balance.json")
        if not balance_file.exists():
            self.check("Testnet history exists", False, "No testnet trading history found")
            print()
            return
        
        with open(balance_file, 'r') as f:
            state = json.load(f)
        
        initial = state.get('initial_balance', 0)
        start_time_str = state.get('start_time', '')
        
        self.check("Initial balance recorded", initial > 0, "No initial balance")
        
        if start_time_str:
            start_time = datetime.fromisoformat(start_time_str)
            runtime = datetime.now() - start_time
            runtime_hours = runtime.total_seconds() / 3600
            
            self.check(
                f"Runtime ({runtime_hours:.1f}h)",
                runtime_hours >= 24,
                "Less than 24 hours of testing",
                warning_only=True
            )
        
        from exchange.factory import create_exchange
        ex = create_exchange(testnet=True)
        await ex.connect()
        
        balance = await ex.fetch_balance()
        ticker = await ex.fetch_ticker('ETH/USDT')
        eth_price = ticker['last']
        
        usdt_total = balance.get('USDT', {}).get('total', 0)
        eth_total = balance.get('ETH', {}).get('total', 0)
        eth_value = eth_total * eth_price
        total_value = usdt_total + eth_value
        
        pnl = total_value - initial
        roi = (pnl / initial) * 100 if initial > 0 else 0
        
        print(f"     Current value: ${total_value:.2f}")
        print(f"     PnL: ${pnl:.2f} ({roi:.2f}%)")
        
        self.check(
            "Profitable on testnet",
            pnl > 0,
            f"Testnet is in loss: ${pnl:.2f}",
            warning_only=True
        )
        
        self.check(
            "ROI > 1%",
            roi > 1.0,
            f"ROI too low: {roi:.2f}%",
            warning_only=True
        )
        
        trades = await ex.fetch_my_trades('ETH/USDT')
        
        self.check(
            f"Sufficient trades ({len(trades)})",
            len(trades) >= 50,
            f"Only {len(trades)} trades - need more data",
            warning_only=True
        )
        
        await ex.disconnect()
        print()

    async def check_exchange_connection(self):
        print("4️⃣  EXCHANGE CONNECTION:")
        
        from exchange.factory import create_exchange
        
        try:
            ex = create_exchange(testnet=True)
            await ex.connect()
            self.check("Testnet connection", True, "")
            await ex.disconnect()
        except Exception as e:
            self.check("Testnet connection", False, str(e))
        
        has_separate_keys = bool(os.getenv("BINANCE_API_KEY")) and bool(os.getenv("BINANCE_TESTNET_API_KEY"))
        
        if not has_separate_keys:
            print("  ⚠️  Mainnet check skipped (no separate mainnet keys)")
            print("     Create keys at binance.com for live trading")
        else:
            try:
                live_key = os.getenv("BINANCE_API_KEY", "")
                live_secret = os.getenv("BINANCE_API_SECRET", "")
                
                if live_key and live_secret:
                    import ccxt.async_support as ccxt
                    ex = ccxt.binance({
                        'apiKey': live_key,
                        'secret': live_secret,
                        'enableRateLimit': True,
                    })
                    await ex.load_markets()
                    balance = await ex.fetch_balance()
                    usdt = balance.get('USDT', {}).get('free', 0)
                    self.check(f"Live connection (USDT: ${usdt:.2f})", True, "")
                    await ex.close()
            except Exception as e:
                self.check("Live connection", False, str(e))
        
        print()

    async def check_balance(self):
        print("5️⃣  LIVE BALANCE:")
        
        has_separate_keys = bool(os.getenv("BINANCE_API_KEY")) and bool(os.getenv("BINANCE_TESTNET_API_KEY"))
        
        if not has_separate_keys:
            print("  ⚠️  Skipped - no mainnet keys configured yet")
            print("     Current keys are for testnet only")
            print()
            return
        
        live_key = os.getenv("BINANCE_API_KEY", "")
        live_secret = os.getenv("BINANCE_API_SECRET", "")
        
        try:
            import ccxt.async_support as ccxt
            ex = ccxt.binance({
                'apiKey': live_key,
                'secret': live_secret,
                'enableRateLimit': True,
            })
            
            balance = await ex.fetch_balance()
            usdt_free = balance.get('USDT', {}).get('free', 0)
            usdt_total = balance.get('USDT', {}).get('total', 0)
            
            print(f"     USDT Free: ${usdt_free:.2f}")
            print(f"     USDT Total: ${usdt_total:.2f}")
            
            self.check(
                "Minimum balance ($100)",
                usdt_free >= 100,
                f"Only ${usdt_free:.2f} available"
            )
            
            self.check(
                "Recommended balance ($500+)",
                usdt_free >= 500,
                f"${usdt_free:.2f} - consider starting with more",
                warning_only=True
            )
            
            await ex.close()
        except Exception as e:
            self.check("Live balance check", False, str(e))
        
        print()

    async def check_risk_settings(self):
        print("6️⃣  RISK SETTINGS:")
        
        from config.settings import settings
        
        self.check(
            "Max risk per trade <= 5%",
            settings.risk.max_risk_per_trade <= 0.05,
            f"Risk {settings.risk.max_risk_per_trade*100:.1f}% is too high"
        )
        
        self.check(
            "Max daily loss <= 20%",
            settings.risk.max_daily_loss <= 0.20,
            f"Daily loss {settings.risk.max_daily_loss*100:.1f}% is too high"
        )
        
        self.check(
            "Kill switch enabled",
            settings.risk.kill_switch_enabled,
            "Kill switch should be ON for safety",
            warning_only=True
        )
        
        print()

    def print_summary(self):
        print("=" * 60)
        print("    SUMMARY")
        print("=" * 60)
        print(f"  ✅ Passed: {self.checks_passed}")
        print(f"  ❌ Failed: {self.checks_failed}")
        print(f"  ⚠️  Warnings: {len(self.warnings)}")
        print()
        
        if self.checks_failed == 0:
            print("  🎉 ALL CRITICAL CHECKS PASSED!")
            print()
            if self.warnings:
                print("  ⚠️  Warnings to consider:")
                for w in self.warnings:
                    print(f"     - {w}")
                print()
            print("  📝 NEXT STEPS:")
            print("     1. Review the warnings above")
            print("     2. Start with a SMALL amount ($100-500)")
            print("     3. Run: python main.py grid-live --balance 100")
            print("     4. Monitor closely for the first few hours")
        else:
            print("  ❌ CRITICAL ISSUES FOUND:")
            for e in self.errors:
                print(f"     - {e}")
            print()
            print("  🛑 DO NOT START LIVE TRADING until issues are fixed!")
        
        print("=" * 60)


async def main():
    checker = PreLiveChecker()
    success = await checker.run_all_checks()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
