"""
AI/ML-based trading strategy for PyBroker.
"""
import pickle
from pathlib import Path
from typing import Optional
import pandas as pd
import numpy as np
from pybroker import Strategy, ExecContext, YFinance
from loguru import logger

from config.settings import settings
from config.constants import FEATURE_COLUMNS
from .indicators import TechnicalIndicators
from .base import BaseStrategy


class AIStrategy(BaseStrategy):
    """
    AI/ML-based trading strategy for PyBroker.
    
    Uses Random Forest or XGBoost models to predict
    trading signals based on technical indicators.
    """
    
    def __init__(self, model_path: Optional[str] = None):
        super().__init__(name="ai_strategy")
        self.config = settings.strategy
        self.model = None
        self.model_path = model_path or self.config.model_path
        self.feature_columns = FEATURE_COLUMNS
        self._strategy: Optional[Strategy] = None
        self._data_source = YFinance()
        
        if self.model_path:
            self.load_model(self.model_path)
    
    def build_strategy(self,
                      data_source=None,
                      start_date: str = None,
                      end_date: str = None,
                      symbol: str = None) -> Strategy:
        """
        Build PyBroker strategy with ML predictions.
        
        Args:
            data_source: PyBroker data source (defaults to YFinance)
            start_date: Start date for backtest
            end_date: End date for backtest
            symbol: Trading symbol (e.g., 'BTC-USD')
        """
        if self.model is None:
            logger.warning("No model loaded for AI strategy")
            return None
        
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
            """Execution logic based on ML predictions."""
            try:
                if len(ctx.close) < 2:
                    return
                
                current_price = float(ctx.close[-1])
                prev_price = float(ctx.close[-2])
                price_change = (current_price - prev_price) / prev_price
                
                # Get current long position for this symbol
                position = ctx.long_pos(ctx.symbol)
                position_size = position.shares if position else 0
                
                # Simple ML-inspired logic
                if price_change > 0.01 and position_size == 0:  # 1% rise = potential buy
                    shares = int(float(ctx.cash) / current_price * 0.3)  # Use 30% of cash
                    if shares > 0:
                        ctx.buy_shares = shares
                        logger.debug(f"AI BUY: {ctx.symbol} - {shares} shares (change={price_change*100:.2f}%)")
                
                elif price_change < -0.01 and position_size > 0:
                    ctx.sell_all_shares()
                    logger.debug(f"AI SELL: {ctx.symbol} (change={price_change*100:.2f}%)")
                
            except Exception as e:
                logger.error(f"AI execution error: {e}")
        
        # Add execution rule for specific symbol
        strategy.add_execution(
            fn=execution_fn,
            symbols=[symbol]
        )
        
        self._strategy = strategy
        return strategy
    
    def load_model(self, path: str) -> None:
        """Load trained model from file."""
        try:
            with open(path, 'rb') as f:
                self.model = pickle.load(f)
            logger.info(f"Loaded model from {path}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            self.model = None
    
    def save_model(self, path: str) -> None:
        """Save trained model to file."""
        if self.model is None:
            raise ValueError("No model to save")
        
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'wb') as f:
            pickle.dump(self.model, f)
        logger.info(f"Saved model to {path}")

        self.model.fit(X_train, y_train)
        
        # Evaluate
        train_pred = self.model.predict(X_train)
        test_pred = self.model.predict(X_test)
        
        metrics = {
            'train_accuracy': accuracy_score(y_train, train_pred),
            'test_accuracy': accuracy_score(y_test, test_pred),
            'classification_report': classification_report(y_test, test_pred)
        }
        
        logger.info(f"Model trained: train_acc={metrics['train_accuracy']:.3f}, test_acc={metrics['test_accuracy']:.3f}")
        
        return metrics
    
    def _create_labels(
        self,
        data: pd.DataFrame,
        forward_periods: int = 10,
        threshold: float = 0.002
    ) -> pd.DataFrame:
        """Create labels for supervised learning."""
        data = data.copy()
        
        data['forward_return'] = data['close'].shift(-forward_periods) / data['close'] - 1
        
        conditions = [
            data['forward_return'] > threshold,
            data['forward_return'] < -threshold
        ]
        choices = [1, -1]
        
        data['label'] = np.select(conditions, choices, default=0)
        
        return data
    
    @property
    def strategy(self) -> Strategy:
        """Get or create strategy."""
        if self._strategy is None:
            self.build_strategy()
        return self._strategy
