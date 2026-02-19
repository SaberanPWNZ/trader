from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime
import pandas as pd
from loguru import logger

from strategies.base import BaseStrategy
from config.constants import SignalType
from data.models import Signal


@dataclass
class GridLevel:
    price: float
    side: str
    amount: float
    order_id: Optional[str] = None
    filled: bool = False
    filled_at: Optional[datetime] = None


@dataclass
class GridConfig:
    symbol: str
    upper_price: float
    lower_price: float
    num_grids: int = 10
    total_investment: float = 100.0
    
    @property
    def grid_spacing(self) -> float:
        return (self.upper_price - self.lower_price) / self.num_grids
    
    @property
    def amount_per_grid(self) -> float:
        return self.total_investment / self.num_grids


class GridStrategy(BaseStrategy):
    def __init__(self, symbol: str, config: Optional[GridConfig] = None):
        super().__init__(f"Grid_{symbol}")
        self.symbol = symbol
        self.config = config
        self.grid_levels: List[GridLevel] = []
        self.initialized = False
        self.last_price = 0.0
        self.center_price = 0.0
        self.last_rebalance_time: Optional[datetime] = None
        self.positions_carried_over: int = 0
        
    def build_strategy(self, data_source=None, start_date=None, end_date=None, symbol=None):
        pass
    
    def _calculate_dynamic_multiplier(self, data: pd.DataFrame) -> float:
        if data is None or len(data) < 30:
            return 7.0
        
        close_prices = data['close'].tail(30)
        daily_returns = close_prices.pct_change().dropna()
        volatility = daily_returns.std()
        
        if volatility > 0.05:
            multiplier = 10.0
            logger.info(f"{self.symbol}: High volatility ({volatility:.3f}) → multiplier = {multiplier}")
        elif volatility > 0.03:
            multiplier = 7.0
            logger.info(f"{self.symbol}: Medium volatility ({volatility:.3f}) → multiplier = {multiplier}")
        else:
            multiplier = 5.0
            logger.info(f"{self.symbol}: Low volatility ({volatility:.3f}) → multiplier = {multiplier}")
        
        return multiplier
    
    def initialize_grid(self, current_price: float, atr: float, total_investment: float, data: pd.DataFrame = None) -> GridConfig:
        atr_multiplier = self._calculate_dynamic_multiplier(data)
        upper_price = current_price + (atr * atr_multiplier)
        lower_price = current_price - (atr * atr_multiplier)
        
        self.config = GridConfig(
            symbol=self.symbol,
            upper_price=upper_price,
            lower_price=lower_price,
            num_grids=5,
            total_investment=total_investment
        )
        
        self.center_price = current_price
        self._create_grid_levels(current_price)
        self.initialized = True
        
        logger.info(f"Grid initialized for {self.symbol}:")
        logger.info(f"  Range: ${lower_price:.2f} - ${upper_price:.2f}")
        logger.info(f"  Center: ${current_price:.2f}")
        logger.info(f"  Grid spacing: ${self.config.grid_spacing:.2f}")
        logger.info(f"  Amount per grid: ${self.config.amount_per_grid:.2f}")
        
        return self.config
    
    def _create_grid_levels(self, current_price: float):
        self.grid_levels = []
        
        for i in range(self.config.num_grids + 1):
            price = self.config.lower_price + (i * self.config.grid_spacing)
            
            if price < current_price:
                side = "buy"
            elif price > current_price:
                side = "sell"
            else:
                continue
                
            self.grid_levels.append(GridLevel(
                price=price,
                side=side,
                amount=self.config.amount_per_grid / price
            ))
        
        self.grid_levels.sort(key=lambda x: x.price)
        logger.debug(f"Created {len(self.grid_levels)} grid levels")
    
    def check_grid_fills(self, current_price: float) -> List[Dict]:
        if not self.initialized:
            logger.debug(f"check_grid_fills: Grid not initialized yet")
            return []
        
        fills = []
        previous_price = self.last_price
        self.last_price = current_price
        
        if previous_price == 0:
            logger.debug(f"check_grid_fills: First price update, setting last_price=${current_price:.2f}")
            return []
        
        logger.debug(f"check_grid_fills: Checking {len(self.grid_levels)} levels, previous=${previous_price:.2f}, current=${current_price:.2f}")
        active_levels = [l for l in self.grid_levels if not l.filled]
        logger.debug(f"check_grid_fills: Active levels: {len(active_levels)} unfilled")
        
        if active_levels:
            buy_levels = [l for l in active_levels if l.side == "buy"]
            sell_levels = [l for l in active_levels if l.side == "sell"]
            if buy_levels:
                buy_prices = [l.price for l in buy_levels]
                logger.debug(f"check_grid_fills: BUY levels at: ${min(buy_prices):.2f} - ${max(buy_prices):.2f}")
            if sell_levels:
                sell_prices = [l.price for l in sell_levels]
                logger.debug(f"check_grid_fills: SELL levels at: ${min(sell_prices):.2f} - ${max(sell_prices):.2f}")
        
        for level in self.grid_levels:
            if level.filled:
                continue
            
            crossed = False
            if level.side == "buy":
                if previous_price > level.price >= current_price:
                    crossed = True
            else:
                if previous_price < level.price <= current_price:
                    crossed = True
            
            if crossed:
                level.filled = True
                level.filled_at = datetime.utcnow()
                fills.append({
                    "price": level.price,
                    "side": level.side,
                    "amount": level.amount,
                    "value": level.amount * level.price
                })
                logger.info(f"Grid level filled: {level.side.upper()} at ${level.price:.2f}")
                self._create_opposite_order(level)
        
        return fills
    
    def _create_opposite_order(self, filled_level: GridLevel):
        opposite_side = "sell" if filled_level.side == "buy" else "buy"
        
        if opposite_side == "sell":
            new_price = filled_level.price + self.config.grid_spacing
        else:
            new_price = filled_level.price - self.config.grid_spacing
        
        if self.config.lower_price <= new_price <= self.config.upper_price:
            tolerance = self.config.grid_spacing * 0.1
            existing = [l for l in self.grid_levels if abs(l.price - new_price) < tolerance and not l.filled]
            if not existing:
                self.grid_levels.append(GridLevel(
                    price=new_price,
                    side=opposite_side,
                    amount=filled_level.amount
                ))
    
    def get_active_levels(self) -> List[GridLevel]:
        return [l for l in self.grid_levels if not l.filled]
    
    def get_filled_levels(self) -> List[GridLevel]:
        return [l for l in self.grid_levels if l.filled]
    
    def calculate_unrealized_pnl(self, current_price: float) -> float:
        pnl = 0.0
        buy_fills = [l for l in self.grid_levels if l.filled and l.side == "buy"]
        for level in buy_fills:
            pnl += (current_price - level.price) * level.amount
        return pnl
    
    def calculate_realized_pnl(self) -> float:
        buys = sorted([l for l in self.grid_levels if l.filled and l.side == "buy"], key=lambda x: x.filled_at or datetime.min)
        sells = sorted([l for l in self.grid_levels if l.filled and l.side == "sell"], key=lambda x: x.filled_at or datetime.min)
        
        pnl = 0.0
        for buy, sell in zip(buys, sells):
            if buy.filled_at and sell.filled_at and buy.filled_at < sell.filled_at:
                profit = (sell.price - buy.price) * min(buy.amount, sell.amount)
                pnl += profit
        return pnl
    
    def can_rebalance_positions_profitable(self, current_price: float) -> tuple[bool, str]:
        from config.settings import settings
        
        filled_buys = [l for l in self.grid_levels if l.filled and l.side == "buy"]
        
        if not filled_buys:
            return True, "No open positions"
        
        total_unrealized = 0.0
        unprofitable_count = 0
        
        for buy in filled_buys:
            position_pnl = (current_price - buy.price) * buy.amount
            total_unrealized += position_pnl
            if position_pnl < 0:
                unprofitable_count += 1
        
        min_profit = max(
            settings.grid.min_profit_threshold,
            self.config.total_investment * (settings.grid.min_profit_threshold_percent / 100)
        )
        
        if total_unrealized < min_profit:
            return False, f"Unrealized ${total_unrealized:.2f} below threshold ${min_profit:.2f}"
        
        if unprofitable_count == 0:
            return True, f"All {len(filled_buys)} positions profitable (${total_unrealized:.2f})"
        
        return False, f"{unprofitable_count}/{len(filled_buys)} positions unprofitable (${total_unrealized:.2f})"
    
    def should_rebalance_hybrid(self, current_price: float) -> tuple[bool, str]:
        from config.settings import settings
        
        if not self.initialized:
            return False, "Not initialized"
        
        now = datetime.utcnow()
        hours_since_rebalance = 0
        
        if self.last_rebalance_time:
            hours_since_rebalance = (now - self.last_rebalance_time).total_seconds() / 3600
            
            if hours_since_rebalance < (settings.grid.rebalance_cooldown_minutes / 60):
                minutes_remaining = settings.grid.rebalance_cooldown_minutes - (hours_since_rebalance * 60)
                return False, f"Cooldown: {minutes_remaining:.0f}m remaining"
        
        buffer = self.config.grid_spacing * settings.grid.breakout_buffer_multiplier
        price_out_of_range = (
            current_price > self.config.upper_price + buffer or 
            current_price < self.config.lower_price - buffer
        )
        
        if price_out_of_range:
            can_rebalance, profit_msg = self.can_rebalance_positions_profitable(current_price)
            
            if hours_since_rebalance >= settings.grid.force_rebalance_after_hours:
                return True, f"FORCED after {hours_since_rebalance:.1f}h: Price breakout. {profit_msg}"
            
            if not can_rebalance and settings.grid.wait_for_profit:
                return False, f"Price breakout but waiting for profit: {profit_msg}"
            
            return True, f"EMERGENCY: Price breakout (${current_price:.2f}). {profit_msg}"
        
        rebalance_interval = settings.grid.get_interval_hours(self.symbol)
        if hours_since_rebalance >= rebalance_interval:
            can_rebalance, profit_msg = self.can_rebalance_positions_profitable(current_price)
            
            if not can_rebalance and settings.grid.wait_for_profit:
                return False, f"{hours_since_rebalance:.1f}h passed but waiting for profit: {profit_msg}"
            
            return True, f"SCHEDULED: {hours_since_rebalance:.1f}h passed. {profit_msg}"
        
        next_rebalance_hours = rebalance_interval - hours_since_rebalance
        return False, f"Next rebalance in {next_rebalance_hours:.1f}h"
    
    def should_rebalance(self, current_price: float) -> bool:
        if not self.initialized:
            return False
        buffer = self.config.grid_spacing * 2
        if current_price > self.config.upper_price + buffer:
            return True
        if current_price < self.config.lower_price - buffer:
            return True
        return False
    
    def rebalance(self, current_price: float, atr: float, reason: str = "unknown", data: pd.DataFrame = None):
        logger.warning(f"🔄 REBALANCING {self.symbol} around ${current_price:.2f}")
        logger.warning(f"   Reason: {reason}")
        
        filled_buys = [l for l in self.grid_levels if l.filled and l.side == "buy"]
        unrealized = self.calculate_unrealized_pnl(current_price)
        logger.warning(f"   Open buy levels: {len(filled_buys)}, Unrealized PnL: ${unrealized:.2f}")
        
        old_config = self.config
        self.positions_carried_over += len(filled_buys)
        
        self.initialize_grid(current_price, atr, self.config.total_investment, data)
        self.last_rebalance_time = datetime.utcnow()
        
        logger.info(f"   Old range: ${old_config.lower_price:.2f} - ${old_config.upper_price:.2f}")
        logger.info(f"   New range: ${self.config.lower_price:.2f} - ${self.config.upper_price:.2f}")
        logger.info(f"   Total positions carried over: {self.positions_carried_over}")
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        return self.create_signal(
            symbol=self.symbol,
            signal_type=SignalType.HOLD,
            confidence=0.5
        )
    
    def get_status(self) -> Dict:
        if not self.initialized:
            return {"status": "not_initialized"}
        
        return {
            "status": "active",
            "symbol": self.symbol,
            "range": f"${self.config.lower_price:.2f} - ${self.config.upper_price:.2f}",
            "center": f"${self.center_price:.2f}",
            "current": f"${self.last_price:.2f}",
            "grid_spacing": f"${self.config.grid_spacing:.2f}",
            "active_levels": len(self.get_active_levels()),
            "filled_levels": len(self.get_filled_levels())
        }
