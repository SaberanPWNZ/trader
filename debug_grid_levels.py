import json

with open('data/grid_state.json', 'r') as f:
    state = json.load(f)
    
print(f"Initial balance: ${state.get('initial_balance', 0):.2f}")
print(f"Started at: {state.get('started_at', 'N/A')}")
print()

symbols_data = state.get('symbols', {})
for symbol, data in symbols_data.items():
    print(f"\n{symbol}:")
    print(f"  Initialized: {data.get('initialized', False)}")
    print(f"  Range: ${data.get('lower_price', 0):.2f} - ${data.get('upper_price', 0):.2f}")
    print(f"  Center: ${data.get('center_price', 0):.2f}")
    print(f"  Spacing: ${data.get('grid_spacing', 0):.2f}")
    
    levels = data.get('grid_levels', [])
    print(f"  Total levels: {len(levels)}")
    
    buy_levels = [l for l in levels if l['side'] == 'buy' and not l['filled']]
    sell_levels = [l for l in levels if l['side'] == 'sell' and not l['filled']]
    
    if buy_levels:
        buy_prices = [l['price'] for l in buy_levels]
        print(f"  Active BUY levels ({len(buy_levels)}): ${min(buy_prices):.2f} - ${max(buy_prices):.2f}")
    
    if sell_levels:
        sell_prices = [l['price'] for l in sell_levels]
        print(f"  Active SELL levels ({len(sell_levels)}): ${min(sell_prices):.2f} - ${max(sell_prices):.2f}")
