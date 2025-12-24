from typing import Optional
from datetime import datetime
from loguru import logger

from learning.database import LearningDatabase
from data.models import Signal


class PredictionTracker:
    def __init__(self, db: LearningDatabase):
        self.db = db
        self._active_predictions = {}

    async def log_prediction(
        self,
        symbol: str,
        signal: Signal,
        model_id: str
    ) -> str:
        prediction_id = await self.db.save_prediction(
            symbol=symbol,
            model_version_id=model_id,
            predicted_signal=self._signal_to_int(signal.signal_type),
            confidence=signal.confidence,
            entry_price=signal.entry_price
        )
        
        self._active_predictions[symbol] = {
            'id': prediction_id,
            'signal': signal,
            'model_id': model_id,
            'timestamp': datetime.utcnow()
        }
        
        logger.info(f"Logged prediction {prediction_id} for {symbol}: {signal.signal_type} @ {signal.confidence:.2%}")
        return prediction_id

    async def update_prediction_outcome(
        self,
        symbol: str,
        actual_outcome: int,
        exit_price: float,
        pnl: float
    ) -> None:
        if symbol not in self._active_predictions:
            logger.warning(f"No active prediction found for {symbol}")
            return
        
        prediction = self._active_predictions[symbol]
        
        await self.db.update_prediction_outcome(
            prediction_id=prediction['id'],
            actual_outcome=actual_outcome,
            exit_price=exit_price,
            pnl=pnl
        )
        
        logger.info(f"Updated prediction {prediction['id']}: outcome={actual_outcome}, pnl={pnl:.2f}")
        del self._active_predictions[symbol]

    async def get_recent_accuracy(
        self,
        symbol: str,
        days: int = 7
    ) -> tuple[float, int]:
        predictions = await self.db.get_predictions_with_outcomes(symbol, days)
        
        if not predictions:
            return 0.0, 0
        
        total = len(predictions)
        correct = sum(1 for p in predictions 
                     if p['predicted_signal'] == p['actual_outcome'])
        
        accuracy = correct / total if total > 0 else 0.0
        return accuracy, total

    async def get_recent_pnl(
        self,
        symbol: str,
        days: int = 7
    ) -> float:
        predictions = await self.db.get_predictions_with_outcomes(symbol, days)
        
        if not predictions:
            return 0.0
        
        total_pnl = sum(p['pnl'] for p in predictions if p['pnl'] is not None)
        return total_pnl

    def _signal_to_int(self, signal_type) -> int:
        signal_map = {
            'buy': 2,
            'sell': 0,
            'hold': 1
        }
        return signal_map.get(signal_type.lower(), 1)
