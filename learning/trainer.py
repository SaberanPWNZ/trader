import time
import pickle
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from pathlib import Path
import pandas as pd
from loguru import logger

from config.settings import settings
from strategies.ai_strategy import AIStrategy
from learning.database import LearningDatabase
from backtesting.engine import BacktestEngine


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
        
        if 'error' in metrics:
            raise ValueError(f"Training failed: {metrics['error']}, samples={metrics.get('samples', 0)}")
        
        if strategy.model is None:
            raise ValueError("Training completed but no model was created")
        
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
            return False, f"Last training was {hours_since_training:.1f}h ago. Next training in {self.config.training_interval_hours - hours_since_training:.1f}h"

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

    def validate_model_with_backtest(
        self,
        strategy: AIStrategy,
        data: pd.DataFrame
    ) -> Tuple[bool, Dict[str, Any]]:
        if not self.config.backtest_before_deploy:
            return True, {"backtest_skipped": True}

        logger.info(f"Running backtest validation on {len(data)} samples")
        
        try:
            backtest_engine = BacktestEngine(
                strategy=strategy,
                initial_balance=settings.backtest.initial_balance,
                fee_rate=settings.backtest.trading_fee,
                slippage=settings.backtest.slippage
            )
            
            result = backtest_engine.run(data)
            metrics = result.metrics
            
            logger.info(f"Backtest metrics: Sharpe={metrics.get('sharpe_ratio', 0):.2f}, "
                       f"Drawdown={metrics.get('max_drawdown_percent', 0):.1f}%, "
                       f"WinRate={metrics.get('win_rate', 0):.1%}, "
                       f"ProfitFactor={metrics.get('profit_factor', 0):.2f}")
            
            passes_validation = (
                metrics.get('sharpe_ratio', 0) >= self.config.min_sharpe_ratio and
                metrics.get('max_drawdown_percent', 100) <= self.config.max_drawdown_percent and
                metrics.get('win_rate', 0) >= self.config.min_win_rate and
                metrics.get('profit_factor', 0) >= self.config.min_profit_factor
            )
            
            backtest_metrics = {
                "sharpe_ratio": metrics.get('sharpe_ratio', 0),
                "max_drawdown_percent": metrics.get('max_drawdown_percent', 0),
                "win_rate": metrics.get('win_rate', 0),
                "profit_factor": metrics.get('profit_factor', 0),
                "total_trades": metrics.get('total_trades', 0),
                "total_pnl": metrics.get('total_pnl', 0),
                "passes_validation": passes_validation
            }
            
            return passes_validation, backtest_metrics
            
        except Exception as e:
            logger.error(f"Backtest validation failed: {e}")
            return False, {"error": str(e)}

    async def run_training_cycle(
        self,
        symbol: str,
        data: pd.DataFrame,
        model_type: str = "xgboost",
        use_walk_forward: bool = False
    ) -> dict:
        should_train, reason = await self.should_retrain(symbol)
        if not should_train:
            return {"status": "skipped", "reason": reason}

        try:
            if use_walk_forward:
                return await self._train_with_walk_forward(symbol, data, model_type)
            
            model_id, metrics = await self.train_model(symbol, data, model_type)

            should_deploy, old_accuracy, improvement = await self.evaluate_improvement(
                symbol, metrics["test_accuracy"]
            )

            overfit_gap = metrics["train_accuracy"] - metrics["test_accuracy"]
            if overfit_gap > self.config.max_overfit_gap:
                logger.warning(f"Model rejected due to overfitting: gap={overfit_gap:.1%} > max={self.config.max_overfit_gap:.1%}")
                await self.db.save_training_run(
                    symbol=symbol,
                    model_version_id=model_id,
                    train_start_date="",
                    train_end_date="",
                    samples=metrics["samples"],
                    train_accuracy=metrics["train_accuracy"],
                    test_accuracy=metrics["test_accuracy"],
                    previous_accuracy=old_accuracy,
                    improvement=improvement,
                    duration_seconds=metrics["duration_seconds"],
                    status=f"rejected: overfitting {overfit_gap:.1%}"
                )
                return {
                    "status": "rejected",
                    "reason": f"Overfitting detected: gap={overfit_gap:.1%} > max={self.config.max_overfit_gap:.1%}",
                    "model_id": model_id,
                    "train_accuracy": metrics["train_accuracy"],
                    "test_accuracy": metrics["test_accuracy"],
                    "overfit_gap": overfit_gap
                }

            strategy = AIStrategy(model_type=model_type)
            strategy.load_model(metrics["model_path"])
            
            backtest_passed, backtest_metrics = self.validate_model_with_backtest(
                strategy, data
            )

            train_start = data.index.min().strftime("%Y-%m-%d") if hasattr(data.index, 'min') else "unknown"
            train_end = data.index.max().strftime("%Y-%m-%d") if hasattr(data.index, 'max') else "unknown"

            sharpe_ratio = backtest_metrics.get("sharpe_ratio") if isinstance(backtest_metrics, dict) else None
            
            await self.db.update_model_sharpe(model_id, sharpe_ratio)

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

            deploy_decision = should_deploy and backtest_passed
            if deploy_decision and self.config.auto_deploy_enabled:
                await self.db.deploy_model(model_id, symbol)
                logger.info(f"Auto-deployed model {model_id} for {symbol} (improvement: {improvement:.1%}, backtest: passed)")
            elif not backtest_passed:
                logger.warning(f"Model {model_id} not deployed - backtest validation failed")

            return {
                "status": "success",
                "model_id": model_id,
                "train_accuracy": metrics["train_accuracy"],
                "test_accuracy": metrics["test_accuracy"],
                "samples": metrics["samples"],
                "duration_seconds": metrics["duration_seconds"],
                "improvement": improvement,
                "previous_accuracy": old_accuracy,
                "deployed": deploy_decision and self.config.auto_deploy_enabled,
                "model_path": metrics["model_path"],
                "backtest_metrics": backtest_metrics,
                "backtest_passed": backtest_passed
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

    async def _train_with_walk_forward(
        self,
        symbol: str,
        data: pd.DataFrame,
        model_type: str
    ) -> dict:
        logger.info(f"Starting walk-forward validation for {symbol}")
        
        train_period = settings.backtest.walk_forward_periods
        test_period = settings.backtest.walk_forward_test_size
        
        strategy = AIStrategy(model_type=model_type)
        data_with_features = strategy.calculate_features(data)
        data_with_labels = strategy.create_labels(data_with_features)
        prepared_data = data_with_labels.dropna()
        
        if len(prepared_data) < train_period + test_period:
            raise ValueError(f"Insufficient data for walk-forward: {len(prepared_data)} < {train_period + test_period}")
        
        all_test_accuracies = []
        fold_results = []
        
        start = 0
        fold_num = 0
        
        while start + train_period + test_period <= len(prepared_data):
            fold_num += 1
            train_end = start + train_period
            test_end = train_end + test_period
            
            train_data = prepared_data.iloc[start:train_end]
            test_data = prepared_data.iloc[train_end:test_end]
            
            logger.info(f"Fold {fold_num}: training on {len(train_data)} samples, testing on {len(test_data)}")
            
            strategy_fold = AIStrategy(model_type=model_type)
            metrics = strategy_fold.train(train_data)
            
            backtest_engine = BacktestEngine(
                strategy=strategy_fold,
                initial_balance=settings.backtest.initial_balance,
                fee_rate=settings.backtest.trading_fee,
                slippage=settings.backtest.slippage
            )
            
            result = backtest_engine.run(test_data)
            
            all_test_accuracies.append(metrics['test_accuracy'])
            fold_results.append({
                'fold': fold_num,
                'test_accuracy': metrics['test_accuracy'],
                'sharpe': result.metrics.get('sharpe_ratio', 0),
                'win_rate': result.metrics.get('win_rate', 0),
                'total_pnl': result.metrics.get('total_pnl', 0)
            })
            
            start += test_period
        
        avg_test_accuracy = sum(all_test_accuracies) / len(all_test_accuracies)
        avg_sharpe = sum(f['sharpe'] for f in fold_results) / len(fold_results)
        avg_win_rate = sum(f['win_rate'] for f in fold_results) / len(fold_results)
        
        logger.info(f"Walk-forward complete: {fold_num} folds, avg accuracy={avg_test_accuracy:.3f}, "
                   f"avg sharpe={avg_sharpe:.2f}, avg win_rate={avg_win_rate:.1%}")
        
        final_strategy = AIStrategy(model_type=model_type)
        final_metrics = final_strategy.train(prepared_data)
        
        if 'error' in final_metrics or final_strategy.model is None:
            raise ValueError(f"Final training failed after walk-forward validation")
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        model_filename = f"{symbol.replace('/', '_')}_{model_type}_wf_{timestamp}.pkl"
        model_path = str(self.models_dir / model_filename)
        final_strategy.save_model(model_path)
        
        model_id = await self.db.save_model(
            symbol=symbol,
            model_type=f"{model_type}_walk_forward",
            train_accuracy=final_metrics['train_accuracy'],
            test_accuracy=avg_test_accuracy,
            samples_trained=len(prepared_data),
            model_path=model_path,
            sharpe_ratio=avg_sharpe,
            notes=f"Walk-forward: {fold_num} folds"
        )
        
        await self.db.save_training_run(
            symbol=symbol,
            model_version_id=model_id,
            train_start_date=prepared_data.index.min().strftime("%Y-%m-%d"),
            train_end_date=prepared_data.index.max().strftime("%Y-%m-%d"),
            samples=len(prepared_data),
            train_accuracy=final_metrics['train_accuracy'],
            test_accuracy=avg_test_accuracy,
            previous_accuracy=0,
            improvement=0,
            duration_seconds=0,
            status="success_walk_forward"
        )
        
        return {
            "status": "success",
            "model_id": model_id,
            "train_accuracy": final_metrics['train_accuracy'],
            "test_accuracy": avg_test_accuracy,
            "samples": len(prepared_data),
            "duration_seconds": 0,
            "improvement": 0,
            "previous_accuracy": 0,
            "deployed": False,
            "model_path": model_path,
            "walk_forward_folds": fold_num,
            "backtest_metrics": {
                "sharpe_ratio": avg_sharpe,
                "win_rate": avg_win_rate,
                "fold_results": fold_results
            },
            "backtest_passed": True
        }
