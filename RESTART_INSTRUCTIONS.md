# 🔄 Restart Grid Trading - New $1000 Experiment

## Current Status
✅ Code updated - market falling protection added
✅ Initial balance changed to $1000  
✅ Data files reset (trades.csv, state.json)
⚠️ Terminal malfunction detected - manual restart required

## Market Falling Protection Added
- **Trigger**: Unrealized PnL < -3%
- **Action**: Pause all BUY orders for 30 minutes
- **Alert**: Telegram notification sent
- **Resume**: Automatic after pause period

## Manual Restart Commands

Open a **NEW terminal window** and run:

```bash
cd /home/admin/projects/trader

# Stop containers
docker compose down

# Rebuild with new code
docker compose build trading-bot

# Start fresh
docker compose up -d

# Check status
docker ps | grep trader

# View logs
docker logs -f crypto-trading-bot
```

## Expected Result
- Grid trading starts with $1000 balance
- Market falling protection active
- New data files created
- Telegram alerts working

## Files Modified
1. `config/settings.py` - Disabled portfolio protection, increased thresholds
2. `paper/grid_simulator.py` - Added market falling pause logic
3. `data/grid_state.json` - Reset to $1000 initial balance
4. `data/grid_trades.csv` - Cleared all historical trades

## Backups Created
- `data/grid_trades_backup_20260201_184959.csv`
- `data/grid_snapshots_backup_20260201_184959.csv`  
- `data/grid_rebalances_backup_20260201_184959.csv`
- `data/grid_state_backup_20260201_184959.json`
