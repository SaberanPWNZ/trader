import pickle
from pathlib import Path
from typing import Optional, Dict, Tuple
from datetime import datetime

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import settings
from strategies.indicators import TechnicalIndicators


class GridAdvice:
    __slots__ = (
        'grid_range_pct', 'trend_bias', 'confidence',
        'volatility_regime', 'recommended_grids', 'reason',
    )

    def __init__(
        self,
        grid_range_pct: float,
        trend_bias: float,
        confidence: float,
        volatility_regime: str,
        recommended_grids: int,
        reason: str,
    ):
        self.grid_range_pct = grid_range_pct
        self.trend_bias = trend_bias
        self.confidence = confidence
        self.volatility_regime = volatility_regime
        self.recommended_grids = recommended_grids
        self.reason = reason

    def __repr__(self) -> str:
        return (
            f"GridAdvice(range={self.grid_range_pct:.1%}, bias={self.trend_bias:+.3f}, "
            f"vol={self.volatility_regime}, conf={self.confidence:.2f}, grids={self.recommended_grids})"
        )


class MLGridAdvisor:
    def __init__(self):
        self._models: Dict[str, object] = {}
        self._last_advice: Dict[str, GridAdvice] = {}
        self._last_update: Dict[str, datetime] = {}
        self._min_update_minutes = 15
        self._default_range = settings.grid.grid_range_pct

    def _load_model(self, symbol: str) -> bool:
        if symbol in self._models:
            return True

        models_dir = settings.models_dir
        safe_symbol = symbol.replace('/', '_')
        model_files = sorted(models_dir.glob(f"{safe_symbol}_xgboost_*.pkl"), reverse=True)

        if not model_files:
            logger.debug(f"No ML model found for {symbol}")
            return False

        try:
            with open(model_files[0], 'rb') as f:
                self._models[symbol] = pickle.load(f)
            logger.info(f"🤖 Loaded ML model for {symbol}: {model_files[0].name}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load model for {symbol}: {e}")
            return False

    def _calculate_volatility_features(self, df: pd.DataFrame) -> Dict[str, float]:
        close = df['close']
        high = df['high']
        low = df['low']

        returns = close.pct_change().dropna()
        recent_vol = returns.tail(24).std()
        medium_vol = returns.tail(72).std()
        long_vol = returns.std()

        atr = TechnicalIndicators.atr(high, low, close, 14)
        atr_pct = (atr / close).iloc[-1] if len(atr) > 0 else 0.02

        bb_upper, bb_middle, bb_lower = TechnicalIndicators.bollinger_bands(close, 20, 2.0)
        bb_width = ((bb_upper - bb_lower) / bb_middle).iloc[-1] if len(bb_middle) > 0 else 0.04

        vol_ratio = recent_vol / medium_vol if medium_vol > 0 else 1.0
        vol_expansion = recent_vol > long_vol * 1.5

        price_range_24h = (high.tail(24).max() - low.tail(24).min()) / close.iloc[-1]

        return {
            'recent_vol': recent_vol,
            'medium_vol': medium_vol,
            'long_vol': long_vol,
            'atr_pct': atr_pct,
            'bb_width': bb_width,
            'vol_ratio': vol_ratio,
            'vol_expansion': vol_expansion,
            'price_range_24h': price_range_24h,
        }

    def _calculate_trend_features(self, df: pd.DataFrame) -> Dict[str, float]:
        close = df['close']

        ema_20 = TechnicalIndicators.ema(close, 20)
        ema_50 = TechnicalIndicators.ema(close, 50)

        rsi = TechnicalIndicators.rsi(close, 14)
        current_rsi = rsi.iloc[-1] if len(rsi) > 0 else 50.0

        macd_line, signal_line, histogram = TechnicalIndicators.macd(close)
        macd_hist = histogram.iloc[-1] if len(histogram) > 0 else 0.0
        macd_hist_prev = histogram.iloc[-2] if len(histogram) > 1 else 0.0

        ema_ratio = ema_20.iloc[-1] / ema_50.iloc[-1] if ema_50.iloc[-1] > 0 else 1.0
        price_vs_ema20 = close.iloc[-1] / ema_20.iloc[-1] if ema_20.iloc[-1] > 0 else 1.0

        macd_momentum = 1 if macd_hist > macd_hist_prev else -1
        ema_trend = 1 if ema_ratio > 1.002 else (-1 if ema_ratio < 0.998 else 0)
        rsi_zone = 1 if current_rsi > 60 else (-1 if current_rsi < 40 else 0)

        trend_score = (ema_trend * 0.4 + rsi_zone * 0.3 + macd_momentum * 0.3)

        return {
            'ema_ratio': ema_ratio,
            'price_vs_ema20': price_vs_ema20,
            'rsi': current_rsi,
            'macd_hist': macd_hist,
            'macd_momentum': macd_momentum,
            'trend_score': trend_score,
        }

    def _get_ml_confidence(self, symbol: str, df: pd.DataFrame) -> Tuple[float, float]:
        if not self._load_model(symbol):
            return 0.5, 0.0

        try:
            df_feat = TechnicalIndicators.add_all_indicators(df.copy())
            feature_cols = [
                'ema_ratio_fast_medium', 'ema_ratio_fast_slow', 'ema_ratio_medium_slow',
                'rsi', 'macd_histogram', 'log_return', 'volume_delta', 'atr_normalized',
            ]
            features = df_feat[feature_cols].dropna()
            if features.empty:
                return 0.5, 0.0

            X = features.iloc[[-1]].values
            model = self._models[symbol]

            prediction = model.predict(X)[0]
            confidence = 0.5
            if hasattr(model, 'predict_proba'):
                probas = model.predict_proba(X)[0]
                confidence = float(max(probas))

            direction = 1.0 if prediction == 1 else -1.0
            return confidence, direction
        except Exception as e:
            logger.warning(f"ML prediction failed for {symbol}: {e}")
            return 0.5, 0.0

    def get_advice(self, symbol: str, ohlcv_df: pd.DataFrame) -> GridAdvice:
        now = datetime.utcnow()
        last = self._last_update.get(symbol)
        if last and (now - last).total_seconds() < self._min_update_minutes * 60:
            cached = self._last_advice.get(symbol)
            if cached:
                return cached

        if ohlcv_df is None or len(ohlcv_df) < 50:
            return self._default_advice("insufficient data")

        try:
            vol = self._calculate_volatility_features(ohlcv_df)
            trend = self._calculate_trend_features(ohlcv_df)
            ml_confidence, ml_direction = self._get_ml_confidence(symbol, ohlcv_df)

            advice = self._compute_grid_params(vol, trend, ml_confidence, ml_direction)

            self._last_advice[symbol] = advice
            self._last_update[symbol] = now

            logger.info(
                f"🤖 ML Grid Advice for {symbol}: {advice.reason} | "
                f"range={advice.grid_range_pct:.1%}, bias={advice.trend_bias:+.3f}, "
                f"vol={advice.volatility_regime}, conf={advice.confidence:.2f}"
            )
            return advice

        except Exception as e:
            logger.warning(f"ML advisor error for {symbol}: {e}")
            return self._default_advice(f"error: {e}")

    def _compute_grid_params(
        self,
        vol: Dict[str, float],
        trend: Dict[str, float],
        ml_confidence: float,
        ml_direction: float,
    ) -> GridAdvice:
        base_range = self._default_range
        atr_pct = vol['atr_pct']
        bb_width = vol['bb_width']
        vol_ratio = vol['vol_ratio']
        range_24h = vol['price_range_24h']

        vol_range = max(atr_pct * 3.0, bb_width * 0.6, range_24h * 0.5)
        vol_range = np.clip(vol_range, 0.02, 0.10)

        if vol_ratio > 2.0:
            volatility_regime = "extreme"
            vol_range *= 1.3
        elif vol_ratio > 1.3:
            volatility_regime = "high"
            vol_range *= 1.1
        elif vol_ratio < 0.6:
            volatility_regime = "low"
            vol_range *= 0.85
        else:
            volatility_regime = "normal"

        grid_range_pct = vol_range * 0.6 + base_range * 0.4
        grid_range_pct = np.clip(grid_range_pct, 0.025, 0.10)

        trend_score = trend['trend_score']
        trend_bias = 0.0

        if ml_confidence > 0.6:
            ml_weight = min((ml_confidence - 0.5) * 2.0, 0.5)
            trend_bias = ml_direction * ml_weight * grid_range_pct * 0.3
            
            if ml_direction < 0 and ml_confidence > 0.65:
                trend_bias *= 1.5
                grid_range_pct *= 1.2
                
        elif abs(trend_score) > 0.3:
            trend_bias = trend_score * grid_range_pct * 0.15
            
            if trend_score < -0.3:
                trend_bias *= 1.3

        if volatility_regime == "extreme":
            recommended_grids = 3
        elif volatility_regime == "high":
            recommended_grids = 3
        elif volatility_regime == "low":
            recommended_grids = settings.grid.min_grids
        else:
            recommended_grids = max(settings.grid.min_grids, settings.grid.max_grids - 2)

        confidence = ml_confidence

        parts = [f"vol={volatility_regime}({vol_ratio:.1f}x)"]
        if abs(trend_bias) > 0.001:
            direction = "UP" if trend_bias > 0 else "DOWN"
            parts.append(f"trend={direction}")
        if ml_confidence > 0.6:
            parts.append(f"ML={ml_confidence:.0%}")
        parts.append(f"ATR={atr_pct:.1%}")
        reason = ", ".join(parts)

        return GridAdvice(
            grid_range_pct=float(grid_range_pct),
            trend_bias=float(trend_bias),
            confidence=float(confidence),
            volatility_regime=volatility_regime,
            recommended_grids=int(recommended_grids),
            reason=reason,
        )

    def _default_advice(self, reason: str) -> GridAdvice:
        return GridAdvice(
            grid_range_pct=self._default_range,
            trend_bias=0.0,
            confidence=0.0,
            volatility_regime="unknown",
            recommended_grids=settings.grid.min_grids,
            reason=f"default: {reason}",
        )
