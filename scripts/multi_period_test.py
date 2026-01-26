import pandas as pd
import numpy as np
from pathlib import Path
from loguru import logger
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.rule_based import RuleBasedStrategy
from strategies.indicators import TechnicalIndicators
from config.constants import SignalType

logger.remove()
logger.add(sys.stderr, level="WARNING")


def load_data(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath)
    
    if 'Price' in df.columns and df.iloc[0]['Price'] == 'Ticker':
        df = df.iloc[2:].copy()
        df.columns = ['date', 'close', 'high', 'low', 'open', 'volume']
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        for col in ['close', 'high', 'low', 'open', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    else:
        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        if 'adj close' in df.columns:
            df = df.drop(columns=['adj close'])
    
    return df


def backtest_strategy(data: pd.DataFrame, initial_balance: float = 100.0) -> dict:
    strategy = RuleBasedStrategy()
    
    data = TechnicalIndicators.add_all_indicators(data.copy())
    data = data.dropna()
    
    if len(data) < 50:
        return None
    
    balance = initial_balance
    position = None
    trades = []
    balance_history = [balance]
    
    for i in range(50, len(data)):
        window = data.iloc[i-50:i+1].copy()
        current = window.iloc[-1]
        
        if position is None:
            signal = strategy.generate_signal(window)
            
            if signal and signal.signal_type in [1, -1]:
                position = {
                    'type': signal.signal_type,
                    'entry': current['close'],
                    'stop_loss': signal.stop_loss,
                    'take_profit': signal.take_profit,
                    'balance_at_entry': balance
                }
        else:
            price = current['close']
            pnl = 0
            closed = False
            
            if position['type'] == 1:
                if price <= position['stop_loss']:
                    pnl = (position['stop_loss'] - position['entry']) / position['entry']
                    closed = True
                elif price >= position['take_profit']:
                    pnl = (position['take_profit'] - position['entry']) / position['entry']
                    closed = True
            else:
                if price >= position['stop_loss']:
                    pnl = (position['entry'] - position['stop_loss']) / position['entry']
                    closed = True
                elif price <= position['take_profit']:
                    pnl = (position['entry'] - position['take_profit']) / position['entry']
                    closed = True
            
            if closed:
                trade_pnl = position['balance_at_entry'] * pnl
                balance += trade_pnl
                trades.append({
                    'pnl': trade_pnl,
                    'pnl_pct': pnl * 100,
                    'type': 'BUY' if position['type'] == 1 else 'SELL'
                })
                position = None
        
        balance_history.append(balance)
    
    if not trades:
        return None
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    
    total_wins = sum(t['pnl'] for t in wins) if wins else 0
    total_losses = abs(sum(t['pnl'] for t in losses)) if losses else 0.01
    
    balance_arr = np.array(balance_history)
    peak = np.maximum.accumulate(balance_arr)
    drawdown = (peak - balance_arr) / peak * 100
    max_drawdown = np.max(drawdown)
    
    return {
        'final_balance': balance,
        'profit_pct': (balance - initial_balance) / initial_balance * 100,
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(trades) * 100 if trades else 0,
        'avg_win': np.mean([t['pnl'] for t in wins]) if wins else 0,
        'avg_loss': np.mean([t['pnl'] for t in losses]) if losses else 0,
        'profit_factor': total_wins / total_losses if total_losses > 0 else 0,
        'max_drawdown': max_drawdown,
        'long_trades': len([t for t in trades if t['type'] == 'BUY']),
        'short_trades': len([t for t in trades if t['type'] == 'SELL'])
    }


def main():
    print("=" * 70)
    print("MULTI-PERIOD BACKTEST - RULE BASED STRATEGY")
    print("=" * 70)
    
    data_dir = Path("/app/data/local")
    
    test_files = [
        ("2022 BEAR (Daily)", "BTC-USD_2022_daily.csv", "BEAR"),
        ("2023 RECOVERY (Daily)", "BTC-USD_2023_daily.csv", "MIXED"),
        ("2024 BULL (Hourly)", "BTC-USD_2024-01-01_2024-12-31.csv", "BULL"),
        ("2025 CURRENT (Hourly)", "BTC-USD_2025-01-01_2025-12-31.csv", "CURRENT"),
        ("RECENT 700d (Hourly)", "BTC-USD_recent_1h.csv", "MIXED"),
    ]
    
    results = []
    
    for name, filename, market_type in test_files:
        filepath = data_dir / filename
        if not filepath.exists():
            print(f"\n{name}: File not found, skipping...")
            continue
        
        print(f"\n{'='*70}")
        print(f"Testing: {name}")
        print(f"{'='*70}")
        
        data = load_data(str(filepath))
        print(f"Data: {len(data)} candles | {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")
        print(f"Price: ${data['close'].iloc[0]:.0f} -> ${data['close'].iloc[-1]:.0f}")
        
        result = backtest_strategy(data)
        
        if result is None:
            print("Not enough data or no trades")
            continue
        
        result['name'] = name
        result['market_type'] = market_type
        results.append(result)
        
        print(f"\nResults:")
        print(f"  Profit:        {result['profit_pct']:+.1f}%")
        print(f"  Trades:        {result['total_trades']} (Long: {result['long_trades']}, Short: {result['short_trades']})")
        print(f"  Win Rate:      {result['win_rate']:.1f}%")
        print(f"  Profit Factor: {result['profit_factor']:.2f}")
        print(f"  Max Drawdown:  {result['max_drawdown']:.1f}%")
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\n{'Period':<25} {'Profit':>10} {'Win%':>8} {'PF':>6} {'MaxDD':>8} {'Market':>8}")
    print("-" * 70)
    
    for r in results:
        print(f"{r['name']:<25} {r['profit_pct']:>+9.1f}% {r['win_rate']:>7.1f}% {r['profit_factor']:>6.2f} {r['max_drawdown']:>7.1f}% {r['market_type']:>8}")
    
    print("\n" + "=" * 70)
    print("READINESS ASSESSMENT")
    print("=" * 70)
    
    profitable_periods = len([r for r in results if r['profit_pct'] > 0])
    avg_profit = np.mean([r['profit_pct'] for r in results]) if results else 0
    avg_win_rate = np.mean([r['win_rate'] for r in results]) if results else 0
    avg_pf = np.mean([r['profit_factor'] for r in results]) if results else 0
    max_dd = max([r['max_drawdown'] for r in results]) if results else 0
    
    print(f"\nProfitable periods: {profitable_periods}/{len(results)}")
    print(f"Average profit:     {avg_profit:+.1f}%")
    print(f"Average win rate:   {avg_win_rate:.1f}%")
    print(f"Average PF:         {avg_pf:.2f}")
    print(f"Worst drawdown:     {max_dd:.1f}%")
    
    print("\n" + "-" * 70)
    
    ready = (
        profitable_periods >= len(results) * 0.6 and
        avg_pf >= 1.0 and
        max_dd < 50
    )
    
    if ready:
        print("✅ STRATEGY APPEARS VIABLE FOR PAPER TRADING")
        print("   Recommend: 2-4 weeks paper trading before real money")
    else:
        print("❌ STRATEGY NOT READY FOR REAL TRADING")
        if profitable_periods < len(results) * 0.6:
            print(f"   - Only {profitable_periods}/{len(results)} periods profitable")
        if avg_pf < 1.0:
            print(f"   - Profit factor {avg_pf:.2f} < 1.0")
        if max_dd >= 50:
            print(f"   - Max drawdown {max_dd:.1f}% too high")


if __name__ == "__main__":
    main()
