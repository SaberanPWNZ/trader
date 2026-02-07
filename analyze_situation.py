import pandas as pd
from datetime import datetime

trades_df = pd.read_csv('data/grid_trades.csv')

if len(trades_df) > 0:
    last_trade = trades_df.iloc[-1]
    first_trade = trades_df.iloc[0]
    
    print("=" * 60)
    print("АНАЛІЗ ПОТОЧНОЇ СИТУАЦІЇ")
    print("=" * 60)
    
    print(f"\nВСЬОГО УГОД: {len(trades_df)}")
    print(f"\nПерша угода: {first_trade['timestamp']}")
    print(f"Остання угода: {last_trade['timestamp']}")
    
    time_first = datetime.fromisoformat(first_trade['timestamp'])
    time_last = datetime.fromisoformat(last_trade['timestamp'])
    hours_diff = (datetime.now() - time_last).total_seconds() / 3600
    
    print(f"\n⏰ Останя угода була {hours_diff:.1f} годин тому")
    
    print(f"\n💰 ПОТОЧНИЙ СТАН:")
    print(f"   Balance: ${last_trade['balance']:.2f}")
    print(f"   Total Value: ${last_trade['total_value']:.2f}")
    print(f"   ROI: {last_trade['roi_percent']:.2f}%")
    print(f"   Unrealized PnL: ${last_trade['unrealized_pnl']:.2f}")
    
    print(f"\n📊 ЦІ КУПІВЛІ:")
    buy_trades = trades_df[trades_df['side'] == 'BUY']
    for symbol in buy_trades['symbol'].unique():
        symbol_trades = buy_trades[buy_trades['symbol'] == symbol]
        avg_price = symbol_trades['price'].mean()
        total_amount = symbol_trades['amount'].sum()
        total_value = symbol_trades['value'].sum()
        print(f"   {symbol}: {len(symbol_trades)} позицій, avg ${avg_price:.2f}, вкладено ${total_value:.2f}")
    
    print(f"\n🔴 РИНОК ЗАРАЗ (з останніх логів):")
    print(f"   BTC: ~$65,100 (куплено по ~$69,200 → -5.9%)")
    print(f"   ETH: ~$1,915 (куплено по ~$2,041 → -6.2%)")
    print(f"   SOL: ~$79.6 (куплено по ~$88.6 → -10.1%)")
    print(f"   DOGE: ~$0.093 (куплено по ~$0.098 → -5.1%)")
    
    if last_trade['roi_percent'] <= -5.0:
        print(f"\n⚠️  КРИТИЧНО! ROI = {last_trade['roi_percent']:.2f}%")
        print(f"   Stop-loss повинен був спрацювати при -5%!")
        print(f"   Але торгівля досі працює...")
    elif last_trade['roi_percent'] <= -3.0:
        print(f"\n⚠️  УВАГА! ROI = {last_trade['roi_percent']:.2f}%")
        print(f"   Наближаємося до stop-loss -5%")
    else:
        print(f"\n✅ ROI = {last_trade['roi_percent']:.2f}% (в межах норми)")
    
    if hours_diff > 12:
        print(f"\n⚠️  ПРОБЛЕМА: Немає нових угод {hours_diff:.1f} годин!")
        print(f"   Можлива причина: grid рівні занадто далеко від поточних цін")
else:
    print("Немає угод в grid_trades.csv")
