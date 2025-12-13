# PyBroker Trading Bot - Quick Start Guide

## Installation & Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create `.env` file:
```env
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
DATABASE_URL=sqlite:///data/trading.db
```

### 3. Create Data & Models Directories
```bash
mkdir -p data models logs
```

---

## Running the Bot

### Backtest Mode (Rule-Based Strategy)

**Basic backtest:**
```bash
python main.py backtest --symbol BTC/USDT --strategy rule_based
```

**With custom dates:**
```bash
python main.py backtest \
  --symbol BTC/USDT \
  --strategy rule_based \
  --start-date 2024-01-01 \
  --end-date 2024-12-01
```

**With custom balance:**
```bash
python main.py backtest \
  --symbol BTC/USDT \
  --initial-balance 50000
```

### Backtest Mode (AI Strategy)

**With pre-trained model:**
```bash
python main.py backtest \
  --symbol BTC/USDT \
  --strategy ai \
  --model models/btc_model.pkl
```

### Walk-Forward Validation

**Run 5+ folds of walk-forward testing:**
```bash
python main.py backtest \
  --symbol BTC/USDT \
  --strategy rule_based \
  --walk-forward
```

Output:
```
WF Fold 1: Win rate=45.0%, Return=12.50%
WF Fold 2: Win rate=50.0%, Return=-5.20%
WF Fold 3: Win rate=42.0%, Return=8.75%
...
```

### Paper Trading

**Start paper trading (last 90 days of data):**
```bash
python main.py paper \
  --symbol BTC/USDT \
  --strategy rule_based
```

**With AI strategy:**
```bash
python main.py paper \
  --symbol BTC/USDT \
  --strategy ai \
  --model models/btc_model.pkl
```

### Live Trading (Testnet)

**⚠️ DANGEROUS - Real money mode:**
```bash
python main.py live \
  --strategy rule_based \
  --confirm
```

**With AI strategy:**
```bash
python main.py live \
  --strategy ai \
  --model models/btc_model.pkl \
  --confirm
```

### Train AI Model

**Train on historical data:**
```bash
python main.py train \
  --symbol BTC/USDT \
  --start-date 2024-01-01 \
  --end-date 2024-10-01
```

**Save to custom path:**
```bash
python main.py train \
  --symbol BTC/USDT \
  --start-date 2024-01-01 \
  --end-date 2024-10-01 \
  --output models/my_custom_model.pkl
```

---

## Configuration

### Main Settings (`config/settings.py`)

#### Trading Parameters
```python
settings.trading.symbols = ["BTC/USDT", "ETH/USDT"]
settings.trading.default_timeframe = "1h"
settings.trading.mode = "paper"  # paper, live, backtest
```

#### Risk Management
```python
settings.risk.max_risk_per_trade = 0.02  # 2%
settings.risk.max_daily_loss = 0.05  # 5%
settings.risk.max_drawdown = 0.10  # 10%
settings.risk.max_position_size = 0.30  # 30%
```

#### Backtest Settings
```python
settings.backtest.start_date = "2024-01-01"
settings.backtest.end_date = "2024-12-01"
settings.backtest.initial_balance = 10000.0
settings.backtest.trading_fee = 0.001  # 0.1%
```

#### PyBroker Settings
```python
settings.pybroker.commission = 0.001  # 0.1%
settings.pybroker.slippage = 0.0005  # 0.05%
settings.pybroker.walk_forward_periods = 252  # 1 year
settings.pybroker.walk_forward_test_size = 63  # 1 quarter
```

#### Strategy Parameters
```python
settings.strategy.ema_fast = 20
settings.strategy.ema_medium = 50
settings.strategy.ema_slow = 200
settings.strategy.rsi_period = 14
settings.strategy.macd_fast = 12
```

### Symbol Mapping

Convert crypto pairs to YFinance format automatically:
```python
yf_symbol = settings.get_symbol_for_pybroker("BTC/USDT")  # → "BTC-USD"
```

---

## Understanding Backtest Output

