# Development Mode Guide

## Overview

Development mode allows you to test trading strategies without connecting to real APIs. All data is generated locally using synthetic OHLCV data.

**Perfect for:**
- Testing new strategies
- Debugging code
- Training AI models offline
- Quick prototyping
- CI/CD pipelines

## Quick Start

### Enable Development Mode

```bash
# Generate mock data
python main.py dev-gen --symbol BTC-USD --start-date 2024-01-01 --end-date 2024-12-01

# Run backtest on mock data
python main.py dev-backtest --symbol BTC-USD --strategy rule_based

# Train model with synthetic data
python main.py dev-train --samples 2000 --features 20
```

## Features

### 🔧 Dev Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `dev-gen` | Generate mock OHLCV data | `python main.py dev-gen --symbol BTC-USD` |
| `dev-backtest` | Backtest on mock data | `python main.py dev-backtest --strategy rule_based` |
| `dev-train` | Train AI with synthetic data | `python main.py dev-train --samples 2000` |
| `dev-list` | List cached data files | `python main.py dev-list` |
| `dev-clear` | Clear cache | `python main.py dev-clear` |

### 📊 Mock Data Generation

Generates realistic OHLCV data with:
- **Realistic price movement** - Random walk with trend
- **Volatility** - Configurable daily volatility
- **Spikes** - Random price spikes (5% chance by default)
- **Volume** - Realistic trading volume variation
- **Caching** - Save data locally for reuse

### 🔄 Local Data Management

- **Automatic caching** - Generated data saved to `data/local/`
- **Smart loading** - Reuse cached data automatically
- **Size tracking** - Monitor cache size
- **Easy cleanup** - Clear specific symbols or all data

### 🤖 Synthetic Model Training

- **Generate training data** - Create synthetic features and labels
- **Offline training** - No API calls needed
- **Model persistence** - Save trained models
- **Quick iteration** - Test model changes rapidly

## Usage Examples

### 1. Generate Mock Data

```bash
# Default parameters
python main.py dev-gen

# Custom symbol and date range
python main.py dev-gen --symbol ETH-USD --start-date 2024-06-01 --end-date 2024-12-31

# Custom volatility
python main.py dev-gen --symbol BTC-USD --volatility 0.03

# Custom base price
python main.py dev-gen --symbol SOL-USD --base-price 100
```

Output:
```
✅ Generated 365 candles
   Symbol: BTC-USD
   Range: 2024-01-01 to 2024-12-01
   Saved: data/local/BTC-USD_2024-01-01_2024-12-01.csv
```

### 2. Backtest with Mock Data

```bash
# Rule-based strategy
python main.py dev-backtest --symbol BTC-USD --strategy rule_based

# AI strategy
python main.py dev-backtest --symbol BTC-USD --strategy ai --model models/btc_model.pkl

# Custom parameters
python main.py dev-backtest \
  --symbol ETH-USD \
  --start-date 2024-06-01 \
  --end-date 2024-12-31 \
  --initial-balance 50000
```

Output:
```
✅ Loaded cached data from data/local/BTC-USD_2024-01-01_2024-12-01.csv
🔧 Development mode: Running backtest with mock data
Running backtest on 365 candles of mock data

╔════════════════════════════════════════════╗
║     BACKTEST PERFORMANCE REPORT            ║
├════════════════════════════════════════════┤
║ Total Trades:        45                    ║
║ Win Rate:            60.0%                 ║
║ Total Return:        25.00%                ║
║ Sharpe Ratio:        1.45                  ║
║ Max Drawdown:        8.2%                  ║
╚════════════════════════════════════════════╝
```

### 3. Train AI Model

```bash
# Default parameters
python main.py dev-train

# Custom samples and features
python main.py dev-train --samples 5000 --features 30

# Save to specific path
python main.py dev-train --output models/custom_model.pkl
```

Output:
```
✅ Model training complete
   Samples: 2000
   Features: 20
   Saved: models/BTC-USD_dev_20241213_143022.pkl
```

### 4. Manage Cached Data

**List all cached files:**
```bash
python main.py dev-list
```

Output:
```
📊 Cached Data Files
   Total files: 3
   Total size: 1.23 MB

   Files:
     - BTC-USD_2024-01-01_2024-12-01.csv (0.45 MB)
     - ETH-USD_2024-01-01_2024-12-01.csv (0.38 MB)
     - SOL-USD_2024-01-01_2024-12-01.csv (0.40 MB)
```

**Clear specific symbol:**
```bash
python main.py dev-clear --symbol BTC-USD
# ✅ Deleted 1 cached files for BTC-USD
```

**Clear all cached data:**
```bash
python main.py dev-clear
# ✅ Deleted 3 cached files
```

## Configuration

### Default Dev Settings

In `config/settings.py`:

```python
@dataclass
class DevConfig:
    enabled: bool = False  # Enable dev mode
    use_mock_data: bool = True  # Use mock data
    mock_symbol: str = "BTC-USD"  # Default symbol
    mock_base_price: float = 45000.0  # Starting price
    mock_volatility: float = 0.02  # Daily volatility (2%)
    mock_days: int = 90  # Default days for mock data
    local_data_dir: str = "data/local"  # Cache directory
    debug_level: int = 1  # Debug verbosity
```

### Customize Settings

```python
# Enable dev mode
settings.enable_dev_mode()

# Disable dev mode
settings.disable_dev_mode()

# Custom mock config
from data.mock_generator import MockConfig

config = MockConfig(
    base_price=45000.0,
    volatility=0.03,  # 3% daily
    trend=0.001,  # Uptrend
    spike_probability=0.10  # 10% spike chance
)
```

