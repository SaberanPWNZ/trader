"""
Mock data generator for development and testing.

Generates realistic OHLCV data without connecting to real APIs.
Useful for:
- Local development
- Testing strategies
- Training models offline
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Tuple, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class MockConfig:
    """Mock data generation configuration."""
    base_price: float = 45000.0  # Starting price
    volatility: float = 0.02  # Daily volatility (2%)
    trend: float = 0.0005  # Daily trend (0.05%)
    volume_base: float = 1000.0  # Base volume
    volume_std: float = 200.0  # Volume standard deviation
    spike_probability: float = 0.05  # Probability of price spike (5%)
    spike_magnitude: float = 0.03  # Max spike magnitude (3%)


class MockDataGenerator:
    """Generate realistic mock OHLCV data for testing."""
    
    def __init__(self, config: Optional[MockConfig] = None):
        """
        Initialize mock data generator.
        
        Args:
            config: Mock data configuration
        """
        self.config = config or MockConfig()
        np.random.seed(42)  # Reproducible data
        logger.info("Initialized MockDataGenerator")
    
    def generate_ohlcv(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "1h"
    ) -> pd.DataFrame:
        """
        Generate realistic mock OHLCV data.
        
        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            timeframe: Candle timeframe (1h, 4h, 1d, etc)
            
        Returns:
            DataFrame with OHLCV data
        """
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        
        # Create date range based on timeframe
        if timeframe == "1h":
            freq = "H"
        elif timeframe == "4h":
            freq = "4H"
        elif timeframe == "1d":
            freq = "D"
        else:
            freq = "D"
        
        dates = pd.date_range(start=start, end=end, freq=freq)
        n = len(dates)
        
        if n < 10:
            logger.warning(f"Generated only {n} candles, consider longer date range")
        
        # Generate price movement with random walk + trend
        returns = np.random.normal(
            self.config.trend,
            self.config.volatility,
            n
        )
        
        # Add occasional spikes
        spikes = np.random.random(n) < self.config.spike_probability
        spike_returns = np.random.normal(0, self.config.spike_magnitude, n)
        returns = np.where(spikes, spike_returns, returns)
        
        # Generate prices
        prices = self.config.base_price * np.exp(np.cumsum(returns))
        
        # Generate OHLC from close prices
        opens = prices.copy()
        closes = prices.copy()
        
        # High and low with realistic range
        highs = prices * (1 + np.abs(np.random.normal(0, 0.005, n)))
        lows = prices * (1 - np.abs(np.random.normal(0, 0.005, n)))
        
        # Make sure OHLC relationships are correct
        highs = np.maximum(highs, np.maximum(opens, closes))
        lows = np.minimum(lows, np.minimum(opens, closes))
        
        # Generate volume
        volumes = self.config.volume_base + np.random.normal(
            0,
            self.config.volume_std,
            n
        )
        volumes = np.maximum(volumes, 10)  # Minimum volume
        
        # Create DataFrame
        df = pd.DataFrame({
            'timestamp': dates,
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volumes,
        })
        
        # Set index
        df.set_index('timestamp', inplace=True)
        
        logger.info(
            f"Generated {n} candles for {symbol} "
            f"[{start_date} to {end_date}] ({timeframe})"
        )
        
        return df
    
    def generate_multi_symbol(
        self,
        symbols: list,
        start_date: str,
        end_date: str,
        base_price: float = 45000.0
    ) -> dict:
        """
        Generate mock data for multiple symbols.
        
        Args:
            symbols: List of symbols (e.g., ['BTC-USD', 'ETH-USD'])
            start_date: Start date
            end_date: End date
            base_price: Base price for first symbol
            
        Returns:
            Dict with symbol: DataFrame pairs
        """
        data = {}
        
        for i, symbol in enumerate(symbols):
            # Different starting prices for different symbols
            config = MockConfig(
                base_price=base_price / (i + 1),
                volatility=np.random.uniform(0.015, 0.03),
                trend=np.random.uniform(-0.001, 0.001)
            )
            
            generator = MockDataGenerator(config)
            data[symbol] = generator.generate_ohlcv(
                symbol,
                start_date,
                end_date
            )
        
        return data
    
    @staticmethod
    def load_sample_data(
        symbol: str = "BTC-USD",
        days: int = 90
    ) -> pd.DataFrame:
        """
        Load pre-generated sample data for quick testing.
        
        Args:
            symbol: Symbol to generate for
            days: Number of days to generate
            
        Returns:
            DataFrame with mock OHLCV data
        """
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        generator = MockDataGenerator()
        return generator.generate_ohlcv(symbol, start_date, end_date, "1d")
    
    @staticmethod
    def save_to_csv(
        df: pd.DataFrame,
        filepath: str
    ) -> None:
        """
        Save mock data to CSV file.
        
        Args:
            df: DataFrame to save
            filepath: Output CSV file path
        """
        df.to_csv(filepath)
        logger.info(f"Saved mock data to {filepath}")
    
    @staticmethod
    def load_from_csv(filepath: str) -> pd.DataFrame:
        """
        Load mock data from CSV file.
        
        Args:
            filepath: Input CSV file path
            
        Returns:
            DataFrame with mock data
        """
        df = pd.read_csv(filepath, index_col='timestamp', parse_dates=True)
        logger.info(f"Loaded mock data from {filepath}")
        return df


def generate_training_data(
    symbol: str,
    samples: int = 1000,
    features: int = 10
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate synthetic training data for ML models.
    
    Args:
        symbol: Symbol name
        samples: Number of samples
        features: Number of features
        
    Returns:
        Tuple of (X, y) for training
    """
    # Generate random features
    X = np.random.randn(samples, features)
    
    # Generate labels based on feature combinations
    y = (
        (X[:, 0] > 0) & (X[:, 1] > 0) |
        (X[:, 2] > 0.5)
    ).astype(int)
    
    # Add some randomness to avoid perfect classification
    flip_mask = np.random.random(samples) < 0.15
    y[flip_mask] = 1 - y[flip_mask]
    
    logger.info(
        f"Generated {samples} training samples with {features} features "
        f"({np.sum(y)} positive labels)"
    )
    
    return X, y