### Sample Output
```
╔═══════════════════════════════════════════════════════════╗
║              BACKTEST PERFORMANCE REPORT                  ║
╠═══════════════════════════════════════════════════════════╣
║ Strategy:           RuleBasedStrategy                     ║
║ Period:             2024-01-01 to 2024-12-01              ║
║                                                           ║
║ SUMMARY                                                   ║
║ ─────────────────────────────────────────────────────── ║
║ Total Trades:       45                                    ║
║ Winning Trades:     27                                    ║
║ Losing Trades:      18                                    ║
║ Win Rate:           60.0%                                 ║
║                                                           ║
║ PERFORMANCE                                               ║
║ ─────────────────────────────────────────────────────── ║
║ Initial Balance:    $10,000.00                            ║
║ Final Balance:      $12,500.00                            ║
║ Total Return:       25.00%                                ║
║ Total PnL:          $2,500.00                             ║
║                                                           ║
║ RISK METRICS                                              ║
║ ─────────────────────────────────────────────────────── ║
║ Sharpe Ratio:       1.45                                  ║
║ Max Drawdown:       8.2%                                  ║
║ Profit Factor:      2.15                                  ║
╚═══════════════════════════════════════════════════════════╝
```

### Key Metrics Explained

| Metric | Meaning | Good Range |
|--------|---------|------------|
| Win Rate | % of profitable trades | > 50% |
| Total Return | % gain/loss | > 10% (annually) |
| Sharpe Ratio | Risk-adjusted return | > 1.0 |
| Max Drawdown | Largest peak-to-trough loss | < 20% |
| Profit Factor | Gross profit / Gross loss | > 1.5 |

---

## Monitoring & Alerts

### Telegram Notifications

Bot sends alerts for:
- **Trade Opened** - Entry price, size, side (🟢 long / 🔴 short)
- **Trade Closed** - Exit price, PnL, reason
- **Risk Alert** - Daily loss, drawdown, execution errors
- **Kill Switch** - Emergency shutdown activated
- **System Status** - Online/offline notifications

### Logging

Logs are written to:
- **Console** - Real-time output with loguru formatting
- **File** - `logs/` directory with timestamp
- **Database** - Trading events (if configured)

### Example Log Output
```
2024-01-15 14:30:45 | INFO     | Trade opened: BTC/USDT long 0.5 @ 45000.00
2024-01-15 14:35:20 | INFO     | Trade closed: BTC/USDT long 0.5 @ 45500.00 PnL=250.00
2024-01-15 14:40:10 | WARNING  | Pre-trade check failed for ETH/USDT: Max daily loss exceeded
```

---

## Strategies

### Rule-Based Strategy

Trades on technical indicators:
- **Buy Signal**: EMA20 > EMA50 > EMA200 AND RSI < 70 AND MACD crossover
- **Sell Signal**: EMA20 < EMA50 OR RSI > 70 OR MACD divergence
- **Entry**: When all conditions met
- **Exit**: Risk-managed via ATR-based stop loss

Config:
```python
settings.strategy.ema_fast = 20
settings.strategy.rsi_overbought = 70
settings.strategy.rsi_oversold = 30
```

### AI Strategy

Trades on machine learning predictions:
- **Model**: XGBoost or Random Forest
- **Features**: Technical indicators + momentum + volatility
- **Prediction**: Binary classification (Buy/Sell)
- **Confidence**: Requires > 60% (configurable)
- **Training**: Uses walk-forward validation

Train & use:
```bash
# Train model
python main.py train --symbol BTC/USDT --output models/btc_model.pkl

# Backtest with model
python main.py backtest --symbol BTC/USDT --strategy ai --model models/btc_model.pkl

# Trade with model
python main.py paper --symbol BTC/USDT --strategy ai --model models/btc_model.pkl
```

---

## Risk Management

### Position Sizing

Automatic position sizing based on:
- Account balance
- Risk per trade (default 2%)
- Stop loss distance
- Available margin

Example:
```
Account: $10,000
Risk per trade: 2% = $200
Stop loss: 5% below entry
Position size: 200 / 0.05 = 4,000 (0.4 BTC @ $10k)
```

