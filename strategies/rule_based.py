"""
Rule-based trading strategy.
"""
import pandas as pd
from typing import Optional
from loguru import logger

from config.settings import settings
from config.constants import SignalType
from data.models import Signal
from .base import BaseStrategy
from .indicators import TechnicalIndicators


class RuleBasedStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="rule_based")
        self.config = settings.strategy
    
    def build_strategy(self, data_source=None, start_date: str = None, end_date: str = None, symbol: str = None):
        return None
    
    def calculate_features(self, data: pd.DataFrame) -> pd.DataFrame:
        return TechnicalIndicators.add_all_indicators(data, self.config)
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """
        Generate trading signal based on rules.
        
        Buy conditions:
        - Price above EMA fast > EMA medium > EMA slow (uptrend)
        - RSI not overbought (< 70)
        - MACD histogram positive and increasing
        
        Sell conditions:
        - Price below EMA fast < EMA medium < EMA slow (downtrend)
        - RSI not oversold (> 30)
        - MACD histogram negative and decreasing
        
        Args:
            data: DataFrame with OHLCV and indicators
            
        Returns:
            Trading signal
        """
        if len(data) < 2:
            return self.create_signal(
                symbol=data['symbol'].iloc[-1] if 'symbol' in data.columns else "UNKNOWN",
                signal_type=SignalType.HOLD,
                confidence=0.0
            )
        
        # Add indicators if not present
        if 'ema_fast' not in data.columns:
            data = self.calculate_features(data)
        
        current = data.iloc[-1]
        previous = data.iloc[-2]
        
        symbol = current.get('symbol', 'UNKNOWN')
        close_price = current['close']
        atr = current['atr']
        
        # Calculate signal strength
        buy_score = 0
        sell_score = 0
        
        # Trend analysis (weight: 3)
        if current['trend'] == 1:  # Uptrend
            buy_score += 3
        elif current['trend'] == -1:  # Downtrend
            sell_score += 3
        
        # RSI analysis (weight: 2)
        rsi = current['rsi']
        if rsi < self.config.rsi_oversold:
            buy_score += 2  # Oversold - potential bounce
        elif rsi > self.config.rsi_overbought:
            sell_score += 2  # Overbought - potential reversal
        elif rsi < 50:
            buy_score += 1
        else:
            sell_score += 1
        
        # MACD analysis (weight: 2)
        macd_hist = current['macd_histogram']
        macd_hist_prev = previous['macd_histogram']
        
        if macd_hist > 0 and macd_hist > macd_hist_prev:
            buy_score += 2  # Bullish momentum increasing
        elif macd_hist < 0 and macd_hist < macd_hist_prev:
            sell_score += 2  # Bearish momentum increasing
        
        # EMA crossover (weight: 2)
        if (previous['ema_fast'] <= previous['ema_medium'] and 
            current['ema_fast'] > current['ema_medium']):
            buy_score += 2  # Bullish crossover
        elif (previous['ema_fast'] >= previous['ema_medium'] and 
              current['ema_fast'] < current['ema_medium']):
            sell_score += 2  # Bearish crossover
        
        # Price relative to Bollinger Bands (weight: 1)
        if current['close'] < current['bb_lower']:
            buy_score += 1  # Price below lower band
        elif current['close'] > current['bb_upper']:
            sell_score += 1  # Price above upper band
        
        # Calculate signal
        max_score = 10  # Maximum possible score
        
        if buy_score > sell_score and buy_score >= 5:
            confidence = buy_score / max_score
            stop_loss = close_price - (atr * self.config.stop_loss_atr_multiplier)
            take_profit = close_price + (atr * self.config.take_profit_atr_multiplier)
            
            logger.info(f"BUY signal for {symbol}: confidence={confidence:.2f}")
            
            return self.create_signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                entry_price=close_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                metadata={
                    'buy_score': buy_score,
                    'sell_score': sell_score,
                    'rsi': rsi,
                    'macd_histogram': macd_hist,
                    'trend': current['trend']
                }
            )
        
        elif sell_score > buy_score and sell_score >= 5:
            confidence = sell_score / max_score
            stop_loss = close_price + (atr * self.config.stop_loss_atr_multiplier)
            take_profit = close_price - (atr * self.config.take_profit_atr_multiplier)
            
            logger.info(f"SELL signal for {symbol}: confidence={confidence:.2f}")
            
            return self.create_signal(
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                entry_price=close_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                metadata={
                    'buy_score': buy_score,
                    'sell_score': sell_score,
                    'rsi': rsi,
                    'macd_histogram': macd_hist,
                    'trend': current['trend']
                }
            )
        
        else:
            logger.debug(f"HOLD signal for {symbol}: buy={buy_score}, sell={sell_score}")
            
            return self.create_signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.5,
                metadata={
                    'buy_score': buy_score,
                    'sell_score': sell_score,
                    'rsi': rsi,
                    'macd_histogram': macd_hist,
                    'trend': current['trend']
                }
            )
