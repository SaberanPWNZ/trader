# Quick Start Guide: New Features

## 🚀 Getting Started in 5 Minutes

### 1. Configure Environment
```bash
# Copy and edit .env file
cp .env.example .env
nano .env

# Required variables:
POSTGRES_PASSWORD=your_secure_password
DATABASE_URL=postgresql+asyncpg://trader:${POSTGRES_PASSWORD}@postgres:5240/trading_bot
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 2. Start Services
```bash
# Build and start everything
make run

# Or start step by step:
make postgres-setup   # Start database first
make grid-start       # Start grid trading
```

### 3. Check Health
```bash
make health-check

# Expected output:
# {
#   "status": "healthy",
#   "database": "connected",
#   "pool_size": 10
# }
```

### 4. Monitor Grid Trading
```bash
# Watch logs in real-time
make grid-logs

# You'll see:
# - Grid initialization
# - Trade fills
# - Rebalancing countdown: "Next rebalance in 11.5h"
# - Rebalancing events: "🔄 REBALANCING BTC/USDT..."
```

## 📊 View Results

### Check Rebalancing History
```bash
# View all rebalances
cat data/grid_rebalances.csv | column -t -s,

# Or prettier:
sqlite3 -csv -header data/grid_rebalances.csv "SELECT * FROM grid_rebalances ORDER BY timestamp DESC LIMIT 10"
```

### Check Trade History
```bash
# All grid trades
cat data/grid_trades.csv | column -t -s,

# Summary stats
python -c "
import pandas as pd
df = pd.read_csv('data/grid_trades.csv')
print(f'Total Trades: {len(df)}')
print(f'Total PnL: ${df[\"realized_pnl\"].sum():.2f}')
print(f'Win Rate: {(df[\"realized_pnl\"] > 0).mean() * 100:.1f}%')
"
```

## 🔄 Common Operations

### Restart Grid Trading
```bash
make grid-restart
```

### Change Rebalance Intervals
Edit `config/settings.py`:
```python
@dataclass
class GridConfig:
    rebalance_interval_hours: dict = {
        "BTC/USDT": 6.0,   # Change to 6 hours
        "DOGE/USDT": 3.0,  # More frequent for DOGE
    }
```

Then restart:
```bash
make grid-restart
```

### Force Manual Rebalance
Currently not implemented via CLI, but you can:
1. Set `force_rebalance_after_hours: float = 0.1` (6 minutes)
2. Restart grid trading
3. Wait 6 minutes
4. Revert the setting

### Migrate Existing SQLite Data
```bash
# If you have data/learning.db with existing trades
make migrate-db

# Follow prompts:
# - Creates backup
# - Migrates all tables
# - Verifies row counts
```

## 🐛 Troubleshooting

### PostgreSQL won't start
```bash
# Check logs
make postgres-logs

# Common fix: Remove old volume
docker compose down -v
docker volume rm trader_postgres-data
make postgres-setup
```

### Grid trading not rebalancing
```bash
# Check logs for countdown
make grid-logs | grep "Next rebalance"

# Check if conditions are met
make grid-logs | grep "waiting for profit"

# Force by setting cooldown to 0 in config/settings.py:
rebalance_cooldown_minutes: int = 0
```

### Health check fails
```bash
# Test directly
curl http://localhost:8000/health

# If connection refused:
docker compose ps health-api  # Check if running
docker compose logs health-api  # Check errors
```

### Telegram alerts not sending
```bash
# Check environment variables
docker compose exec grid-trading env | grep TELEGRAM

# Test manually
docker compose exec grid-trading python -c "
import asyncio
from monitoring.alerts import telegram
asyncio.run(telegram.send_message('Test message'))
"
```

## 📈 Understanding Rebalance Reasons

**Messages you'll see:**

1. **"Next rebalance in X.Xh"**
   - Normal - countdown to next scheduled rebalance
   - Action: None, system is working

2. **"SCHEDULED: 12.5h passed. All 3 positions profitable ($15.42)"**
   - Time interval reached + positions profitable
   - Action: Automatic rebalance executed

3. **"12.5h passed but waiting for profit: 2/3 positions unprofitable ($-5.21)"**
   - Time reached but positions in loss
   - Action: Waiting for profit (if wait_for_profit=True)

4. **"EMERGENCY: Price breakout ($92500). All positions profitable ($20.15)"**
   - Price moved beyond grid range
   - Action: Immediate rebalance

5. **"FORCED after 24.2h: Price breakout. 1/2 positions unprofitable ($-3.50)"**
   - Out of range for 24+ hours
   - Action: Forced rebalance despite loss

## 🎯 Performance Tips

### Optimize Rebalance Intervals
- **Low volatility** (BTC, ETH): 12-24 hours
- **Medium volatility** (SOL, XRP): 6-12 hours  
- **High volatility** (DOGE, meme coins): 3-6 hours

### Adjust Grid Width (ATR Multiplier)
Edit `strategies/grid.py`:
```python
def initialize_grid(self, current_price: float, atr: float, total_investment: float):
    atr_multiplier = 5.0  # Wider grid (default: 3.0)
```

Wider grid = Less rebalancing = Lower transaction costs

### Monitor P&L
```bash
# Real-time P&L
watch -n 5 'tail -1 data/grid_trades.csv | cut -d, -f7-10'

# Daily summary
make logs-grid | grep "12h report"
```

## 🔐 Security Notes

- PostgreSQL password in `.env` - keep secure
- Database port 5432 exposed for development - close in production
- Health API port 8000 - add authentication if exposed

## ✅ Verification Checklist

After deployment, verify:
- [ ] `make health-check` returns healthy
- [ ] `make grid-logs` shows initialization
- [ ] Grid trades appearing in `data/grid_trades.csv`
- [ ] Telegram alerts received
- [ ] PostgreSQL accepting connections
- [ ] All 5 containers running: `docker compose ps`
- [ ] Health API accessible: `curl localhost:8000/health`

## 📞 Support

**Logs Location:**
- Grid: `make grid-logs`
- Database: `make postgres-logs`  
- Health: `make logs-health`
- All: `make logs-all`

**Data Files:**
- Trades: `data/grid_trades.csv`
- Rebalances: `data/grid_rebalances.csv`
- Snapshots: `data/grid_snapshots.csv`

**Common Commands:**
```bash
make help          # See all commands
make health-check  # Check system health
make grid-logs     # Monitor grid trading
make grid-restart  # Restart grid trading
make migrate-db    # Migrate to PostgreSQL
```

---
**Ready to trade? Run `make run` and watch the magic happen! 🚀**
