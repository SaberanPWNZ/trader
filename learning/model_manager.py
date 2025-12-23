import os
import pickle
from datetime import datetime
from typing import Optional, List
from pathlib import Path
from loguru import logger

from config.settings import settings
from learning.database import LearningDatabase


class ModelManager:
    def __init__(self, db: LearningDatabase):
        self.db = db
        self.config = settings.self_learning
        self.models_dir = settings.models_dir
        self._loaded_models: dict = {}

    async def get_active_model(self, symbol: str):
        deployed = await self.db.get_deployed_model(symbol)
        if not deployed:
            latest = await self.db.get_latest_model(symbol)
            if latest:
                await self.db.deploy_model(latest["id"], symbol)
                deployed = latest
        
        if not deployed:
            return None

        model_path = deployed["model_path"]
        if symbol in self._loaded_models:
            cached_path, model = self._loaded_models[symbol]
            if cached_path == model_path:
                return model

        model = self._load_model_from_file(model_path)
        if model:
            self._loaded_models[symbol] = (model_path, model)
        return model

    def _load_model_from_file(self, path: str):
        try:
            with open(path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            logger.error(f"Failed to load model from {path}: {e}")
            return None

    async def deploy_model(self, model_id: str, symbol: str) -> bool:
        model_info = None
        models = await self.db.get_models(symbol)
        for m in models:
            if m["id"] == model_id:
                model_info = m
                break
        
        if not model_info:
            logger.error(f"Model {model_id} not found")
            return False

        if not Path(model_info["model_path"]).exists():
            logger.error(f"Model file not found: {model_info['model_path']}")
            return False

        await self.db.deploy_model(model_id, symbol)
        
        if symbol in self._loaded_models:
            del self._loaded_models[symbol]

        logger.info(f"Deployed model {model_id} for {symbol}")
        return True

    async def rollback_model(self, symbol: str) -> Optional[str]:
        models = await self.db.get_models(symbol, limit=5)
        deployed_idx = -1
        for i, m in enumerate(models):
            if m["is_deployed"]:
                deployed_idx = i
                break

        if deployed_idx < 0 or deployed_idx >= len(models) - 1:
            logger.warning(f"No previous model to rollback to for {symbol}")
            return None

        previous_model = models[deployed_idx + 1]
        await self.db.deploy_model(previous_model["id"], symbol)
        
        if symbol in self._loaded_models:
            del self._loaded_models[symbol]

        logger.info(f"Rolled back to model {previous_model['id']} for {symbol}")
        return previous_model["id"]

    async def cleanup_old_models(self, symbol: str) -> int:
        models = await self.db.get_models(symbol, limit=100)
        if len(models) <= self.config.max_models_to_keep:
            return 0

        models_to_delete = models[self.config.max_models_to_keep:]
        deleted_count = 0
        
        for model in models_to_delete:
            if model["is_deployed"]:
                continue
            try:
                model_path = Path(model["model_path"])
                if model_path.exists():
                    model_path.unlink()
                    deleted_count += 1
                    logger.debug(f"Deleted old model file: {model_path}")
            except Exception as e:
                logger.error(f"Failed to delete model file: {e}")

        return deleted_count

    async def get_model_comparison(self, symbol: str, limit: int = 5) -> List[dict]:
        models = await self.db.get_models(symbol, limit=limit)
        return [{
            "id": m["id"],
            "created_at": m["created_at"],
            "test_accuracy": m["test_accuracy"],
            "train_accuracy": m["train_accuracy"],
            "samples": m["samples_trained"],
            "is_deployed": m["is_deployed"]
        } for m in models]
