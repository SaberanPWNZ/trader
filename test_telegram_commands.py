#!/usr/bin/env python3
import asyncio
import sys
from learning.telegram_bot import LearningTelegramBot

async def test_commands():
    print("\n" + "=" * 60)
    print("  TESTING TELEGRAM BOT COMMANDS")
    print("=" * 60 + "\n")
    
    bot = LearningTelegramBot()
    
    test_cases = [
        ("/start", "Show welcome message"),
        ("/help", "Show help"),
        ("/balance", "Get balance"),
        ("/grid", "Grid status"),
        ("/trades 5", "Last 5 trades"),
        ("/profit", "Profit report"),
        ("/daily", "Daily report"),
    ]
    
    print("Available commands:\n")
    for cmd, desc in test_cases:
        has_cmd = cmd.split()[0] in bot._commands
        status = "✅" if has_cmd else "❌"
        print(f"  {status} {cmd:<15} - {desc}")
    
    print("\n" + "=" * 60)
    print("  TO TEST IN TELEGRAM:")
    print("=" * 60)
    print("\n1. Make sure bot is running:")
    print("   python main.py grid-live --balance 2000\n")
    print("2. Open Telegram and send these commands to your bot\n")
    print("3. Verify responses are correct\n")
    
    all_present = all(cmd.split()[0] in bot._commands for cmd, _ in test_cases)
    
    if all_present:
        print("✅ All commands are registered!\n")
        return 0
    else:
        print("❌ Some commands missing\n")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(test_commands()))
