"""
Position sizing calculations.
"""
from typing import Optional
from loguru import logger

from config.settings import settings


class PositionSizer:
    """
    Position sizing calculator.
    
    Implements various position sizing methods:
    - Fixed risk (percentage of account)
    - Fixed amount
    - Kelly criterion
    """
    
    def __init__(self):
        self.config = settings.risk
    
    def fixed_risk(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        risk_percent: Optional[float] = None
    ) -> float:
        """
        Calculate position size using fixed risk method.
        
        Position Size = (Account × Risk%) / |Entry - StopLoss|
        
        Args:
            account_balance: Current account balance
            entry_price: Entry price
            stop_loss: Stop loss price
            risk_percent: Risk percentage (uses config if not provided)
            
        Returns:
            Position size in base currency
        """
        risk_percent = risk_percent or self.config.max_risk_per_trade
        
        risk_amount = account_balance * risk_percent
        price_risk = abs(entry_price - stop_loss)
        
        if price_risk == 0:
            logger.warning("Price risk is zero")
            return 0.0
        
        position_size = risk_amount / price_risk
        
        # Apply max position size constraint
        max_value = account_balance * self.config.max_position_size
        max_size = max_value / entry_price
        
        return min(position_size, max_size)
    
    def fixed_amount(
        self,
        amount: float,
        entry_price: float,
        account_balance: float
    ) -> float:
        """
        Calculate position size using fixed amount.
        
        Args:
            amount: Fixed amount to risk
            entry_price: Entry price
            account_balance: Current account balance
            
        Returns:
            Position size in base currency
        """
        position_size = amount / entry_price
        
        # Apply max position size constraint
        max_value = account_balance * self.config.max_position_size
        max_size = max_value / entry_price
        
        return min(position_size, max_size)
    
    def kelly_criterion(
        self,
        account_balance: float,
        entry_price: float,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        kelly_fraction: float = 0.5
    ) -> float:
        """
        Calculate position size using Kelly Criterion.
        
        Kelly % = W - [(1-W) / R]
        Where:
        - W = Win probability
        - R = Win/Loss ratio
        
        Args:
            account_balance: Current account balance
            entry_price: Entry price
            win_rate: Historical win rate (0-1)
            avg_win: Average winning trade amount
            avg_loss: Average losing trade amount
            kelly_fraction: Fraction of Kelly to use (default 0.5 for half-Kelly)
            
        Returns:
            Position size in base currency
        """
        if avg_loss == 0:
            logger.warning("Average loss is zero, cannot calculate Kelly")
            return 0.0
        
        win_loss_ratio = avg_win / avg_loss
        
        kelly_percent = win_rate - ((1 - win_rate) / win_loss_ratio)
        
        # Apply Kelly fraction (half-Kelly is more conservative)
        kelly_percent = kelly_percent * kelly_fraction
        
        # Constrain Kelly percentage
        kelly_percent = max(0, min(kelly_percent, self.config.max_risk_per_trade * 5))
        
        position_value = account_balance * kelly_percent
        position_size = position_value / entry_price
        
        # Apply max position size constraint
        max_value = account_balance * self.config.max_position_size
        max_size = max_value / entry_price
        
        return min(position_size, max_size)
    
    def volatility_adjusted(
        self,
        account_balance: float,
        entry_price: float,
        atr: float,
        atr_multiplier: float = 2.0,
        risk_percent: Optional[float] = None
    ) -> float:
        """
        Calculate position size adjusted for volatility (ATR).
        
        Stop loss is placed at ATR × multiplier from entry.
        
        Args:
            account_balance: Current account balance
            entry_price: Entry price
            atr: Average True Range
            atr_multiplier: ATR multiplier for stop loss
            risk_percent: Risk percentage
            
        Returns:
            Position size in base currency
        """
        risk_percent = risk_percent or self.config.max_risk_per_trade
        
        stop_distance = atr * atr_multiplier
        stop_loss = entry_price - stop_distance
        
        return self.fixed_risk(
            account_balance,
            entry_price,
            stop_loss,
            risk_percent
        )
