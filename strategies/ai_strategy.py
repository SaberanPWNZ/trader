"""
AI/ML-based trading strategy.
"""
import pickle
from pathlib import Path
from typing import Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger

from config.settings import settings
from config.constants import SignalType, FEATURE_COLUMNS
from data.models import Signal
from .base import BaseStrategy
from .indicators import TechnicalIndicators


class AIStrategy(BaseStrategy):
    """
    AI/ML-based trading strategy.
    
    Uses Random Forest or XGBoost models to predict
    trading signals based on technical indicators.
    """
    
    def __init__(self, model_path: Optional[str] = None):
        super().__init__(name="ai_strategy")
        self.config = settings.strategy
        self.model = None
        self.model_path = model_path or self.config.model_path
        self.feature_columns = FEATURE_COLUMNS
        
        if self.model_path:
            self.load_model(self.model_path)
    
    def calculate_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add technical indicators and prepare features."""
        df = TechnicalIndicators.add_all_indicators(data, self.config)
        return df
    
    def prepare_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare feature matrix for model prediction.
        
        Args:
            data: DataFrame with indicators
            
        Returns:
            Feature matrix
        """
        if not all(col in data.columns for col in self.feature_columns):
            data = self.calculate_features(data)
        
        features = data[self.feature_columns].dropna()
        return features
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """
        Generate trading signal using ML model.
        
        Args:
            data: DataFrame with OHLCV data
            
        Returns:
            Trading signal
        """
        if self.model is None:
            logger.warning("No model loaded, returning HOLD signal")
            return self.create_signal(
                symbol=data.get('symbol', ['UNKNOWN']).iloc[-1] if 'symbol' in data.columns else 'UNKNOWN',
                signal_type=SignalType.HOLD,
                confidence=0.0
            )
        
        # Prepare data
        data = self.calculate_features(data)
        features = self.prepare_features(data)
        
        if features.empty:
            return self.create_signal(
                symbol=data['symbol'].iloc[-1] if 'symbol' in data.columns else 'UNKNOWN',
                signal_type=SignalType.HOLD,
                confidence=0.0
            )
        
        current = data.iloc[-1]
        symbol = current.get('symbol', 'UNKNOWN')
        close_price = current['close']
        atr = current['atr']
        
        # Get prediction
        X = features.iloc[[-1]]
        prediction = self.model.predict(X)[0]
        
        # Get prediction probabilities if available
        confidence = self.config.min_confidence
        if hasattr(self.model, 'predict_proba'):
            probas = self.model.predict_proba(X)[0]
            confidence = max(probas)
        
        # Map prediction to signal
        if prediction == 1 and confidence >= self.config.min_confidence:
            stop_loss = close_price - (atr * self.config.stop_loss_atr_multiplier)
            take_profit = close_price + (atr * self.config.take_profit_atr_multiplier)
            
            logger.info(f"AI BUY signal for {symbol}: confidence={confidence:.2f}")
            
            return self.create_signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                confidence=confidence,
                entry_price=close_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                metadata={'prediction': prediction}
            )
        
        elif prediction == -1 and confidence >= self.config.min_confidence:
            stop_loss = close_price + (atr * self.config.stop_loss_atr_multiplier)
            take_profit = close_price - (atr * self.config.take_profit_atr_multiplier)
            
            logger.info(f"AI SELL signal for {symbol}: confidence={confidence:.2f}")
            
            return self.create_signal(
                symbol=symbol,
                signal_type=SignalType.SELL,
                confidence=confidence,
                entry_price=close_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                metadata={'prediction': prediction}
            )
        
        else:
            logger.debug(f"AI HOLD signal for {symbol}: confidence={confidence:.2f}")
            
            return self.create_signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=confidence,
                metadata={'prediction': prediction}
            )
    
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
        data = self.calculate_features(data)
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
        threshold: float = 0.002  # 0.2% minimum expected move
    ) -> pd.DataFrame:
        """
        Create labels for supervised learning.
        
        Labels:
        - BUY (1): Expected price increase > threshold
        - SELL (-1): Expected price decrease > threshold
        - HOLD (0): No clear edge
        
        Args:
            data: DataFrame with OHLCV data
            forward_periods: Lookahead periods for return calculation
            threshold: Minimum return threshold
            
        Returns:
            DataFrame with label column
        """
        data = data.copy()
        
        # Calculate forward returns
        data['forward_return'] = data['close'].shift(-forward_periods) / data['close'] - 1
        
        # Create labels
        conditions = [
            data['forward_return'] > threshold,
            data['forward_return'] < -threshold
        ]
        choices = [1, -1]  # BUY, SELL
        
        data['label'] = np.select(conditions, choices, default=0)  # HOLD
        
        return data
