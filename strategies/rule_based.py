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
        if len(data) < 2:
            return self.create_signal(
                symbol=data['symbol'].iloc[-1] if 'symbol' in data.columns else "UNKNOWN",
                signal_type=SignalType.HOLD,
                confidence=0.0
            )
        
        if 'ema_fast' not in data.columns:
            data = self.calculate_features(data)
        
        current = data.iloc[-1]
        previous = data.iloc[-2]
        
        symbol = current.get('symbol', 'UNKNOWN')
        close_price = current['close']
        atr = current['atr']
        
        buy_score = 0
        sell_score = 0
        
        if current['trend'] == 1:
            buy_score += 4
        elif current['trend'] == -1:
            sell_score += 4
        
        rsi = current['rsi']
        if rsi < 30:
            buy_score += 3
        elif rsi > 70:
            sell_score += 3
        elif 30 <= rsi < 45:
            buy_score += 1
        elif 55 < rsi <= 70:
            sell_score += 1
        
        macd_hist = current['macd_histogram']
        macd_hist_prev = previous['macd_histogram']
        macd_line = current['macd_line']
        macd_signal = current['macd_signal']
        
        if macd_hist > 0 and macd_hist > macd_hist_prev and macd_line > macd_signal:
            buy_score += 3
        elif macd_hist < 0 and macd_hist < macd_hist_prev and macd_line < macd_signal:
            sell_score += 3
        
        if (previous['ema_fast'] <= previous['ema_medium'] and 
            current['ema_fast'] > current['ema_medium'] and
            current['ema_medium'] > current['ema_slow']):
            buy_score += 3
        elif (previous['ema_fast'] >= previous['ema_medium'] and 
              current['ema_fast'] < current['ema_medium'] and
              current['ema_medium'] < current['ema_slow']):
            sell_score += 3
        
        if current['close'] < current['bb_lower'] and rsi < 40:
            buy_score += 2
        elif current['close'] > current['bb_upper'] and rsi > 60:
            sell_score += 2
        
        volume_increase = current['volume'] > data['volume'].rolling(20).mean().iloc[-1] * 1.5
        if volume_increase:
            if buy_score > sell_score:
                buy_score += 1
            elif sell_score > buy_score:
                sell_score += 1
        
        max_score = 16
        threshold = 7
        
        global_trend = current.get('global_trend', 0)
        
        if global_trend == 1 and buy_score > sell_score and buy_score >= threshold and current['trend'] == 1 and rsi < 70:
            confidence = min(buy_score / max_score, 0.99)
            stop_loss = close_price - (atr * self.config.stop_loss_atr_multiplier)
            take_profit = close_price + (atr * self.config.take_profit_atr_multiplier)
            
            logger.info(f"BUY signal for {symbol}: confidence={confidence:.2f} (score={buy_score}/{max_score}, rsi={rsi:.1f}, global_trend=BULL)")
            
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
                    'trend': current['trend'],
                    'global_trend': global_trend
                }
            )
        
        else:
            logger.debug(f"HOLD signal for {symbol}: buy={buy_score}, sell={sell_score}, global_trend={global_trend}")
            
            return self.create_signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.5,
                metadata={
                    'buy_score': buy_score,
                    'sell_score': sell_score,
                    'rsi': rsi,
                    'macd_histogram': macd_hist,
                    'trend': current['trend'],
                    'global_trend': global_trend
                }
            )
