"""
Rule-based trading strategy for PyBroker.
"""
import pandas as pd
from pybroker import Strategy, ExecContext
from loguru import logger

from config.settings import settings
from config.constants import SignalType
from .indicators import TechnicalIndicators
from .base import BaseStrategy


class RuleBasedStrategy(BaseStrategy):
    """
    Rule-based trading strategy using PyBroker.
    
    Uses EMA crossovers, RSI, and MACD for signal generation.
    """
    
    def __init__(self):
        super().__init__(name="rule_based")
        self.config = settings.strategy
        self._strategy: Strategy = None
    
    def build_strategy(self) -> Strategy:
        """Build PyBroker strategy with entry/exit rules."""
        if self._strategy is not None:
            return self._strategy
        
        strategy = Strategy(ctx=None)
        
        @strategy.indicator()
        def add_indicators(data: pd.DataFrame) -> pd.DataFrame:
            """Add technical indicators."""
            return TechnicalIndicators.add_all_indicators(data, self.config)
        
        @strategy.entry(add_indicators)
        def entry_logic(ctx: ExecContext) -> None:
            """Entry logic based on indicator values."""
            indicators = ctx.indicator()
            
            close = indicators['close'].iloc[-1]
            rsi = indicators['rsi'].iloc[-1]
            macd_hist = indicators['macd_histogram'].iloc[-1]
            macd_hist_prev = indicators['macd_histogram'].iloc[-2]
            trend = indicators['trend'].iloc[-1]
            
            # BUY conditions
            if (trend == 1 and  # Uptrend
                rsi < self.config.rsi_overbought and  # Not overbought
                macd_hist > 0 and macd_hist > macd_hist_prev):  # MACD positive
                
                size = ctx.portfolio.size if ctx.portfolio else 0.1
                ctx.buy_shares = max(size, 0.01)
                logger.info(f"BUY signal: {ctx.symbol} (trend={trend}, rsi={rsi:.1f})")
        
        @strategy.exit()
        def exit_logic(ctx: ExecContext) -> None:
            """Exit logic for position management."""
            if not ctx.position:
                return
            
            indicators = ctx.indicator()
            trend = indicators['trend'].iloc[-1]
            rsi = indicators['rsi'].iloc[-1]
            
            # SELL conditions (exit long)
            if ctx.position.size > 0:
                if (trend == -1 or  # Downtrend
                    rsi > self.config.rsi_overbought):  # Overbought
                    ctx.close_all_shares()
                    logger.info(f"SELL signal: {ctx.symbol} (trend={trend})")
            
            # EXIT short
            elif ctx.position.size < 0:
                if (trend == 1 or  # Uptrend
                    rsi < self.config.rsi_oversold):  # Oversold
                    ctx.close_all_shares()
                    logger.info(f"CLOSE SHORT: {ctx.symbol} (trend={trend})")
        
        self._strategy = strategy
        return self._strategy
    
    @property
    def strategy(self) -> Strategy:
        """Get or create strategy."""
        if self._strategy is None:
            self.build_strategy()
        return self._strategy