### Risk Limits

**Hard Stops:**
- Max consecutive losses: 3 trades
- Max daily loss: 5% of balance
- Max account drawdown: 10%
- Kill switch on breach

**Position Limits:**
- Max position size: 30% of portfolio
- Max symbol exposure: 50% of portfolio
- Max leverage: 1.0x (no margin)

### Configuration

```python
settings.risk.max_risk_per_trade = 0.02
settings.risk.max_daily_loss = 0.05
settings.risk.max_drawdown = 0.10
settings.risk.max_position_size = 0.30
settings.risk.max_consecutive_losses = 3
settings.risk.kill_switch_enabled = True
```

---

## Data Sources

### Backtesting & Paper Trading
- **Source**: YFinance
- **Data**: Daily/Intraday OHLCV (depending on timeframe)
- **Lag**: Real-time within YFinance update delay (typically < 15 min)
- **Symbols**: All major crypto pairs (BTC, ETH, etc.)

### Live Trading
- **Source**: Binance (configurable to any ccxt exchange)
- **Data**: Real-time order book, trades, balances
- **Lag**: < 100ms (exchange dependent)
- **Symbols**: All active pairs on exchange

---

## Troubleshooting

### "No data available"
- Check symbol spelling (use YFinance format)
- Verify date range is valid
- Check internet connection

### "Import error: pybroker"
```bash
pip install pybroker --upgrade
```

### "Strategy build failed"
- Ensure strategy implements `build_strategy()` method
- Check for syntax errors in strategy code
- Verify imports are correct

### "Telegram alerts not sending"
- Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
- Verify telegram_enabled = True in config
- Test connectivity: `curl https://api.telegram.org/bot{TOKEN}/getMe`

### "Out of memory during walk-forward"
- Reduce walk_forward_periods (default 252)
- Reduce walk_forward_test_size (default 63)
- Run on smaller date range

---

## Advanced Usage

### Custom Backtest Loop
```python
from backtesting.pybroker_engine import BacktestEngine
from strategies.rule_based_pb import RuleBasedStrategy

engine = BacktestEngine(initial_balance=50000)
strategy = RuleBasedStrategy()

result = engine.run(
    symbol="BTC-USD",
    strategy=strategy,
    start_date="2024-01-01",
    end_date="2024-12-01"
)

print(f"Return: {result.total_return:.2f}%")
print(f"Win Rate: {result.win_rate:.1%}")
```

### Using ExecutionManager
```python
from execution.pybroker_executor import ExecutionManager
from risk.manager import RiskManager

risk_mgr = RiskManager(initial_balance=10000)
exec_mgr = ExecutionManager(risk_manager=risk_mgr)

# Check if trade allowed
allowed, reason = exec_mgr.pre_trade_check("BTC/USDT")

# Log trade event
await exec_mgr.on_trade_filled(
    symbol="BTC/USDT",
    side="long",
    shares=0.5,
    entry_price=45000,
    exit_price=46000,
    pnl=500
)
```

---

## Performance Tips

### Faster Backtesting
1. Reduce date range
2. Use walk-forward with smaller periods
3. Run on faster hardware
4. Use rule-based strategy (faster than AI)

### Faster Paper/Live Trading
1. Increase trading loop sleep interval
2. Reduce number of symbols
3. Use longer timeframe (1h instead of 5m)
4. Async Telegram alerts (non-blocking)

### Memory Optimization
1. Clear old logs periodically
2. Prune model files
3. Use database for historical data (not CSV)

---

## Next Steps

1. **Backtest** - Run initial backtest to verify setup
2. **Optimize** - Adjust parameters via walk-forward validation
3. **Train AI** - Create ML model if interested
4. **Paper Trade** - Test with simulated money (90 days)
5. **Go Live** - Use `--confirm` flag for real trading

---

**For more info:**
- PyBroker: https://pybroker.io/
- Project README: `README.md`
- Migration details: `PYBROKER_MIGRATION.md`
