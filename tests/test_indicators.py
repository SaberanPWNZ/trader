"""
Tests for technical indicators.
"""
import pytest
import pandas as pd
import numpy as np
from strategies.indicators import TechnicalIndicators


@pytest.fixture
def sample_ohlcv_data():
    """Generate sample OHLCV data for testing."""
    np.random.seed(42)
    n = 100
    
    dates = pd.date_range(start='2024-01-01', periods=n, freq='1h')
    
    # Generate random walk prices
    returns = np.random.normal(0, 0.02, n)
    close = 100 * np.exp(np.cumsum(returns))
    
    # Generate OHLCV
    high = close * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, n)))
    open_ = close * (1 + np.random.normal(0, 0.005, n))
    volume = np.random.uniform(1000, 10000, n)
    
    df = pd.DataFrame({
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    }, index=dates)
    
    return df


class TestTechnicalIndicators:
    """Test cases for TechnicalIndicators class."""
    
    def test_ema(self, sample_ohlcv_data):
        """Test EMA calculation."""
        ema = TechnicalIndicators.ema(sample_ohlcv_data['close'], 20)
        
        assert len(ema) == len(sample_ohlcv_data)
        assert not ema.isna().all()
        # EMA should be close to price
        assert abs(ema.iloc[-1] - sample_ohlcv_data['close'].iloc[-1]) < sample_ohlcv_data['close'].iloc[-1] * 0.1
    
    def test_sma(self, sample_ohlcv_data):
        """Test SMA calculation."""
        sma = TechnicalIndicators.sma(sample_ohlcv_data['close'], 20)
        
        assert len(sma) == len(sample_ohlcv_data)
        # First 19 values should be NaN
        assert sma.iloc[:19].isna().all()
        assert not sma.iloc[19:].isna().any()
    
    def test_rsi(self, sample_ohlcv_data):
        """Test RSI calculation."""
        rsi = TechnicalIndicators.rsi(sample_ohlcv_data['close'], 14)
        
        assert len(rsi) == len(sample_ohlcv_data)
        # RSI should be between 0 and 100
        valid_rsi = rsi.dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()
    
    def test_macd(self, sample_ohlcv_data):
        """Test MACD calculation."""
        macd_line, signal_line, histogram = TechnicalIndicators.macd(
            sample_ohlcv_data['close']
        )
        
        assert len(macd_line) == len(sample_ohlcv_data)
        assert len(signal_line) == len(sample_ohlcv_data)
        assert len(histogram) == len(sample_ohlcv_data)
        
        # Histogram should be MACD - Signal
        np.testing.assert_array_almost_equal(
            histogram.dropna().values,
            (macd_line - signal_line).dropna().values
        )
    
    def test_atr(self, sample_ohlcv_data):
        """Test ATR calculation."""
        atr = TechnicalIndicators.atr(
            sample_ohlcv_data['high'],
            sample_ohlcv_data['low'],
            sample_ohlcv_data['close'],
            14
        )
        
        assert len(atr) == len(sample_ohlcv_data)
        # ATR should be positive
        assert (atr.dropna() > 0).all()
    
    def test_bollinger_bands(self, sample_ohlcv_data):
        """Test Bollinger Bands calculation."""
        upper, middle, lower = TechnicalIndicators.bollinger_bands(
            sample_ohlcv_data['close']
        )
        
        assert len(upper) == len(sample_ohlcv_data)
        # Upper > Middle > Lower
        valid_idx = ~upper.isna()
        assert (upper[valid_idx] >= middle[valid_idx]).all()
        assert (middle[valid_idx] >= lower[valid_idx]).all()
    
    def test_add_all_indicators(self, sample_ohlcv_data):
        """Test adding all indicators to DataFrame."""
        df = TechnicalIndicators.add_all_indicators(sample_ohlcv_data)
        
        expected_columns = [
            'ema_fast', 'ema_medium', 'ema_slow',
            'rsi', 'macd', 'macd_signal', 'macd_histogram',
            'atr', 'bb_upper', 'bb_middle', 'bb_lower',
            'trend'
        ]
        
        for col in expected_columns:
            assert col in df.columns, f"Missing column: {col}"
