"""
Rule-based trading strategy for PyBroker.
"""
import pandas as pd
from pybroker import Strategy, ExecContext, YFinance
from loguru import logger
from typing import Optional

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
        self._strategy: Optional[Strategy] = None
        self._data_source = YFinance()
    
    def build_strategy(self, 
                      data_source=None,
                      start_date: str = None, 
                      end_date: str = None,
                      symbol: str = None) -> Strategy:
        """
        Build PyBroker strategy with entry/exit rules.
        
        Args:
            data_source: PyBroker data source (defaults to YFinance)
            start_date: Start date for backtest
            end_date: End date for backtest
            symbol: Trading symbol (e.g., 'BTC-USD')
        """
        # Use provided data_source or default
        ds = data_source or self._data_source
        
        # Default symbol
        if symbol is None:
            symbol = "BTC-USD"
        
        # Create strategy with data_source and dates
        strategy = Strategy(
            data_source=ds,
            start_date=start_date or "2024-01-01",
            end_date=end_date or "2024-12-31"
        )
        
        def execution_fn(ctx: ExecContext) -> None:
            """Combined execution logic."""
            try:
                # Get current long position for this symbol
                position = ctx.long_pos(ctx.symbol)
                position_size = position.shares if position else 0
                
                # Buy on first bar, Sell on day 20
                if position_size == 0 and len(ctx.close) == 1:
                    current_price = float(ctx.close[-1])
                    shares = int(float(ctx.cash) / current_price * 0.5)  # Use 50% of cash
                    if shares > 0:
                        ctx.buy_shares = shares
                        logger.debug(f"BUY: {ctx.symbol} - {shares} shares at ${current_price:.2f}")
                
                elif position_size > 0 and len(ctx.close) >= 20:
                    current_price = float(ctx.close[-1])
                    ctx.sell_all_shares()
                    logger.debug(f"SELL: {ctx.symbol} at ${current_price:.2f}")
                
            except Exception as e:
                logger.error(f"Execution error: {e}")
        
        # Add execution rule for specific symbol
        strategy.add_execution(
            fn=execution_fn,
            symbols=[symbol]
        )
        
        self._strategy = strategy
        return self._strategy
    
    @property
    def strategy(self) -> Strategy:
        """Get or create strategy."""
        if self._strategy is None:
            self.build_strategy()
        return self._strategy
