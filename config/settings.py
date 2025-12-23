"""
Application settings and configuration management.
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ExchangeConfig:
    """Exchange connection configuration."""
    name: str = "binance"
    api_key: str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("BINANCE_API_SECRET", ""))
    testnet: bool = True
    rate_limit: int = 1200  # requests per minute
    timeout: int = 30000  # milliseconds


@dataclass
class TradingConfig:
    """Trading parameters configuration."""
    symbols: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])
    timeframes: List[str] = field(default_factory=lambda: ["15m", "1h"])
    default_timeframe: str = "1h"
    mode: str = "paper"  # paper, live, backtest


@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_risk_per_trade: float = 0.02  # 2%
    max_daily_loss: float = 0.05  # 5%
    max_drawdown: float = 0.10  # 10%
    max_position_size: float = 0.30  # 30% of portfolio
    stop_loss_atr_multiplier: float = 2.0
    take_profit_atr_multiplier: float = 3.0
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 60
    kill_switch_enabled: bool = True


@dataclass
class StrategyConfig:
    """Strategy configuration."""
    # EMA periods
    ema_fast: int = 20
    ema_medium: int = 50
    ema_slow: int = 200
    # RSI
    rsi_period: int = 14
    rsi_overbought: int = 70
    rsi_oversold: int = 30
    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    # ATR
    atr_period: int = 14
    # Risk Management
    stop_loss_atr_multiplier: float = 2.0  # ATR multiplier for stop loss
    take_profit_atr_multiplier: float = 3.0  # ATR multiplier for take profit
    # AI Model
    model_type: str = "xgboost"  # randomforest, xgboost
    model_path: Optional[str] = None
    min_confidence: float = 0.6


@dataclass
class DevConfig:
    """Development mode configuration."""
    enabled: bool = False  # Enable dev mode
    use_mock_data: bool = True  # Use mock data instead of real APIs
    mock_symbol: str = "BTC-USD"  # Symbol for mock data
    mock_base_price: float = 45000.0  # Base price for mock data
    mock_volatility: float = 0.02  # Daily volatility (2%)
    mock_days: int = 90  # Number of days for mock data
    local_data_dir: str = "data/local"  # Directory for local data files
    debug_level: int = 1  # Debug verbosity (0=off, 1=info, 2=verbose)
    skip_api_validation: bool = True  # Skip API key validation in dev mode


@dataclass
class PyBrokerConfig:
    """PyBroker framework configuration."""
    # Data source configuration
    data_source: str = "yfinance"  # yfinance is default for PyBroker
    commission: float = 0.001  # 0.1% commission
    slippage: float = 0.0005  # 0.05% slippage
    
    # Bar configuration
    bar_size: int = 1  # number of periods per bar
    
    # Strategy execution
    max_bars: Optional[int] = None  # limit bars for quick testing, None = all
    
    # Crypto pair mapping for YFinance
    # PyBroker uses YFinance which requires different symbols for crypto
    symbol_mapping: dict = field(default_factory=lambda: {
        "BTC/USDT": "BTC-USD",  # Maps crypto pair to YFinance symbol
        "ETH/USDT": "ETH-USD",
        "BNB/USDT": "BNB-USD",
        "ADA/USDT": "ADA-USD",
        "XRP/USDT": "XRP-USD",
        "SOL/USDT": "SOL-USD",
        "DOGE/USDT": "DOGE-USD",
        "MATIC/USDT": "MATIC-USD",
    })


@dataclass
class BacktestConfig:
    """Backtesting configuration."""
    start_date: str = "2024-01-01"
    end_date: str = "2024-12-01"
    initial_balance: float = 10000.0
    trading_fee: float = 0.001  # 0.1%
    slippage: float = 0.0005  # 0.05%
    
    # PyBroker-specific backtest settings
    pybroker_engine: bool = True  # Use PyBroker for backtesting
    walk_forward_periods: int = 252  # trading days for walk-forward validation
    walk_forward_test_size: int = 63  # test set size


@dataclass
class MonitoringConfig:
    """Monitoring and alerts configuration."""
    telegram_enabled: bool = False
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    log_level: str = "INFO"
    log_to_file: bool = True
    log_dir: str = "logs"


@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///data/trading.db"))
    echo: bool = False


@dataclass
class Settings:
    """Main application settings."""
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    pybroker: PyBrokerConfig = field(default_factory=PyBrokerConfig)
    dev: DevConfig = field(default_factory=DevConfig)
    
    # Paths
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")
    models_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "models")
    
    def __post_init__(self):
        """Create necessary directories."""
        self.data_dir.mkdir(exist_ok=True)
        self.models_dir.mkdir(exist_ok=True)
        Path(self.monitoring.log_dir).mkdir(exist_ok=True)
        
        # Create dev data directory if dev mode enabled
        if self.dev.enabled:
            Path(self.dev.local_data_dir).mkdir(parents=True, exist_ok=True)
    
    def get_symbol_for_pybroker(self, crypto_pair: str) -> str:
        """Convert ccxt symbol to YFinance symbol for PyBroker."""
        return self.pybroker.symbol_mapping.get(crypto_pair, crypto_pair)
    
    def enable_dev_mode(self) -> None:
        """Enable development mode."""
        self.dev.enabled = True
        self.dev.use_mock_data = True
        Path(self.dev.local_data_dir).mkdir(parents=True, exist_ok=True)
        from loguru import logger
        logger.info("✅ Development mode ENABLED")
    
    def disable_dev_mode(self) -> None:
        """Disable development mode."""
        self.dev.enabled = False
        self.dev.use_mock_data = False
        from loguru import logger
        logger.info("🔓 Development mode DISABLED")


# Global settings instance
settings = Settings()
