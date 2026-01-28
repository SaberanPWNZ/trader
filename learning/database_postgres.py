import asyncpg
import os
from typing import Optional, List, Dict, Any
from datetime import datetime
from loguru import logger


class PostgresDatabase:
    def __init__(self, connection_url: Optional[str] = None):
        self.connection_url = connection_url or os.getenv(
            "DATABASE_URL",
            "postgresql://trader:password@localhost:5432/trading_bot"
        )
        self._pool: Optional[asyncpg.Pool] = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        try:
            self._pool = await asyncpg.create_pool(
                self.connection_url,
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            await self._create_tables()
            self._initialized = True
            logger.info("PostgreSQL database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL database: {e}")
            raise

    async def _create_tables(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    id VARCHAR(8) PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    model_type VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    train_accuracy NUMERIC(5,4) NOT NULL,
                    test_accuracy NUMERIC(5,4) NOT NULL,
                    sharpe_ratio NUMERIC(8,4),
                    samples_trained INTEGER NOT NULL,
                    model_path TEXT NOT NULL,
                    is_deployed BOOLEAN DEFAULT FALSE,
                    notes TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_models_symbol ON models(symbol);
                CREATE INDEX IF NOT EXISTS idx_models_deployed ON models(symbol, is_deployed) WHERE is_deployed = TRUE;
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS training_runs (
                    id VARCHAR(8) PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    model_version_id VARCHAR(8) REFERENCES models(id),
                    train_start_date TEXT,
                    train_end_date TEXT,
                    samples INTEGER,
                    train_accuracy NUMERIC(5,4),
                    test_accuracy NUMERIC(5,4),
                    previous_accuracy NUMERIC(5,4),
                    improvement NUMERIC(5,4),
                    duration_seconds NUMERIC(10,2),
                    status VARCHAR(20)
                );
                CREATE INDEX IF NOT EXISTS idx_training_runs_symbol ON training_runs(symbol);
                CREATE INDEX IF NOT EXISTS idx_training_runs_timestamp ON training_runs(timestamp DESC);
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id VARCHAR(8) PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    symbol VARCHAR(20) NOT NULL,
                    model_version_id VARCHAR(8) REFERENCES models(id),
                    predicted_signal INTEGER,
                    confidence NUMERIC(5,4),
                    actual_outcome INTEGER,
                    entry_price NUMERIC(12,6),
                    exit_price NUMERIC(12,6),
                    pnl NUMERIC(12,6)
                );
                CREATE INDEX IF NOT EXISTS idx_predictions_symbol ON predictions(symbol);
                CREATE INDEX IF NOT EXISTS idx_predictions_timestamp ON predictions(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_predictions_model ON predictions(model_version_id);
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS balance_history (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    balance NUMERIC(12,6) NOT NULL,
                    equity NUMERIC(12,6) NOT NULL,
                    total_pnl NUMERIC(12,6) NOT NULL,
                    total_trades INTEGER NOT NULL,
                    winning_trades INTEGER NOT NULL,
                    losing_trades INTEGER NOT NULL,
                    open_positions INTEGER NOT NULL,
                    notes TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_balance_history_timestamp ON balance_history(timestamp DESC);
            """)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._initialized = False

    async def save_model(self, model_data: Dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO models (
                    id, symbol, model_type, created_at, train_accuracy,
                    test_accuracy, sharpe_ratio, samples_trained, model_path,
                    is_deployed, notes
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (id) DO UPDATE SET
                    train_accuracy = EXCLUDED.train_accuracy,
                    test_accuracy = EXCLUDED.test_accuracy,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    is_deployed = EXCLUDED.is_deployed,
                    notes = EXCLUDED.notes
            """, 
            model_data['id'], model_data['symbol'], model_data['model_type'],
            model_data['created_at'], model_data['train_accuracy'],
            model_data['test_accuracy'], model_data.get('sharpe_ratio'),
            model_data['samples_trained'], model_data['model_path'],
            model_data.get('is_deployed', False), model_data.get('notes'))

    async def get_latest_model(self, symbol: str, deployed_only: bool = True) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            query = """
                SELECT * FROM models 
                WHERE symbol = $1
            """
            if deployed_only:
                query += " AND is_deployed = TRUE"
            query += " ORDER BY created_at DESC LIMIT 1"
            
            row = await conn.fetchrow(query, symbol)
            return dict(row) if row else None

    async def get_all_models(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            if symbol:
                rows = await conn.fetch(
                    "SELECT * FROM models WHERE symbol = $1 ORDER BY created_at DESC",
                    symbol
                )
            else:
                rows = await conn.fetch("SELECT * FROM models ORDER BY created_at DESC")
            return [dict(row) for row in rows]

    async def deploy_model(self, model_id: str, symbol: str) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE models SET is_deployed = FALSE WHERE symbol = $1",
                    symbol
                )
                await conn.execute(
                    "UPDATE models SET is_deployed = TRUE WHERE id = $1",
                    model_id
                )

    async def save_training_run(self, run_data: Dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO training_runs (
                    id, timestamp, symbol, model_version_id, train_start_date,
                    train_end_date, samples, train_accuracy, test_accuracy,
                    previous_accuracy, improvement, duration_seconds, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """,
            run_data['id'], run_data['timestamp'], run_data['symbol'],
            run_data.get('model_version_id'), run_data.get('train_start_date'),
            run_data.get('train_end_date'), run_data.get('samples'),
            run_data.get('train_accuracy'), run_data.get('test_accuracy'),
            run_data.get('previous_accuracy'), run_data.get('improvement'),
            run_data.get('duration_seconds'), run_data.get('status', 'completed'))

    async def get_training_history(self, symbol: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            if symbol:
                rows = await conn.fetch(
                    "SELECT * FROM training_runs WHERE symbol = $1 ORDER BY timestamp DESC LIMIT $2",
                    symbol, limit
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM training_runs ORDER BY timestamp DESC LIMIT $1",
                    limit
                )
            return [dict(row) for row in rows]

    async def save_prediction(self, prediction_data: Dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO predictions (
                    id, timestamp, symbol, model_version_id, predicted_signal,
                    confidence, actual_outcome, entry_price, exit_price, pnl
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            prediction_data['id'], prediction_data['timestamp'],
            prediction_data['symbol'], prediction_data.get('model_version_id'),
            prediction_data.get('predicted_signal'), prediction_data.get('confidence'),
            prediction_data.get('actual_outcome'), prediction_data.get('entry_price'),
            prediction_data.get('exit_price'), prediction_data.get('pnl'))

    async def update_prediction_outcome(self, prediction_id: str, actual_outcome: int,
                                       exit_price: float, pnl: float) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                UPDATE predictions
                SET actual_outcome = $2, exit_price = $3, pnl = $4
                WHERE id = $1
            """, prediction_id, actual_outcome, exit_price, pnl)

    async def get_predictions(self, symbol: Optional[str] = None,
                            model_id: Optional[str] = None,
                            limit: int = 100) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            query = "SELECT * FROM predictions WHERE 1=1"
            params = []
            param_count = 1
            
            if symbol:
                query += f" AND symbol = ${param_count}"
                params.append(symbol)
                param_count += 1
            
            if model_id:
                query += f" AND model_version_id = ${param_count}"
                params.append(model_id)
                param_count += 1
            
            query += f" ORDER BY timestamp DESC LIMIT ${param_count}"
            params.append(limit)
            
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def get_model_accuracy(self, model_id: str) -> Optional[float]:
        async with self._pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT 
                    CASE 
                        WHEN COUNT(*) = 0 THEN NULL
                        ELSE CAST(SUM(CASE WHEN predicted_signal = actual_outcome THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*)
                    END
                FROM predictions
                WHERE model_version_id = $1 AND actual_outcome IS NOT NULL
            """, model_id)
            return float(result) if result is not None else None

    async def save_balance_snapshot(self, snapshot_data: Dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO balance_history (
                    timestamp, balance, equity, total_pnl, total_trades,
                    winning_trades, losing_trades, open_positions, notes
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            snapshot_data['timestamp'], snapshot_data['balance'],
            snapshot_data['equity'], snapshot_data['total_pnl'],
            snapshot_data['total_trades'], snapshot_data['winning_trades'],
            snapshot_data['losing_trades'], snapshot_data['open_positions'],
            snapshot_data.get('notes'))

    async def get_balance_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM balance_history ORDER BY timestamp DESC LIMIT $1",
                limit
            )
            return [dict(row) for row in rows]

    async def get_latest_balance(self) -> Optional[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM balance_history ORDER BY timestamp DESC LIMIT 1"
            )
            return dict(row) if row else None

    async def health_check(self) -> Dict[str, Any]:
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
                return {
                    "status": "healthy",
                    "pool_size": self._pool.get_size(),
                    "pool_free": self._pool.get_idle_size(),
                    "connection": "connected"
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "connection": "failed"
            }
