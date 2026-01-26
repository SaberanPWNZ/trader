"""
AI/ML-based trading strategy.
"""
import pickle
from pathlib import Path
from typing import Optional, Tuple
import pandas as pd
import numpy as np
from loguru import logger
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.metrics import accuracy_score, classification_report

from config.settings import settings
from config.constants import SignalType, FEATURE_COLUMNS
from data.models import Signal
from .base import BaseStrategy
from .indicators import TechnicalIndicators


class AIStrategy(BaseStrategy):
    def __init__(self, model_path: Optional[str] = None, model_type: str = None, db = None):
        super().__init__(name="ai_strategy")
        self.config = settings.strategy
        self.model = None
        self.model_path = model_path or self.config.model_path
        self.model_type = model_type or self.config.model_type
        self.feature_columns = FEATURE_COLUMNS
        self.db = db
        self._loaded_models = {}
        
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
    
    async def load_model_for_symbol(self, symbol: str) -> bool:
        """Load deployed model for symbol from database."""
        if symbol in self._loaded_models:
            self.model = self._loaded_models[symbol]
            return True
        
        if self.db is None:
            return False
        
        try:
            deployed = await self.db.get_deployed_model(symbol)
            if not deployed:
                logger.debug(f"No deployed model for {symbol}")
                return False
            
            model_path = deployed['model_path']
            if not Path(model_path).exists():
                logger.warning(f"Model file not found: {model_path}")
                return False
            
            with open(model_path, 'rb') as f:
                model = pickle.load(f)
            
            self._loaded_models[symbol] = model
            self.model = model
            logger.info(f"Loaded model for {symbol} from {model_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load model for {symbol}: {e}")
            return False
    
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        symbol = data.get('symbol', ['UNKNOWN']).iloc[-1] if 'symbol' in data.columns else 'UNKNOWN'
        
        if self.model is None:
            logger.warning(f"No model loaded for {symbol}, returning HOLD signal")
            return self.create_signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=0.0
            )
        
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
        
        X = features.iloc[[-1]].values
        prediction = self.model.predict(X)[0]
        
        confidence = 0.5
        if hasattr(self.model, 'predict_proba'):
            probas = self.model.predict_proba(X)[0]
            confidence = max(probas)
        
        confidence_threshold = settings.self_learning.confidence_threshold
        
        if confidence < confidence_threshold:
            logger.debug(f"AI HOLD signal for {symbol}: low confidence={confidence:.2f}")
            return self.create_signal(
                symbol=symbol,
                signal_type=SignalType.HOLD,
                confidence=confidence,
                metadata={'prediction': int(prediction), 'reason': 'low_confidence'}
            )
        
        if prediction == 1:
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
        else:
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
                metadata={'prediction': 0}
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
        learning_config = settings.self_learning
        
        data = self.calculate_features(data)
        data = self.create_labels(data, threshold=learning_config.label_threshold)
        
        valid_data = data.dropna(subset=self.feature_columns + [label_column])
        features = valid_data[self.feature_columns]
        labels = valid_data[label_column]
        
        if len(features) < learning_config.min_samples_for_training:
            logger.warning(f"Insufficient data: {len(features)} samples, need {learning_config.min_samples_for_training}")
            return {'error': 'insufficient_data', 'samples': len(features)}
        
        split_idx = int(len(features) * (1 - test_size))
        X_train, X_test = features.iloc[:split_idx], features.iloc[split_idx:]
        y_train, y_test = labels.iloc[:split_idx], labels.iloc[split_idx:]
        
        pos_count = (y_train == 1).sum()
        neg_count = (y_train == 0).sum()
        scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0
        
        logger.info(f"Training data: {len(y_train)} samples, pos={pos_count}, neg={neg_count}, scale={scale_pos_weight:.2f}")
        
        cv_splits = learning_config.cv_splits
        tscv = TimeSeriesSplit(n_splits=cv_splits)
        
        if self.model_type == 'xgboost':
            try:
                from xgboost import XGBClassifier
                base_model = XGBClassifier(
                    random_state=42,
                    scale_pos_weight=scale_pos_weight,
                    eval_metric='logloss',
                    reg_alpha=0.1,
                    reg_lambda=1.0,
                    subsample=0.8,
                    colsample_bytree=0.8
                )
                if learning_config.hyperparameter_tuning:
                    param_grid = {
                        'n_estimators': [50, 100],
                        'max_depth': [3, 4, 5],
                        'learning_rate': [0.01, 0.03, 0.05],
                        'min_child_weight': [3, 5, 7]
                    }
                    grid_search = GridSearchCV(
                        base_model, param_grid, cv=tscv, scoring='accuracy', n_jobs=-1
                    )
                    grid_search.fit(X_train, y_train)
                    self.model = grid_search.best_estimator_
                    best_params = grid_search.best_params_
                    cv_score = grid_search.best_score_
                    logger.info(f"Best params: {best_params}, CV score: {cv_score:.3f}")
                else:
                    base_model.set_params(n_estimators=100, max_depth=5, learning_rate=0.05)
                    base_model.fit(X_train, y_train)
                    self.model = base_model
                    best_params = {}
                    cv_score = 0.0
            except ImportError:
                logger.warning("XGBoost not available, using RandomForest")
                self.model_type = 'randomforest'
        
        if self.model_type != 'xgboost':
            from sklearn.ensemble import RandomForestClassifier
            base_model = RandomForestClassifier(
                random_state=42,
                class_weight='balanced'
            )
            if learning_config.hyperparameter_tuning:
                param_grid = {
                    'n_estimators': [50, 100, 200],
                    'max_depth': [5, 10, 15],
                    'min_samples_split': [2, 5, 10]
                }
                grid_search = GridSearchCV(
                    base_model, param_grid, cv=tscv, scoring='accuracy', n_jobs=-1
                )
                grid_search.fit(X_train, y_train)
                self.model = grid_search.best_estimator_
                best_params = grid_search.best_params_
                cv_score = grid_search.best_score_
                logger.info(f"Best params: {best_params}, CV score: {cv_score:.3f}")
            else:
                base_model.set_params(n_estimators=100, max_depth=10)
                base_model.fit(X_train, y_train)
                self.model = base_model
                best_params = {}
                cv_score = 0.0
        
        train_pred = self.model.predict(X_train)
        test_pred = self.model.predict(X_test)
        
        train_accuracy = accuracy_score(y_train, train_pred)
        test_accuracy = accuracy_score(y_test, test_pred)
        
        metrics = {
            'train_accuracy': train_accuracy,
            'test_accuracy': test_accuracy,
            'cv_score': cv_score,
            'best_params': best_params,
            'samples_used': len(features),
            'class_balance': {'positive': int(pos_count), 'negative': int(neg_count)},
            'classification_report': classification_report(y_test, test_pred)
        }
        
        logger.info(f"Model trained: train_acc={train_accuracy:.3f}, test_acc={test_accuracy:.3f}, cv={cv_score:.3f}")
        
        return metrics
    
    def create_labels(
        self,
        data: pd.DataFrame,
        forward_periods: int = 10,
        threshold: float = 0.005
    ) -> pd.DataFrame:
        data = data.copy()
        
        data['forward_return'] = data['close'].shift(-forward_periods) / data['close'] - 1
        
        data['label'] = np.where(data['forward_return'] > threshold, 1, 
                                 np.where(data['forward_return'] < -threshold, 0, np.nan))
        
        initial_count = len(data)
        data = data.dropna(subset=['label'])
        filtered_count = initial_count - len(data)
        
        if filtered_count > 0:
            logger.debug(f"Filtered {filtered_count} neutral samples ({filtered_count/initial_count*100:.1f}%)")
        
        data['label'] = data['label'].astype(int)
        
        return data
