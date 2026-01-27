# Grid Trading Guide

## 📊 Quick Status Check

```bash
python main.py status
```

Shows current balance, PnL, ROI, and number of trades.

## 🚀 Starting Grid Trading

```bash
python main.py grid --initial-balance 100
```

Default: $100 balance, BTC/USDT + ETH/USDT

## 📈 Detailed Analysis

```bash
python analyze_grid.py
```

Shows:
- Daily summary with correct balance
- Trade breakdown by symbol
- Performance metrics
- Last 10 trades
- Scheduled report history

## 📊 Live Monitoring

```bash
./monitor_grid.sh
```

Real-time updates every 30 seconds with:
- Recent trades
- Profit summary
- Process status
- Current prices

## 💰 Understanding The Data

### Correct Balance Calculation

- **Initial Balance:** $100 (locked in grid)
- **Realized PnL:** Profit from closed trades
- **Unrealized PnL:** Profit/loss from open positions
- **Total Value:** Initial + Realized + Unrealized

### Example Reading

```
Initial: $100.00
Realized: $0.50   (closed trades made $0.50)
Unrealized: -$0.20  (open positions down $0.20)
Total: $100.30   (actual portfolio value)
ROI: +0.30%
```

## 📁 Data Files

- `data/grid_trades.csv` - Every trade with timestamp, price, PnL
- `data/grid_snapshots.csv` - Periodic snapshots (12h, 24h)

## 🔔 Telegram Reports

- **Trade notifications:** Every BUY/SELL
- **12-hour report:** Summary every 12h
- **24-hour report:** Daily summary

## 🔧 Process Management

Check if running:
```bash
ps aux | grep "python main.py grid"
```

Restart:
```bash
kill <PID>
nohup python main.py grid --initial-balance 100 > logs/grid_output.log 2>&1 &
```

View logs:
```bash
tail -f logs/grid_output.log
```

## 📌 Important Notes

1. **Balance column in CSV is FIXED at initial amount** - ignore it
2. **Use Total Value for real balance** - Initial + Realized + Unrealized
3. **Grid works on price crossings** - needs volatility for trades
4. **Check interval: 60 seconds** - trades when price crosses grid levels
5. **Reports show CORRECT values** - after bug fix (Jan 27, 2026)

## 🎯 Daily Routine

Morning:
```bash
python main.py status
```

Detailed check:
```bash
python analyze_grid.py
```

Continuous monitoring:
```bash
./monitor_grid.sh
```
