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
        
    def build_strategy(self, data_source=None, start_date=None, end_date=None, symbol=None):
        pass
    
    def initialize_grid(self, current_price: float, atr: float, total_investment: float) -> GridConfig:
        atr_multiplier = 3.0
        upper_price = current_price + (atr * atr_multiplier)
        lower_price = current_price - (atr * atr_multiplier)
        
        self.config = GridConfig(
            symbol=self.symbol,
            upper_price=upper_price,
            lower_price=lower_price,
            num_grids=10,
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
            return []
        
        fills = []
        previous_price = self.last_price
        self.last_price = current_price
        
        if previous_price == 0:
            return []
        
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
            existing = [l for l in self.grid_levels if abs(l.price - new_price) < 0.01 and not l.filled]
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
    
    def should_rebalance(self, current_price: float) -> bool:
        if not self.initialized:
            return False
        buffer = self.config.grid_spacing * 2
        if current_price > self.config.upper_price + buffer:
            return True
        if current_price < self.config.lower_price - buffer:
            return True
        return False
    
    def rebalance(self, current_price: float, atr: float):
        logger.info(f"Rebalancing grid for {self.symbol} around ${current_price:.2f}")
        filled_buys = [l for l in self.grid_levels if l.filled and l.side == "buy"]
        
        self.initialize_grid(current_price, atr, self.config.total_investment)
    
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
