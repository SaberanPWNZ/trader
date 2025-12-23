import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Callable
from loguru import logger
import pandas as pd
import yfinance as yf

from config.settings import settings
from learning.database import LearningDatabase
from learning.trainer import AutoTrainer
from learning.model_manager import ModelManager
from monitoring.alerts import telegram


class LearningScheduler:
    def __init__(
        self,
        db: Optional[LearningDatabase] = None,
        symbols: Optional[List[str]] = None
    ):
        self.db = db or LearningDatabase()
        self.trainer = AutoTrainer(self.db)
        self.model_manager = ModelManager(self.db)
        self.config = settings.self_learning
        self.symbols = symbols or settings.trading.symbols
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callbacks: List[Callable] = []

    def register_callback(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        if self._running:
            logger.warning("Scheduler already running")
            return

        await self.db.initialize()
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        
        now = datetime.utcnow()
        next_run = self._get_next_run_time(now)
        wait_seconds = (next_run - now).total_seconds()
        wait_hours = wait_seconds / 3600
        
        logger.info("Learning scheduler started")
        
        startup_msg = (
            f"🤖 Self-learning scheduler started\n"
            f"⏱️ Interval: every {self.config.training_interval_hours} hour(s)\n"
            f"📅 Next training: {next_run.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"⏳ In {wait_hours:.1f} hours\n"
            f"📍 Symbols: {', '.join(self.symbols)}"
        )
        await telegram.system_status("online", startup_msg)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Learning scheduler stopped")
        await telegram.system_status("offline", "Self-learning scheduler stopped")

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                now = datetime.utcnow()
                next_run = self._get_next_run_time(now)
                wait_seconds = (next_run - now).total_seconds()

                if wait_seconds > 0:
                    logger.info(f"Next training scheduled at {next_run.strftime('%Y-%m-%d %H:%M:%S')} UTC")
                    await asyncio.sleep(min(wait_seconds, 3600))
                    if wait_seconds > 3600:
                        continue

                await self.run_training_cycle()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(60)

    def _get_next_run_time(self, now: datetime) -> datetime:
        interval_hours = self.config.training_interval_hours
        
        if interval_hours >= 24:
            target_hour = 0
            next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            if now.hour >= target_hour:
                next_run += timedelta(days=1)
        else:
            minutes_to_next = (interval_hours * 60) - (now.minute + now.hour * 60) % (interval_hours * 60)
            next_run = now + timedelta(minutes=minutes_to_next)
            next_run = next_run.replace(second=0, microsecond=0)
        
        return next_run

    async def run_training_cycle(self) -> dict:
        results = {}
        logger.info(f"Starting training cycle for {len(self.symbols)} symbols")

        for symbol in self.symbols:
            try:
                await telegram.training_started(symbol)
                
                data = await self._fetch_training_data(symbol)
                if data is None or len(data) < self.config.min_samples_for_training:
                    logger.warning(f"Insufficient data for {symbol}")
                    results[symbol] = {"status": "skipped", "reason": "insufficient data"}
                    continue

                result = await self.trainer.run_training_cycle(
                    symbol=symbol,
                    data=data,
                    model_type=settings.strategy.model_type
                )
                results[symbol] = result

                if result["status"] == "success":
                    await telegram.training_complete(
                        symbol=symbol,
                        model_type=settings.strategy.model_type,
                        train_accuracy=result["train_accuracy"],
                        test_accuracy=result["test_accuracy"],
                        samples=result["samples"],
                        duration_seconds=result["duration_seconds"],
                        improvement=result.get("improvement", 0),
                        deployed=result.get("deployed", False)
                    )
                    await self.model_manager.cleanup_old_models(symbol)
                else:
                    await telegram.training_failed(
                        symbol=symbol,
                        error=result.get("error") or result.get("reason", "Unknown error")
                    )

                for callback in self._callbacks:
                    try:
                        await callback(symbol, result)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")

            except Exception as e:
                logger.error(f"Training failed for {symbol}: {e}")
                results[symbol] = {"status": "failed", "error": str(e)}
                await telegram.training_failed(symbol=symbol, error=str(e))

        logger.info(f"Training cycle complete: {results}")
        return results

    async def _fetch_training_data(self, symbol: str) -> Optional[pd.DataFrame]:
        try:
            yf_symbol = settings.get_symbol_for_pybroker(symbol)
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=self.config.performance_lookback_days)

            ticker = yf.Ticker(yf_symbol)
            data = ticker.history(
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval="1h"
            )

            if data.empty:
                return None

            data.columns = [c.lower() for c in data.columns]
            data = data.rename(columns={"stock splits": "stock_splits"})
            return data

        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return None

    async def force_train(self, symbol: str) -> dict:
        await self.db.initialize()
        await telegram.training_started(symbol)

        data = await self._fetch_training_data(symbol)
        if data is None:
            error = "Failed to fetch training data"
            await telegram.training_failed(symbol, error)
            return {"status": "failed", "error": error}

        model_id, metrics = await self.trainer.train_model(
            symbol=symbol,
            data=data,
            model_type=settings.strategy.model_type
        )

        should_deploy, old_accuracy, improvement = await self.trainer.evaluate_improvement(
            symbol, metrics["test_accuracy"]
        )

        await self.db.save_training_run(
            symbol=symbol,
            model_version_id=model_id,
            train_start_date=data.index.min().strftime("%Y-%m-%d"),
            train_end_date=data.index.max().strftime("%Y-%m-%d"),
            samples=metrics["samples"],
            train_accuracy=metrics["train_accuracy"],
            test_accuracy=metrics["test_accuracy"],
            previous_accuracy=old_accuracy,
            improvement=improvement,
            duration_seconds=metrics["duration_seconds"],
            status="success"
        )

        await telegram.training_complete(
            symbol=symbol,
            model_type=settings.strategy.model_type,
            train_accuracy=metrics["train_accuracy"],
            test_accuracy=metrics["test_accuracy"],
            samples=metrics["samples"],
            duration_seconds=metrics["duration_seconds"],
            improvement=improvement,
            deployed=False
        )

        return {
            "status": "success",
            "model_id": model_id,
            **metrics,
            "improvement": improvement,
            "should_deploy": should_deploy
        }
