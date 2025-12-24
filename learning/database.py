import aiosqlite
import uuid
from datetime import datetime
from typing import Optional, List
from pathlib import Path
from loguru import logger

from config.settings import settings


class LearningDatabase:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.self_learning.db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    train_accuracy REAL NOT NULL,
                    test_accuracy REAL NOT NULL,
                    sharpe_ratio REAL,
                    samples_trained INTEGER NOT NULL,
                    model_path TEXT NOT NULL,
                    is_deployed BOOLEAN DEFAULT FALSE,
                    notes TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS training_runs (
                    id TEXT PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    symbol TEXT NOT NULL,
                    model_version_id TEXT REFERENCES models(id),
                    train_start_date TEXT,
                    train_end_date TEXT,
                    samples INTEGER,
                    train_accuracy REAL,
                    test_accuracy REAL,
                    previous_accuracy REAL,
                    improvement REAL,
                    duration_seconds REAL,
                    status TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id TEXT PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    symbol TEXT NOT NULL,
                    model_version_id TEXT REFERENCES models(id),
                    predicted_signal INTEGER,
                    confidence REAL,
                    actual_outcome INTEGER,
                    entry_price REAL,
                    exit_price REAL,
                    pnl REAL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_models_symbol ON models(symbol)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_symbol ON predictions(symbol)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_training_runs_symbol ON training_runs(symbol)
            """)
            await db.commit()
        self._initialized = True
        logger.info(f"Learning database initialized at {self.db_path}")

    async def save_model(
        self,
        symbol: str,
        model_type: str,
        train_accuracy: float,
        test_accuracy: float,
        samples_trained: int,
        model_path: str,
        sharpe_ratio: Optional[float] = None,
        notes: Optional[str] = None
    ) -> str:
        model_id = str(uuid.uuid4())[:8]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO models (id, symbol, model_type, created_at, train_accuracy, 
                    test_accuracy, sharpe_ratio, samples_trained, model_path, is_deployed, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (model_id, symbol, model_type, datetime.utcnow(), train_accuracy,
                  test_accuracy, sharpe_ratio, samples_trained, model_path, False, notes))
            await db.commit()
        return model_id

    async def get_deployed_model(self, symbol: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM models WHERE symbol = ? AND is_deployed = TRUE
                ORDER BY created_at DESC LIMIT 1
            """, (symbol,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_latest_model(self, symbol: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM models WHERE symbol = ?
                ORDER BY created_at DESC LIMIT 1
            """, (symbol,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def deploy_model(self, model_id: str, symbol: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE models SET is_deployed = FALSE WHERE symbol = ?
            """, (symbol,))
            await db.execute("""
                UPDATE models SET is_deployed = TRUE WHERE id = ?
            """, (model_id,))
            await db.commit()

    async def update_model_sharpe(self, model_id: str, sharpe_ratio: Optional[float]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE models SET sharpe_ratio = ? WHERE id = ?
            """, (sharpe_ratio, model_id))
            await db.commit()

    async def get_models(self, symbol: Optional[str] = None, limit: int = 10) -> List[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if symbol:
                query = "SELECT * FROM models WHERE symbol = ? ORDER BY created_at DESC LIMIT ?"
                params = (symbol, limit)
            else:
                query = "SELECT * FROM models ORDER BY created_at DESC LIMIT ?"
                params = (limit,)
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def save_training_run(
        self,
        symbol: str,
        model_version_id: str,
        train_start_date: str,
        train_end_date: str,
        samples: int,
        train_accuracy: float,
        test_accuracy: float,
        previous_accuracy: float,
        improvement: float,
        duration_seconds: float,
        status: str
    ) -> str:
        run_id = str(uuid.uuid4())[:8]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO training_runs (id, timestamp, symbol, model_version_id, 
                    train_start_date, train_end_date, samples, train_accuracy, test_accuracy,
                    previous_accuracy, improvement, duration_seconds, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, datetime.utcnow(), symbol, model_version_id, train_start_date,
                  train_end_date, samples, train_accuracy, test_accuracy, previous_accuracy,
                  improvement, duration_seconds, status))
            await db.commit()
        return run_id

    async def get_training_runs(self, symbol: Optional[str] = None, limit: int = 10) -> List[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if symbol:
                query = "SELECT * FROM training_runs WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?"
                params = (symbol, limit)
            else:
                query = "SELECT * FROM training_runs ORDER BY timestamp DESC LIMIT ?"
                params = (limit,)
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_last_training_run(self, symbol: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM training_runs WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1
            """, (symbol,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def save_prediction(
        self,
        symbol: str,
        model_version_id: str,
        predicted_signal: int,
        confidence: float,
        entry_price: Optional[float] = None
    ) -> str:
        pred_id = str(uuid.uuid4())[:8]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO predictions (id, timestamp, symbol, model_version_id,
                    predicted_signal, confidence, entry_price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (pred_id, datetime.utcnow(), symbol, model_version_id,
                  predicted_signal, confidence, entry_price))
            await db.commit()
        return pred_id

    async def update_prediction_outcome(
        self,
        prediction_id: str,
        actual_outcome: int,
        exit_price: float,
        pnl: float
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE predictions SET actual_outcome = ?, exit_price = ?, pnl = ?
                WHERE id = ?
            """, (actual_outcome, exit_price, pnl, prediction_id))
            await db.commit()

    async def get_prediction_accuracy(self, symbol: str, days: int = 30) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN predicted_signal = actual_outcome THEN 1 ELSE 0 END) as correct,
                    SUM(pnl) as total_pnl,
                    AVG(confidence) as avg_confidence
                FROM predictions 
                WHERE symbol = ? 
                    AND actual_outcome IS NOT NULL
                    AND timestamp >= datetime('now', ?)
            """, (symbol, f'-{days} days')) as cursor:
                row = await cursor.fetchone()
                total, correct, total_pnl, avg_confidence = row
                accuracy = correct / total if total > 0 else 0
                return {
                    "total_predictions": total or 0,
                    "correct_predictions": correct or 0,
                    "accuracy": accuracy,
                    "total_pnl": total_pnl or 0,
                    "avg_confidence": avg_confidence or 0
                }

    async def get_predictions_with_outcomes(
        self,
        symbol: str,
        days: int = 30
    ) -> List[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM predictions
                WHERE symbol = ?
                    AND actual_outcome IS NOT NULL
                    AND timestamp >= datetime('now', ?)
                ORDER BY timestamp DESC
            """, (symbol, f'-{days} days')) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_performance_summary(self, days: int = 30) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT 
                    symbol,
                    COUNT(*) as total_runs,
                    AVG(test_accuracy) as avg_accuracy,
                    MAX(test_accuracy) as best_accuracy,
                    AVG(improvement) as avg_improvement
                FROM training_runs 
                WHERE timestamp >= datetime('now', ?)
                    AND status = 'success'
                GROUP BY symbol
            """, (f'-{days} days',)) as cursor:
                rows = await cursor.fetchall()
                return {row['symbol']: dict(row) for row in rows}
