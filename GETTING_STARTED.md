# Getting Started - PyBroker Trading Bot

## ✅ Pre-Launch Checklist

### 1. Installation
- [ ] Clone/extract project files
- [ ] Install Python 3.11+ (or check: `python --version`)
- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Verify PyBroker: `pip show pybroker`

### 2. Configuration
- [ ] Copy `.env.example` to `.env`
- [ ] Add Binance API keys (if doing live trading):
  - [ ] `BINANCE_API_KEY`
  - [ ] `BINANCE_API_SECRET`
- [ ] Add Telegram bot credentials (optional):
  - [ ] `TELEGRAM_BOT_TOKEN`
  - [ ] `TELEGRAM_CHAT_ID`

### 3. Directory Structure
- [ ] Verify `/data` directory exists
- [ ] Verify `/models` directory exists
- [ ] Verify `/logs` directory exists

### 4. First Run - Test Installation
```bash
# Should show help without errors
python main.py --help
```

---

## 🚀 Getting Started in 5 Steps

### Step 1: Run Your First Backtest
```bash
python main.py backtest --symbol BTC/USDT --strategy rule_based
```

**Expected output:**
- Download YFinance data
- Run backtest
- Show performance report
- No errors

### Step 2: Try Walk-Forward Validation
```bash
python main.py backtest --symbol BTC/USDT --walk-forward
```

**What to look for:**
- Multiple fold results (typically 5-10)
- Consistent win rates across folds
- Realistic returns (10-30% annually)

### Step 3: Train an AI Model
```bash
python main.py train --symbol BTC/USDT --start-date 2024-01-01 --end-date 2024-06-01
```

**Expected output:**
- Model training progress
- Training completion message
- Model saved to `models/`

### Step 4: Backtest with AI Model
```bash
python main.py backtest --symbol BTC/USDT --strategy ai --model models/BTC_USDT_*.pkl
```

**What to compare:**
- AI strategy vs rule-based
- Win rates
- Sharpe ratios

### Step 5: Paper Trade (Simulated)
```bash
python main.py paper --symbol BTC/USDT --strategy rule_based
```

**What to monitor:**
- Check logs in `logs/` directory
- Verify trades are being generated
- Check if Telegram alerts work (if configured)

---

## 📖 Reading Guide

**Start Here:**
1. `MIGRATION_COMPLETE.md` - Overview of what changed
2. `QUICKSTART.md` - Detailed command examples
3. `PYBROKER_MIGRATION.md` - Technical deep dive

**Deep Dives:**
- Backtesting: See `backtesting/pybroker_engine.py`
- Strategies: See `strategies/rule_based_pb.py` and `strategies/ai_strategy_pb.py`
- Risk Management: See `risk/manager.py`
- Monitoring: See `monitoring/`

---

## 🔧 Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'pybroker'"
**Solution:**
```bash
pip install pybroker --upgrade
pip install -r requirements.txt
```

### Issue: "No data available for symbol"
**Solution:**
- Check symbol format (use: BTC/USDT not BTCUSDT)
- Verify YFinance has data: `python -c "import yfinance as yf; yf.download('BTC-USD', '2024-01-01')"`

### Issue: "Strategy build failed"
**Solution:**
- Check Python version (need 3.11+)
- Verify strategy file syntax
- Check imports in strategy file

### Issue: "Telegram alerts not sending"
**Solution:**
- Enable in settings: `settings.monitoring.telegram_enabled = True`
- Verify bot token and chat ID in .env
- Test manually: `curl https://api.telegram.org/bot{TOKEN}/getMe`

### Issue: Memory error during walk-forward
**Solution:**
- Reduce `walk_forward_periods` (default 252)
- Reduce date range
- Use rule-based strategy (faster than AI)

---

## 💡 Common Tasks

### Backtest Multiple Symbols
```bash
# BTC
python main.py backtest --symbol BTC/USDT

# ETH
python main.py backtest --symbol ETH/USDT

# Or edit config and run:
python main.py backtest --symbol BNB/USDT
```

### Change Risk Parameters
Edit `config/settings.py`:
```python
settings.risk.max_daily_loss = 0.10  # Change from 0.05
settings.risk.max_position_size = 0.50  # Change from 0.30
```

### Adjust Strategy Parameters
Edit `config/settings.py`:
```python
settings.strategy.ema_fast = 15  # Default: 20
settings.strategy.ema_slow = 250  # Default: 200
settings.strategy.rsi_overbought = 75  # Default: 70
```

