"""
AI/ML-based trading strategy for PyBroker.
"""
import pickle
from pathlib import Path
from typing import Optional
import pandas as pd
import numpy as np
from pybroker import Strategy, ExecContext
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
        self._strategy: Strategy = None
        
        if self.model_path:
            self.load_model(self.model_path)
    
    def build_strategy(self) -> Strategy:
        """Build PyBroker strategy with ML predictions."""
        if self._strategy is not None:
            return self._strategy
        
        if self.model is None:
            logger.warning("No model loaded for AI strategy")
            return None
        
        strategy = Strategy(ctx=None)
        
        @strategy.indicator()
        def add_indicators(data: pd.DataFrame) -> pd.DataFrame:
            """Add technical indicators."""
            return TechnicalIndicators.add_all_indicators(data, self.config)
        
        @strategy.entry(add_indicators)
        def entry_logic(ctx: ExecContext) -> None:
            """Entry logic based on ML predictions."""
            indicators = ctx.indicator()
            
            # Extract features
            features = indicators[self.feature_columns].iloc[-1:].fillna(0)
            
            if features.empty:
                return
            
            # Get prediction
            try:
                prediction = self.model.predict(features)[0]
                
                # Get confidence
                confidence = self.config.min_confidence
                if hasattr(self.model, 'predict_proba'):
                    probas = self.model.predict_proba(features)[0]
                    confidence = max(probas)
                
                # BUY signal (prediction == 1)
                if prediction == 1 and confidence >= self.config.min_confidence:
                    size = ctx.portfolio.size if ctx.portfolio else 0.1
                    ctx.buy_shares = max(size, 0.01)
                    logger.info(f"AI BUY: {ctx.symbol} (conf={confidence:.2f})")
                
            except Exception as e:
                logger.error(f"Prediction error: {e}")
        
        @strategy.exit()
        def exit_logic(ctx: ExecContext) -> None:
            """Exit logic for ML positions."""
            if not ctx.position:
                return
            
            indicators = ctx.indicator()
            features = indicators[self.feature_columns].iloc[-1:].fillna(0)
            
            if features.empty:
                return
            
            try:
                prediction = self.model.predict(features)[0]
                
                # Exit long on SELL prediction
                if ctx.position.size > 0 and prediction == -1:
                    ctx.close_all_shares()
                    logger.info(f"AI SELL: {ctx.symbol}")
                
                # Exit short on BUY prediction
                elif ctx.position.size < 0 and prediction == 1:
                    ctx.close_all_shares()
                    logger.info(f"AI CLOSE SHORT: {ctx.symbol}")
            
            except Exception as e:
                logger.error(f"Exit logic error: {e}")
        
        self._strategy = strategy
        return self._strategy
    
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
    
    def train(
        self,
        data: pd.DataFrame,
        label_column: str = 'label',
        test_size: float = 0.2
    ) -> dict:
        """
        Train the ML model.
        
        Args:
            data: DataFrame with features and labels
            label_column: Name of label column
            test_size: Test set proportion
            
        Returns:
            Training metrics
        """
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, classification_report
        
        # Prepare features and labels
        data = TechnicalIndicators.add_all_indicators(data, self.config)
        data = self._create_labels(data)
        
        features = data[self.feature_columns].dropna()
        labels = data.loc[features.index, label_column]
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            features, labels, test_size=test_size, shuffle=False
        )
        
        # Create and train model
        if self.config.model_type == 'xgboost':
            try:
                from xgboost import XGBClassifier
                self.model = XGBClassifier(
                    n_estimators=100,
                    max_depth=5,
                    learning_rate=0.1,
                    random_state=42
                )
            except ImportError:
                logger.warning("XGBoost not available, using RandomForest")
                from sklearn.ensemble import RandomForestClassifier
                self.model = RandomForestClassifier(
                    n_estimators=100,
                    max_depth=10,
                    random_state=42
                )
        else:
            from sklearn.ensemble import RandomForestClassifier
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42
            )
        
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
