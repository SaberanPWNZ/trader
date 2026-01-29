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
    symbols: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"])
    timeframes: List[str] = field(default_factory=lambda: ["15m", "1h"])
    default_timeframe: str = "1h"
    mode: str = "paper"  # paper, live, backtest


@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_risk_per_trade: float = 0.02  # 2%
    max_daily_loss: float = 0.10  # 10%
    max_drawdown: float = 0.20  # 20% - portfolio kill switch
    max_position_size: float = 0.05  # 5% of portfolio per trade
    stop_loss_atr_multiplier: float = 1.5
    take_profit_atr_multiplier: float = 3.0
    max_consecutive_losses: int = 5
    cooldown_minutes: int = 30
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
    enabled: bool = False
    use_mock_data: bool = True
    mock_symbol: str = "BTC-USD"
    mock_base_price: float = 45000.0
    mock_volatility: float = 0.02
    mock_days: int = 90
    local_data_dir: str = "data/local"
    debug_level: int = 1
    skip_api_validation: bool = True


@dataclass
class SelfLearningConfig:
    enabled: bool = False
    training_interval_hours: int = field(default_factory=lambda: int(os.getenv("TRAINING_INTERVAL_HOURS", "4")))
    min_accuracy_improvement: float = 0.02
    min_samples_for_training: int = 1000
    max_models_to_keep: int = 5
    db_path: str = field(default_factory=lambda: os.getenv("LEARNING_DB_PATH", "data/learning.db"))
    performance_lookback_days: int = 365
    holdout_days: int = 7
    auto_deploy_enabled: bool = False
    backtest_before_deploy: bool = True
    min_sharpe_ratio: float = 0.5
    max_drawdown_percent: float = 20.0
    min_win_rate: float = 0.45
    min_profit_factor: float = 1.0
    max_overfit_gap: float = 0.20
    cv_splits: int = 5
    hyperparameter_tuning: bool = True
    label_threshold: float = 0.015
    confidence_threshold: float = 0.60


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
    initial_balance: float = 100.0  # Start with $100 for paper trading
    trading_fee: float = 0.001  # 0.1%
    slippage: float = 0.0005  # 0.05%
    
    # PyBroker-specific backtest settings
    pybroker_engine: bool = True
    walk_forward_periods: int = 252
    walk_forward_test_size: int = 63


@dataclass
class MonitoringConfig:
    telegram_enabled: bool = field(default_factory=lambda: os.getenv("TELEGRAM_ENABLED", "false").lower() == "true")
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    telegram_commands_enabled: bool = field(default_factory=lambda: os.getenv("TELEGRAM_COMMANDS_ENABLED", "false").lower() == "true")
    telegram_polling_interval: int = 2
    log_level: str = "INFO"
    log_to_file: bool = True
    log_dir: str = "logs"


@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str = field(default_factory=lambda: os.getenv(
        "DATABASE_URL", 
        "postgresql+asyncpg://trader:password@localhost:5240/trading_bot"
    ))
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False
    legacy_sqlite_path: str = field(default_factory=lambda: os.getenv("SQLITE_DB_PATH", "data/learning.db"))


@dataclass
class GridConfig:
    """Grid trading rebalancing configuration."""
    rebalance_interval_hours: float = field(default_factory=lambda: {
        "BTC/USDT": 12.0,
        "ETH/USDT": 12.0,
        "SOL/USDT": 8.0,
        "DOGE/USDT": 6.0,
        "XRP/USDT": 8.0
    })
    auto_rebalance_enabled: bool = True
    wait_for_profit: bool = True
    min_profit_threshold: float = 0.0
    min_profit_threshold_percent: float = 0.0
    rebalance_cooldown_minutes: int = 30
    min_price_movement_percent: float = 1.0
    emergency_rebalance_on_breakout: bool = True
    breakout_buffer_multiplier: float = 2.0
    force_rebalance_after_hours: float = 24.0
    
    portfolio_stop_loss_percent: float = 5.0
    portfolio_take_profit_percent: float = 10.0
    max_unrealized_loss_percent: float = 3.0
    partial_close_profit_percent: float = 2.0
    partial_close_ratio: float = 0.5
    enable_portfolio_protection: bool = True
    pause_after_stop_loss_hours: int = 24
    
    def get_interval_hours(self, symbol: str) -> float:
        if isinstance(self.rebalance_interval_hours, dict):
            return self.rebalance_interval_hours.get(symbol, 12.0)
        return self.rebalance_interval_hours


@dataclass
class Settings:
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    pybroker: PyBrokerConfig = field(default_factory=PyBrokerConfig)
    dev: DevConfig = field(default_factory=DevConfig)
    self_learning: SelfLearningConfig = field(default_factory=SelfLearningConfig)
    
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
