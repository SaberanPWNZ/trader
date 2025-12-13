"""
Technical indicators calculation.
"""
import pandas as pd
import numpy as np
from typing import Optional


class TechnicalIndicators:
    """
    Technical indicators calculator.
    
    Provides methods to calculate common technical indicators
    used in trading strategies.
    """
    
    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """
        Calculate Exponential Moving Average.
        
        Args:
            series: Price series
            period: EMA period
            
        Returns:
            EMA series
        """
        return series.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """
        Calculate Simple Moving Average.
        
        Args:
            series: Price series
            period: SMA period
            
        Returns:
            SMA series
        """
        return series.rolling(window=period).mean()
    
    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """
        Calculate Relative Strength Index.
        
        Args:
            series: Price series
            period: RSI period
            
        Returns:
            RSI series (0-100)
        """
        delta = series.diff()
        
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        
        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    @staticmethod
    def macd(
        series: pd.Series,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> tuple:
        """
        Calculate MACD (Moving Average Convergence Divergence).
        
        Args:
            series: Price series
            fast_period: Fast EMA period
            slow_period: Slow EMA period
            signal_period: Signal line period
            
        Returns:
            Tuple of (MACD line, Signal line, Histogram)
        """
        fast_ema = TechnicalIndicators.ema(series, fast_period)
        slow_ema = TechnicalIndicators.ema(series, slow_period)
        
        macd_line = fast_ema - slow_ema
        signal_line = TechnicalIndicators.ema(macd_line, signal_period)
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    @staticmethod
    def atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> pd.Series:
        """
        Calculate Average True Range.
        
        Args:
            high: High price series
            low: Low price series
            close: Close price series
            period: ATR period
            
        Returns:
            ATR series
        """
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.ewm(span=period, adjust=False).mean()
        
        return atr
    
    @staticmethod
    def bollinger_bands(
        series: pd.Series,
        period: int = 20,
        std_dev: float = 2.0
    ) -> tuple:
        """
        Calculate Bollinger Bands.
        
        Args:
            series: Price series
            period: Moving average period
            std_dev: Standard deviation multiplier
            
        Returns:
            Tuple of (Upper band, Middle band, Lower band)
        """
        middle = TechnicalIndicators.sma(series, period)
        std = series.rolling(window=period).std()
        
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return upper, middle, lower
    
    @staticmethod
    def volume_delta(volume: pd.Series, period: int = 20) -> pd.Series:
        """
        Calculate volume change relative to average.
        
        Args:
            volume: Volume series
            period: Average period
            
        Returns:
            Volume delta series
        """
        avg_volume = volume.rolling(window=period).mean()
        return (volume - avg_volume) / avg_volume
    
    @staticmethod
    def log_returns(close: pd.Series) -> pd.Series:
        """
        Calculate log returns.
        
        Args:
            close: Close price series
            
        Returns:
            Log returns series
        """
        return np.log(close / close.shift(1))
    
    @staticmethod
    def add_all_indicators(df: pd.DataFrame, config=None) -> pd.DataFrame:
        """
        Add all standard indicators to DataFrame.
        
        Args:
            df: DataFrame with OHLCV data
            config: Strategy configuration (optional)
            
        Returns:
            DataFrame with added indicator columns
        """
        from config.settings import settings
        
        if config is None:
            config = settings.strategy
        
        df = df.copy()
        
        # EMAs
        df['ema_fast'] = TechnicalIndicators.ema(df['close'], config.ema_fast)
        df['ema_medium'] = TechnicalIndicators.ema(df['close'], config.ema_medium)
        df['ema_slow'] = TechnicalIndicators.ema(df['close'], config.ema_slow)
        
        # EMA ratios (features for ML)
        df['ema_ratio_fast_medium'] = df['ema_fast'] / df['ema_medium']
        df['ema_ratio_fast_slow'] = df['ema_fast'] / df['ema_slow']
        df['ema_ratio_medium_slow'] = df['ema_medium'] / df['ema_slow']
        
        # RSI
        df['rsi'] = TechnicalIndicators.rsi(df['close'], config.rsi_period)
        
        # MACD
        macd_line, signal_line, histogram = TechnicalIndicators.macd(
            df['close'],
            config.macd_fast,
            config.macd_slow,
            config.macd_signal
        )
        df['macd'] = macd_line
        df['macd_signal'] = signal_line
        df['macd_histogram'] = histogram
        
        # ATR
        df['atr'] = TechnicalIndicators.atr(
            df['high'], df['low'], df['close'], config.atr_period
        )
        df['atr_normalized'] = df['atr'] / df['close']
        
        # Volume
        df['volume_delta'] = TechnicalIndicators.volume_delta(df['volume'])
        
        # Returns
        df['log_return'] = TechnicalIndicators.log_returns(df['close'])
        
        # Bollinger Bands
        upper, middle, lower = TechnicalIndicators.bollinger_bands(df['close'])
        df['bb_upper'] = upper
        df['bb_middle'] = middle
        df['bb_lower'] = lower
        df['bb_width'] = (upper - lower) / middle
        
        # Trend detection
        df['trend'] = TechnicalIndicators.detect_trend(df)
        
        return df
    
    @staticmethod
    def detect_trend(df: pd.DataFrame) -> pd.Series:
        """
        Detect market trend.
        
        Args:
            df: DataFrame with EMA columns
            
        Returns:
            Series with trend values (1=uptrend, -1=downtrend, 0=flat)
        """
        conditions = [
            (df['ema_fast'] > df['ema_medium']) & (df['ema_medium'] > df['ema_slow']),
            (df['ema_fast'] < df['ema_medium']) & (df['ema_medium'] < df['ema_slow'])
        ]
        choices = [1, -1]
        
        return pd.Series(
            np.select(conditions, choices, default=0),
            index=df.index
        )
