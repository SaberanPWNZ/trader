import time
import pickle
from datetime import datetime, timedelta
from typing import Optional, Tuple
from pathlib import Path
import pandas as pd
from loguru import logger

from config.settings import settings
from strategies.ai_strategy import AIStrategy
from learning.database import LearningDatabase


class AutoTrainer:
    def __init__(self, db: LearningDatabase):
        self.db = db
        self.config = settings.self_learning
        self.models_dir = settings.models_dir

    async def train_model(
        self,
        symbol: str,
        data: pd.DataFrame,
        model_type: str = "xgboost"
    ) -> Tuple[str, dict]:
        start_time = time.time()
        logger.info(f"Starting training for {symbol} with {len(data)} samples")

        strategy = AIStrategy(model_type=model_type)
        data_with_features = strategy.calculate_features(data)
        data_with_labels = strategy.create_labels(data_with_features)
        prepared_data = data_with_labels.dropna()

        if len(prepared_data) < self.config.min_samples_for_training:
            raise ValueError(f"Insufficient samples: {len(prepared_data)} < {self.config.min_samples_for_training}")

        metrics = strategy.train(prepared_data)
        duration = time.time() - start_time

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        model_filename = f"{symbol.replace('/', '_')}_{model_type}_{timestamp}.pkl"
        model_path = str(self.models_dir / model_filename)
        strategy.save_model(model_path)

        model_id = await self.db.save_model(
            symbol=symbol,
            model_type=model_type,
            train_accuracy=metrics.get("train_accuracy", 0),
            test_accuracy=metrics.get("test_accuracy", 0),
            samples_trained=len(prepared_data),
            model_path=model_path,
            sharpe_ratio=metrics.get("sharpe_ratio"),
            notes=f"Auto-trained on {datetime.utcnow().date()}"
        )

        return model_id, {
            "model_id": model_id,
            "train_accuracy": metrics.get("train_accuracy", 0),
            "test_accuracy": metrics.get("test_accuracy", 0),
            "samples": len(prepared_data),
            "duration_seconds": duration,
            "model_path": model_path
        }

    async def should_retrain(self, symbol: str) -> Tuple[bool, str]:
        last_run = await self.db.get_last_training_run(symbol)
        if not last_run:
            return True, "No previous training found"

        last_training_time = datetime.fromisoformat(str(last_run["timestamp"]))
        hours_since_training = (datetime.utcnow() - last_training_time).total_seconds() / 3600

        if hours_since_training < self.config.training_interval_hours:
            return False, f"Last training was {hours_since_training:.1f}h ago"

        return True, f"Time for scheduled retraining ({hours_since_training:.1f}h since last)"

    async def evaluate_improvement(
        self,
        symbol: str,
        new_accuracy: float
    ) -> Tuple[bool, float, float]:
        current_model = await self.db.get_deployed_model(symbol)
        if not current_model:
            return True, 0, new_accuracy

        old_accuracy = current_model.get("test_accuracy", 0)
        improvement = (new_accuracy - old_accuracy) / old_accuracy if old_accuracy > 0 else 1.0

        should_deploy = improvement >= self.config.min_accuracy_improvement
        return should_deploy, old_accuracy, improvement

    async def run_training_cycle(
        self,
        symbol: str,
        data: pd.DataFrame,
        model_type: str = "xgboost"
    ) -> dict:
        should_train, reason = await self.should_retrain(symbol)
        if not should_train:
            return {"status": "skipped", "reason": reason}

        try:
            model_id, metrics = await self.train_model(symbol, data, model_type)

            should_deploy, old_accuracy, improvement = await self.evaluate_improvement(
                symbol, metrics["test_accuracy"]
            )

            train_start = data.index.min().strftime("%Y-%m-%d") if hasattr(data.index, 'min') else "unknown"
            train_end = data.index.max().strftime("%Y-%m-%d") if hasattr(data.index, 'max') else "unknown"

            await self.db.save_training_run(
                symbol=symbol,
                model_version_id=model_id,
                train_start_date=train_start,
                train_end_date=train_end,
                samples=metrics["samples"],
                train_accuracy=metrics["train_accuracy"],
                test_accuracy=metrics["test_accuracy"],
                previous_accuracy=old_accuracy,
                improvement=improvement,
                duration_seconds=metrics["duration_seconds"],
                status="success"
            )

            if should_deploy and self.config.auto_deploy_enabled:
                await self.db.deploy_model(model_id, symbol)
                logger.info(f"Auto-deployed model {model_id} for {symbol} (improvement: {improvement:.1%})")

            return {
                "status": "success",
                "model_id": model_id,
                "train_accuracy": metrics["train_accuracy"],
                "test_accuracy": metrics["test_accuracy"],
                "samples": metrics["samples"],
                "duration_seconds": metrics["duration_seconds"],
                "improvement": improvement,
                "previous_accuracy": old_accuracy,
                "deployed": should_deploy and self.config.auto_deploy_enabled,
                "model_path": metrics["model_path"]
            }

        except Exception as e:
            logger.error(f"Training failed for {symbol}: {e}")
            await self.db.save_training_run(
                symbol=symbol,
                model_version_id="",
                train_start_date="",
                train_end_date="",
                samples=0,
                train_accuracy=0,
                test_accuracy=0,
                previous_accuracy=0,
                improvement=0,
                duration_seconds=0,
                status=f"failed: {str(e)}"
            )
            return {"status": "failed", "error": str(e)}
