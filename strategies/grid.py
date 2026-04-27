from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime
import pandas as pd
from loguru import logger

from strategies.base import BaseStrategy
from config.constants import SignalType
from config.settings import settings
from data.models import Signal
from execution.portfolio_protection import compute_adaptive_num_grids


@dataclass
class GridLevel:
    price: float
    side: str
    amount: float
    order_id: Optional[str] = None
    filled: bool = False
    filled_at: Optional[datetime] = None
    level_id: Optional[int] = None
    pair_id: Optional[int] = None


@dataclass
class GridConfig:
    symbol: str
    upper_price: float
    lower_price: float
    num_grids: int = 10
    total_investment: float = 100.0

    @property
    def grid_spacing(self) -> float:
        # num_grids interior levels strictly between lower_price and upper_price
        # → there are num_grids+1 equal-width gaps.
        return (self.upper_price - self.lower_price) / (self.num_grids + 1)
    
    @property
    def amount_per_grid(self) -> float:
        """Legacy: USDT allocated per level if split evenly across all `num_grids`.

        For actual capital allocation see `GridStrategy._create_grid_levels`,
        which divides `total_investment` only across BUY levels (SELL levels
        don't tie up USDT — they require base inventory)."""
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
        self._next_level_id: int = 0

    def _new_level_id(self) -> int:
        lid = self._next_level_id
        self._next_level_id += 1
        return lid
        
    def build_strategy(self, data_source=None, start_date=None, end_date=None, symbol=None):
        pass
    
    def _calculate_dynamic_multiplier(self, data: pd.DataFrame) -> float:
        """Pick an ATR multiplier from recent return volatility.

        ``_get_ml_advice`` and the rest of the live pipeline feed 1-hour
        candles into this method, so the standard-deviation thresholds are
        calibrated for *hourly* returns. The previous defaults of 5% / 3%
        were daily-return-sized and effectively unreachable on hourly data,
        so the high-volatility branch never fired.
        """
        if data is None or len(data) < 30:
            return 7.0

        close_prices = data['close'].tail(30)
        hourly_returns = close_prices.pct_change().dropna()
        volatility = hourly_returns.std()

        # Hourly-return std thresholds:
        #   > 1.5%   ≈ shock / news event
        #   > 0.8%   ≈ elevated regime
        #   else     ≈ calm
        if volatility > 0.015:
            multiplier = 10.0
            logger.info(f"{self.symbol}: High hourly volatility ({volatility:.4f}) → multiplier = {multiplier}")
        elif volatility > 0.008:
            multiplier = 7.0
            logger.info(f"{self.symbol}: Medium hourly volatility ({volatility:.4f}) → multiplier = {multiplier}")
        else:
            multiplier = 5.0
            logger.info(f"{self.symbol}: Low hourly volatility ({volatility:.4f}) → multiplier = {multiplier}")

        return multiplier
    
    def _classify_volatility_regime(self, data: pd.DataFrame) -> str:
        """Map recent hourly-return volatility to the regime strings used by
        ``compute_adaptive_num_grids``.

        Thresholds mirror ``_calculate_dynamic_multiplier`` so the same
        bands drive both the ATR multiplier (range width) and the grid
        line count (range density).
        """
        if data is None or len(data) < 30:
            return "normal"
        close_prices = data['close'].tail(30)
        hourly_returns = close_prices.pct_change().dropna()
        if hourly_returns.empty:
            return "normal"
        volatility = float(hourly_returns.std())
        if volatility > 0.015:
            return "high"
        if volatility > 0.008:
            return "normal"
        return "low"

    def initialize_grid(
        self,
        current_price: float,
        atr: float,
        total_investment: float,
        data: pd.DataFrame = None,
        _is_rebalance: bool = False,
        volatility_regime: Optional[str] = None,
    ) -> GridConfig:
        atr_multiplier = self._calculate_dynamic_multiplier(data)
        upper_price = current_price + (atr * atr_multiplier)
        lower_price = current_price - (atr * atr_multiplier)

        # Pick grid density adaptively from volatility — calm markets get a
        # denser grid (more fills on small wiggles), choppy markets get a
        # sparser grid (each leg captures real movement). Replaces the old
        # hard-coded ``num_grids=5``.
        regime = volatility_regime or self._classify_volatility_regime(data)
        num_grids = compute_adaptive_num_grids(
            min_grids=settings.grid.min_grids,
            max_grids=settings.grid.max_grids,
            volatility_regime=regime,
        )

        self.config = GridConfig(
            symbol=self.symbol,
            upper_price=upper_price,
            lower_price=lower_price,
            num_grids=num_grids,
            total_investment=total_investment
        )
        
        self.center_price = current_price
        self._create_grid_levels(current_price)
        self.initialized = True
        # Stamp the rebalance clock on first init too — otherwise
        # ``should_rebalance_hybrid`` sees ``last_rebalance_time = None`` and
        # treats hours_since_rebalance as 0, *bypassing* the cooldown check
        # and allowing an immediate rebalance right after initialization.
        if not _is_rebalance and self.last_rebalance_time is None:
            self.last_rebalance_time = datetime.utcnow()
        
        logger.info(f"Grid initialized for {self.symbol}:")
        logger.info(f"  Range: ${lower_price:.2f} - ${upper_price:.2f}")
        logger.info(f"  Center: ${current_price:.2f}")
        logger.info(f"  Grid spacing: ${self.config.grid_spacing:.2f}")
        logger.info(f"  Amount per grid: ${self.config.amount_per_grid:.2f}")
        
        return self.config
    
    def _create_grid_levels(self, current_price: float):
        """Place exactly `num_grids` levels strictly between lower_price and
        upper_price. Capital (`total_investment`) is split evenly across BUY
        levels only — SELL levels don't lock USDT, they need base inventory.
        """
        self.grid_levels = []
        spacing = self.config.grid_spacing
        # Two-pass: first compute prices and sides so we know how many BUYs
        # exist before allocating capital per BUY.
        prices_sides = []
        for i in range(1, self.config.num_grids + 1):
            price = self.config.lower_price + i * spacing
            if price < current_price:
                side = "buy"
            elif price > current_price:
                side = "sell"
            else:
                # Exact match with current price is treated as BUY (USDT-funded);
                # this preserves total level count = num_grids.
                side = "buy"
            prices_sides.append((price, side))

        num_buys = sum(1 for _, s in prices_sides if s == "buy")
        usdt_per_buy = (self.config.total_investment / num_buys) if num_buys > 0 else 0.0

        for price, side in prices_sides:
            if side == "buy":
                amount = usdt_per_buy / price if price > 0 else 0.0
            else:
                # SELL inventory size mirrors what a single BUY would have produced;
                # actual base inventory comes from filled BUYs or seed positions.
                amount = usdt_per_buy / price if price > 0 else 0.0
            self.grid_levels.append(GridLevel(
                price=price,
                side=side,
                amount=amount,
                level_id=self._new_level_id()
            ))

        self.grid_levels.sort(key=lambda x: x.price)
        logger.debug(
            f"Created {len(self.grid_levels)} grid levels "
            f"({num_buys} BUY, {len(self.grid_levels) - num_buys} SELL)"
        )
    
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
        
        # Two-phase iteration: don't mutate self.grid_levels while iterating it.
        # Phase 1 — detect crosses against a snapshot.
        crossed_levels: List[GridLevel] = []
        for level in list(self.grid_levels):
            if level.filled:
                continue

            crossed = False
            if level.side == "buy":
                # Symmetric inclusive bounds: price moved from at-or-above to
                # at-or-below the level (covers exact touches on either tick).
                if previous_price >= level.price >= current_price:
                    crossed = True
            else:
                if previous_price <= level.price <= current_price:
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
                crossed_levels.append(level)

        # Phase 2 — spawn opposite orders after the iteration is done.
        for level in crossed_levels:
            self._create_opposite_order(level)

        return fills
    
    def _create_opposite_order(self, filled_level: GridLevel):
        opposite_side = "sell" if filled_level.side == "buy" else "buy"
        
        if opposite_side == "sell":
            new_price = filled_level.price + self.config.grid_spacing
        else:
            new_price = filled_level.price - self.config.grid_spacing
        
        if self.config.lower_price <= new_price <= self.config.upper_price:
            # Use a generous tolerance (half of grid_spacing). The previous
            # 0.1*spacing band let near-duplicate levels coexist when an
            # opposite order was spawned at almost — but not exactly — the
            # same price as an existing active level, which produced
            # double-fills on the next cross. Half-spacing is the natural
            # exclusion radius around a grid line.
            tolerance = self.config.grid_spacing * 0.5
            existing = [l for l in self.grid_levels if abs(l.price - new_price) < tolerance and not l.filled]
            if not existing:
                self.grid_levels.append(GridLevel(
                    price=new_price,
                    side=opposite_side,
                    amount=filled_level.amount,
                    level_id=self._new_level_id(),
                    pair_id=filled_level.level_id
                ))
    
    def get_active_levels(self) -> List[GridLevel]:
        return [l for l in self.grid_levels if not l.filled]
    
    def get_filled_levels(self) -> List[GridLevel]:
        return [l for l in self.grid_levels if l.filled]
    
    def calculate_unrealized_pnl(self, current_price: float) -> float:
        """Unrealized PnL = MTM of filled BUYs whose paired SELL is NOT yet filled.

        BUY is considered "open" only if no filled SELL references it as pair_id.
        This avoids double-counting BUYs that have already been closed by a SELL.
        """
        levels_by_id = {l.level_id: l for l in self.grid_levels if l.level_id is not None}
        closed_buy_ids = {
            l.pair_id for l in self.grid_levels
            if l.filled and l.side == "sell" and l.pair_id is not None and l.pair_id in levels_by_id
        }

        pnl = 0.0
        for level in self.grid_levels:
            if not (level.filled and level.side == "buy"):
                continue
            if level.level_id is not None and level.level_id in closed_buy_ids:
                continue
            pnl += (current_price - level.price) * level.amount
        return pnl

    def calculate_realized_pnl(self) -> float:
        """Realized PnL = sum over filled SELLs paired (via pair_id) with a filled BUY.

        Falls back to FIFO chronological matching for legacy levels that lack pair_id
        (e.g. positions restored from older state files without level_id metadata).
        """
        levels_by_id = {l.level_id: l for l in self.grid_levels if l.level_id is not None}

        pnl = 0.0
        legacy_sells = []
        legacy_buy_ids = set()

        for sell in self.grid_levels:
            if not (sell.filled and sell.side == "sell"):
                continue
            if sell.pair_id is not None and sell.pair_id in levels_by_id:
                buy = levels_by_id[sell.pair_id]
                if buy.filled and buy.side == "buy":
                    matched = min(buy.amount, sell.amount)
                    pnl += (sell.price - buy.price) * matched
                    legacy_buy_ids.add(buy.level_id)
                    continue
            legacy_sells.append(sell)

        if legacy_sells:
            legacy_buys = sorted(
                [l for l in self.grid_levels
                 if l.filled and l.side == "buy" and l.level_id not in legacy_buy_ids],
                key=lambda x: x.filled_at or datetime.min
            )
            legacy_sells.sort(key=lambda x: x.filled_at or datetime.min)
            for buy, sell in zip(legacy_buys, legacy_sells):
                if buy.filled_at and sell.filled_at and buy.filled_at < sell.filled_at:
                    pnl += (sell.price - buy.price) * min(buy.amount, sell.amount)
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
            self.config.total_investment * (
                settings.grid.get_min_profit_threshold_percent(self.symbol) / 100
            )
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

        # Preserve historical filled levels (with their original prices,
        # amounts, level_id and pair_id) so realized/unrealized PnL stays
        # consistent across the rebalance. ``_create_grid_levels`` (called
        # from ``initialize_grid``) clears ``self.grid_levels``, which
        # previously dropped this history and silently zeroed past PnL.
        history = [l for l in self.grid_levels if l.filled]

        self.initialize_grid(
            current_price, atr, self.config.total_investment, data,
            _is_rebalance=True,
        )

        # Re-attach historical levels alongside the freshly-built grid.
        # They are kept marked as filled so they are not treated as active
        # orders, but they remain visible to the PnL calculations and to
        # ``get_filled_levels``.
        if history:
            self.grid_levels.extend(history)
            self.grid_levels.sort(key=lambda l: l.price)

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