## Mock Data Details

### Realistic Features

1. **Price Movement** - Random walk with configurable trend
2. **Volatility** - Normal distribution of daily returns
3. **Spikes** - Occasional large price movements
4. **Volume** - Realistic volume with variation
5. **OHLC Relationships** - Proper high/low boundaries

### Data Structure

```python
DataFrame with columns:
- timestamp: Date/time index
- open: Opening price
- high: High price
- low: Low price
- close: Closing price
- volume: Trading volume
```

### Reproducibility

- Random seed fixed (42) for consistent results
- Same parameters produce identical data
- Perfect for testing and debugging

## Advanced Usage

### Custom Mock Data Configuration

```python
from data.mock_generator import MockDataGenerator, MockConfig

config = MockConfig(
    base_price=50000,
    volatility=0.015,  # Lower volatility
    trend=0.0002,  # Slight uptrend
    volume_base=2000,
    spike_probability=0.02  # Rare spikes
)

generator = MockDataGenerator(config)
df = generator.generate_ohlcv(
    "BTC-USD",
    "2024-01-01",
    "2024-12-31"
)
```

### Programmatic Use

```python
from data.local_data import DataLoader
from backtesting.pybroker_engine import BacktestEngine
from strategies.rule_based_pb import RuleBasedStrategy

# Load data
loader = DataLoader()
data = loader.load_data("BTC-USD", "2024-01-01", "2024-12-31")

# Create strategy and backtest
strategy = RuleBasedStrategy()
engine = BacktestEngine()

result = engine.run(
    symbol="BTC-USD",
    strategy=strategy,
    start_date="2024-01-01",
    end_date="2024-12-31"
)

print(f"Return: {result.total_return:.2f}%")
```

### Generate Training Data Programmatically

```python
from data.mock_generator import generate_training_data

X, y = generate_training_data(
    symbol="BTC-USD",
    samples=5000,
    features=30
)

print(f"Features shape: {X.shape}")  # (5000, 30)
print(f"Labels shape: {y.shape}")    # (5000,)
print(f"Positive class: {y.sum()}")  # ~2500 (50%)
```

## Workflow Example

### Step 1: Generate Data

```bash
python main.py dev-gen --symbol BTC-USD --start-date 2024-01-01 --end-date 2024-12-31
```

### Step 2: Test Strategy

```bash
python main.py dev-backtest --symbol BTC-USD --strategy rule_based
```

### Step 3: Refine Parameters

Edit `config/settings.py`:
```python
settings.strategy.ema_fast = 15  # Changed from 20
settings.strategy.rsi_overbought = 75  # Changed from 70
```

### Step 4: Backtest Again

```bash
python main.py dev-backtest --symbol BTC-USD --strategy rule_based
```

### Step 5: Train Model

```bash
python main.py dev-train --samples 3000 --features 25
```

### Step 6: Test AI Strategy

```bash
python main.py dev-backtest \
  --symbol BTC-USD \
  --strategy ai \
  --model models/BTC-USD_dev_*.pkl
```

## Caching System

### How It Works

1. **First run** - Generates data, saves to `data/local/`
2. **Subsequent runs** - Loads from cache automatically
3. **Date-based** - Different dates = different files
4. **Symbol-based** - Different symbols = different files

### File Naming

```
{symbol}_{start_date}_{end_date}.csv
BTC-USD_2024-01-01_2024-12-31.csv
ETH-USD_2024-06-01_2024-08-31.csv
```

### Clear Cache When

- Testing with different parameters
- Need to regenerate data
- Free up disk space
- Change mock configuration

## Performance

### Generation Speed

- **90 days**: ~0.1 seconds
- **365 days**: ~0.3 seconds
- **1000 days**: ~0.8 seconds

### Backtest Speed

- **90 days**: ~1-2 seconds
- **365 days**: ~2-5 seconds
- **1000 days**: ~5-10 seconds

### Training Speed

- **1000 samples**: ~0.5 seconds
- **5000 samples**: ~1 second
- **10000 samples**: ~2 seconds

## Troubleshooting

### Cache Not Loading

```bash
# Clear specific symbol
python main.py dev-clear --symbol BTC-USD

# Regenerate
python main.py dev-gen --symbol BTC-USD
```

### Import Errors

```bash
# Verify dev modules exist
ls -la data/mock_generator.py
ls -la data/local_data.py
```

### Low Backtest Returns

Mock data is random - different results each run:
- Use `--volatility` to adjust
- Use `--base-price` to set starting price
- Reduce to ensure consistency

## Tips & Best Practices

✅ **DO:**
- Use dev mode for rapid testing
- Cache data for repeated tests
- Test strategies before using real data
- Use different date ranges for validation
- Generate varied mock data for robustness

❌ **DON'T:**
- Trust mock data results for live trading
- Use old cached data without refresh
- Ignore dev mode limitations
- Forget to test with real APIs before going live

## Limitations

⚠️ **Dev Mode:**
- Mock data not identical to real markets
- No slippage/liquidity simulation
- Perfect fills (no partial orders)
- No API delays

✅ **Still useful for:**
- Testing logic
- Parameter optimization
- Model training experiments
- CI/CD validation

## Next Steps

1. Generate mock data: `python main.py dev-gen`
2. Test strategy: `python main.py dev-backtest`
3. Train model: `python main.py dev-train`
4. Refine and optimize
5. Switch to real APIs when ready

---

**Questions?** Check logs in `logs/` directory or review code in `data/mock_generator.py` and `data/local_data.py`.
