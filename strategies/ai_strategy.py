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
    def __init__(self, model_path: Optional[str] = None, model_type: str = None):
        super().__init__(name="ai_strategy")
        self.config = settings.strategy
        self.model = None
        self.model_path = model_path or self.config.model_path
        self.model_type = model_type or self.config.model_type
        self.feature_columns = FEATURE_COLUMNS
        
        if self.model_path:
            self.load_model(self.model_path)

    def build_strategy(self, data_source=None, start_date: str = None, end_date: str = None, symbol: str = None):
        return None
    
    def calculate_features(self, data: pd.DataFrame) -> pd.DataFrame:
        df = TechnicalIndicators.add_all_indicators(data, self.config)
        return df
    
    def prepare_features(self, data: pd.DataFrame) -> pd.DataFrame:
        if not all(col in data.columns for col in self.feature_columns):
            data = self.calculate_features(data)
        
        features = data[self.feature_columns].dropna()
        return features
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
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
                metadata={'prediction': 1}
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
                metadata={'prediction': -1}
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
        try:
            with open(path, 'rb') as f:
                self.model = pickle.load(f)
            logger.info(f"Loaded model from {path}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            self.model = None
    
    def save_model(self, path: str) -> None:
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
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, classification_report
        
        data = self.calculate_features(data)
        data = self.create_labels(data)
        
        features = data[self.feature_columns].dropna()
        labels = data.loc[features.index, label_column]
        
        X_train, X_test, y_train, y_test = train_test_split(
            features, labels, test_size=test_size, shuffle=False
        )
        
        if self.model_type == 'xgboost':
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
        
        train_pred = self.model.predict(X_train)
        test_pred = self.model.predict(X_test)
        
        metrics = {
            'train_accuracy': accuracy_score(y_train, train_pred),
            'test_accuracy': accuracy_score(y_test, test_pred),
            'classification_report': classification_report(y_test, test_pred)
        }
        
        logger.info(f"Model trained: train_acc={metrics['train_accuracy']:.3f}, test_acc={metrics['test_accuracy']:.3f}")
        
        return metrics
    
    def create_labels(
        self,
        data: pd.DataFrame,
        forward_periods: int = 10,
        threshold: float = 0.002
    ) -> pd.DataFrame:
        data = data.copy()
        
        data['forward_return'] = data['close'].shift(-forward_periods) / data['close'] - 1
        
        conditions = [
            data['forward_return'] > threshold,
            data['forward_return'] < -threshold
        ]
        choices = [2, 0]
        
        data['label'] = np.select(conditions, choices, default=1)
        
        return data