### Enable Detailed Logging
Edit `config/settings.py`:
```python
settings.monitoring.log_level = "DEBUG"  # More verbose output
```

### Check Previous Backtests
View results in `logs/` directory:
```bash
ls -lh logs/
tail -f logs/*.log  # Real-time log watching
```

---

## 🎯 Recommended Workflow

### Week 1: Learning
- [x] Run backtests on different symbols
- [x] Experiment with date ranges
- [x] Try walk-forward validation
- [x] Read through strategy code

### Week 2: Optimization
- [x] Adjust risk parameters
- [x] Optimize strategy parameters
- [x] Compare rule-based vs AI strategies
- [x] Check performance metrics

### Week 3: Model Training
- [x] Train AI models on different symbols
- [x] Validate models with walk-forward
- [x] Compare AI vs rule-based backtest results
- [x] Save best models

### Week 4: Paper Trading
- [x] Run paper trading (simulated)
- [x] Monitor for 1-2 weeks
- [x] Verify Telegram alerts
- [x] Check log files

### Week 5+: Live Trading
- [x] Start with small balance (testnet first)
- [x] Monitor closely (check logs)
- [x] Verify kill switch works
- [x] Scale up gradually

---

## 📊 Performance Expectations

### Good Backtest Results
- **Win Rate:** 50-65%
- **Annual Return:** 15-50% (realistic)
- **Sharpe Ratio:** 1.0-2.0
- **Max Drawdown:** 5-15%
- **Profit Factor:** 1.5-3.0

### Warning Signs
- Win rate < 40% → strategy too conservative
- Win rate > 80% → possible overfitting
- Sharpe < 0.5 → poor risk-adjusted returns
- Max drawdown > 30% → too much risk

---

## 🔐 Security Best Practices

### Before Going Live:
- [ ] Never commit `.env` to git
- [ ] Use testnet first (set `testnet: true` in config)
- [ ] Start with small amounts
- [ ] Test emergency kill switch
- [ ] Set `max_daily_loss` conservatively
- [ ] Enable Telegram alerts
- [ ] Monitor logs regularly

### Live Trading Safeguards:
```python
# In config/settings.py for live trading:
settings.risk.max_daily_loss = 0.05  # 5%
settings.risk.max_drawdown = 0.10  # 10%
settings.risk.kill_switch_enabled = True  # Always ON
settings.exchange.testnet = False  # Only when ready!
```

---

## 📞 Getting Help

**Documentation:**
- See `QUICKSTART.md` for command examples
- See `PYBROKER_MIGRATION.md` for technical details
- See `MIGRATION_COMPLETE.md` for what changed

**Debugging:**
- Check `logs/` directory for detailed output
- Increase log level: `settings.monitoring.log_level = "DEBUG"`
- Test commands manually first

**External Resources:**
- PyBroker: https://pybroker.io/
- YFinance: https://github.com/ranaroussi/yfinance

---

## ✨ Next Steps After First Run

1. **Celebrate!** 🎉 - You have a working bot
2. **Understand** - Read through the backtest results
3. **Experiment** - Try different parameters
4. **Optimize** - Use walk-forward to find best settings
5. **Train** - Create AI models
6. **Test** - Paper trade for a month
7. **Deploy** - Go live (with caution!)

---

## 🚨 Critical Reminders

⚠️ **Always Test First**
- Never go live without thorough testing
- Use testnet before real money
- Start with small amounts

⚠️ **Monitor Closely**
- Check logs regularly
- Set up Telegram alerts
- Be ready to shut down if needed

⚠️ **Understand the Code**
- Read strategy implementations
- Know your risk limits
- Understand what "kill switch" does

---

## 🎓 Learning Resources

### Quick Tutorials (5 min each):
1. Basic backtest
2. Walk-forward validation
3. AI model training
4. Paper trading setup

### In-Depth Guides (30 min each):
1. Strategy customization
2. Risk management tuning
3. Parameter optimization
4. Live trading setup

### Advanced Topics:
1. Multiple symbol strategies
2. Portfolio management
3. Custom indicators
4. Machine learning features

---

**Ready to start?** 🚀

```bash
# Your first backtest:
python main.py backtest --symbol BTC/USDT
```

Good luck! 📈
