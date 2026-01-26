#!/usr/bin/env python3
"""
Test rule-based strategy on historical data
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger

from strategies.rule_based import RuleBasedStrategy
from config.settings import settings


def load_local_data(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']]
    return df


async def backtest_strategy(symbol: str, days: int = 90, use_local: bool = True):
    if use_local and 'BTC' in symbol:
        logger.info(f"Loading local BTC data (full year 2024)...")
        data = load_local_data('/app/data/local/BTC-USD_2024-01-01_2024-12-31.csv')
        logger.info(f"Loaded {len(data)} candles from local file")
    else:
        from data.collector import DataCollector
        collector = DataCollector()
        await collector.connect()
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        logger.info(f"Loading {days} days of {symbol} data...")
        data = await collector.fetch_historical_data(
            symbol=symbol,
            timeframe="1h",
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d")
        )
        await collector.disconnect()
    
    if data.empty:
        logger.error(f"No data for {symbol}")
        return None
    
    logger.info(f"Loaded {len(data)} candles")
    
    strategy = RuleBasedStrategy()
    
    balance = 100.0
    position = None
    trades = []
    wins = 0
    losses = 0
    
    for i in range(100, len(data)):
        window = data.iloc[:i+1].copy()
        signal = strategy.generate_signal(window)
        
        current_price = window['close'].iloc[-1]
        
        if position is None and signal.signal_type != 0:
            side_name = "LONG" if signal.signal_type == 1 else "SHORT"
            position = {
                'type': signal.signal_type,
                'entry_price': current_price,
                'entry_time': window.index[-1],
                'stop_loss': signal.stop_loss,
                'take_profit': signal.take_profit,
                'amount': balance / current_price
            }
            logger.debug(
                f"OPEN {side_name} @ ${current_price:.2f} "
                f"(SL: ${signal.stop_loss:.2f}, TP: ${signal.take_profit:.2f})"
            )
        
        elif position:
            close_reason = None
            exit_price = current_price
            
            if signal.signal_type != 0:
                if (position['type'] == 1 and signal.signal_type == -1) or \
                   (position['type'] == -1 and signal.signal_type == 1):
                    close_reason = "Reverse Signal"
            
            if position['type'] == 1:
                if current_price <= position['stop_loss']:
                    close_reason = "Stop Loss"
                elif current_price >= position['take_profit']:
                    close_reason = "Take Profit"
            else:
                if current_price >= position['stop_loss']:
                    close_reason = "Stop Loss"
                elif current_price <= position['take_profit']:
                    close_reason = "Take Profit"
            
            if close_reason:
                if position['type'] == 1:
                    pnl = (exit_price - position['entry_price']) * position['amount']
                else:
                    pnl = (position['entry_price'] - exit_price) * position['amount']
                
                pnl_pct = (pnl / balance) * 100
                balance += pnl
                
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': window.index[-1],
                    'type': 'LONG' if position['type'] == 1 else 'SHORT',
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'balance': balance,
                    'reason': close_reason
                })
                
                logger.info(
                    f"CLOSE {close_reason}: ${position['entry_price']:.2f} → ${exit_price:.2f} | "
                    f"PnL: ${pnl:+.2f} ({pnl_pct:+.2f}%) | Balance: ${balance:.2f}"
                )
                
                position = None
    
    if not trades:
        logger.warning("No trades executed")
        return None
    
    total_trades = len(trades)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    profit = balance - 100.0
    profit_pct = (profit / 100.0) * 100
    
    logger.info(f"\n{'='*70}")
    logger.info(f"📊 BACKTEST RESULTS - {symbol} ({days} days)")
    logger.info(f"{'='*70}")
    logger.info(f"Initial Balance:  $100.00")
    logger.info(f"Final Balance:    ${balance:.2f}")
    logger.info(f"Profit:           ${profit:+.2f} ({profit_pct:+.2f}%)")
    logger.info(f"Total Trades:     {total_trades}")
    logger.info(f"Wins:             {wins}")
    logger.info(f"Losses:           {losses}")
    logger.info(f"Win Rate:         {win_rate:.1f}%")
    
    if total_trades > 0:
        avg_win = sum(t['pnl'] for t in trades if t['pnl'] > 0) / wins if wins > 0 else 0
        avg_loss = sum(t['pnl'] for t in trades if t['pnl'] < 0) / losses if losses > 0 else 0
        logger.info(f"Avg Win:          ${avg_win:.2f}")
        logger.info(f"Avg Loss:         ${avg_loss:.2f}")
        
        if avg_loss != 0:
            profit_factor = abs(avg_win * wins) / abs(avg_loss * losses)
            logger.info(f"Profit Factor:    {profit_factor:.2f}")
    
    logger.info(f"{'='*70}\n")
    
    return {
        'symbol': symbol,
        'days': days,
        'initial': 100.0,
        'final': balance,
        'profit': profit,
        'profit_pct': profit_pct,
        'trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'trades_data': trades
    }


async def main():
    logger.info("🧪 Testing Rule-Based Strategy on Real Historical Data (BTC 2024)\n")
    
    results = []
    
    result = await backtest_strategy("BTC/USDT", days=365, use_local=True)
    if result:
        results.append(result)
    
    if results:
        logger.info("\n" + "="*70)
        logger.info("💰 PROFIT PROJECTIONS")
        logger.info("="*70)
        
        for r in results:
            weekly_profit = (r['profit_pct'] / 30) * 7
            monthly_profit = r['profit_pct']
            
            logger.info(f"\n{r['symbol']}:")
            logger.info(f"  From $100 in 1 week:  ${100 + (weekly_profit/100*100):.2f} ({weekly_profit:+.1f}%)")
            logger.info(f"  From $100 in 1 month: ${100 + (monthly_profit/100*100):.2f} ({monthly_profit:+.1f}%)")
            
            if r['profit_pct'] > 0:
                year_projection = (1 + r['profit_pct']/100) ** 12 - 1
                logger.info(f"  Year projection:      +{year_projection*100:.0f}% (якщо так триматиметься)")


if __name__ == "__main__":
    asyncio.run(main())
