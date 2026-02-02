#!/usr/bin/env python3
"""Reset grid trading data for new experiment with $1000"""

import os
import json
from datetime import datetime

DATA_DIR = "data"

def reset_grid_data():
    """Reset all grid trading data files"""
    
    # Reset grid_trades.csv
    trades_file = os.path.join(DATA_DIR, "grid_trades.csv")
    with open(trades_file, 'w') as f:
        f.write("timestamp,symbol,side,price,amount,value,realized_pnl,unrealized_pnl,balance,total_value,roi_percent\n")
    print(f"✅ Reset {trades_file}")
    
    # Reset grid_snapshots.csv
    snapshots_file = os.path.join(DATA_DIR, "grid_snapshots.csv")
    with open(snapshots_file, 'w') as f:
        f.write("timestamp,balance,realized_pnl,unrealized_pnl,total_value,roi_percent,total_trades,win_rate,btc_price,eth_price,report_type\n")
    print(f"✅ Reset {snapshots_file}")
    
    # Reset grid_rebalances.csv
    rebalances_file = os.path.join(DATA_DIR, "grid_rebalances.csv")
    try:
        os.remove(rebalances_file)
    except:
        pass
    with open(rebalances_file, 'w') as f:
        f.write("timestamp,symbol,reason,old_range,new_range,open_positions,unrealized_pnl,positions_profitable,forced\n")
    print(f"✅ Reset {rebalances_file}")
    
    # Reset grid_state.json
    state_file = os.path.join(DATA_DIR, "grid_state.json")
    try:
        os.remove(state_file)
    except:
        pass
    state_data = {
        "initial_balance": 1000.0,
        "started_at": datetime.utcnow().isoformat()
    }
    with open(state_file, 'w') as f:
        json.dump(state_data, f)
    print(f"✅ Reset {state_file}")
    
    print("\n🎉 All grid data reset successfully!")
    print(f"💰 Starting fresh with $1000.00")
    print(f"📅 Start time: {state_data['started_at']}")

if __name__ == "__main__":
    reset_grid_data()
