"""
AI Scoring Engine
─────────────────
Primary mode  : XGBoost model (ENABLE_ML_MODEL=true + model/xgb_scorer.json present).
Fallback mode : weighted linear scoring (always available).

XGBoost feature vector (14 features — must match training schema in scripts/train_xgb.py):
    rsi_14, macd_bullish, bb_pct, stoch_rsi, ma_cross_bullish,
    volume_anomaly, volatility_20d,
    technical_score, fundamental_score, sentiment_score,
    macro_score, volatility_score, catalyst_score,
    vix (from macro)

Weighted fallback:
    score = base(6 weights, sum=1.0) + weight_alt * (alt_score - 0.5)
"""
import os
from typing import Optional

from app.config import get_settings
from app.db import COLL_FEATURES, get_db
from app.utils.helpers import clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Path where a trained XGBoost model is expected (optional)
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "model", "xgb_scorer.json")
_xgb_model = None  # loaded lazily


async def score_ticker(ticker: str) -> dict:
    """
    Read feature document for *ticker* and produce a composite score.
    Returns the (updated) feature document including composite_score.
    """
    ticker = ticker.upper()
    db = await get_db()

    feat = await db[COLL_FEATURES].find_one({"ticker": ticker})
    if feat is None:
        raise ValueError(f"No features found for {ticker}. Run feature engineering first.")

    settings = get_settings()

    if settings.enable_ml_model:
        composite = _ml_score(feat)
        method = "xgboost"
    else:
        composite = _weighted_score(feat, settings)
        method = "weighted"

    composite = clamp(composite)

    await db[COLL_FEATURES].update_one(
        {"ticker": ticker},
        {"$set": {"composite_score": round(composite, 4), "scoring_method": method}},
    )

    logger.info("scored", ticker=ticker, composite=composite, method=method)
    feat["composite_score"] = round(composite, 4)
    feat["scoring_method"] = method
    return feat


def _weighted_score(feat: dict, settings) -> float:
    """
    6-weight base score (weights sum to 1.0) plus an alternative-data modifier.
    alt_score=0.5 → no change; >0.5 → boost; <0.5 → drag.
    Max effect: ±weight_alternative_data/2 on the composite.
    """
    base = (
        settings.weight_technical   * feat.get("technical_score",   0.5)
        + settings.weight_fundamental * feat.get("fundamental_score", 0.5)
        + settings.weight_sentiment   * feat.get("sentiment_score",   0.5)
        + settings.weight_macro       * feat.get("macro_score",       0.5)
        + settings.weight_volatility  * feat.get("volatility_score",  0.5)
        + settings.weight_catalyst    * feat.get("catalyst_score",    0.5)
    )
    alt_modifier = settings.weight_alternative_data * (
        feat.get("alternative_data_score", 0.5) - 0.5
    )
    return base + alt_modifier


def _ml_score(feat: dict) -> float:
    """
    XGBoost inference path.
    Feature vector must match training schema in scripts/train_xgb.py.

    NOTE: fundamental_score and sentiment_score are frozen at 0.5 to match
    training data (train_xgb.py hardcodes both; historical values unavailable).
    Re-train xgb_scorer.json with real fundamental/sentiment data before unfreezing.

    VIX is read directly from feat["vix"] (stored by feature_engineering.py from
    raw macro data). Previously this defaulted to 20.0 due to a missing propagation.
    """
    global _xgb_model

    if _xgb_model is None:
        if not os.path.exists(_MODEL_PATH):
            logger.warning("xgb_model_not_found", path=_MODEL_PATH, fallback="weighted")
            return _weighted_score(feat, get_settings())
        try:
            import xgboost as xgb
            _xgb_model = xgb.XGBRegressor()
            _xgb_model.load_model(_MODEL_PATH)
            logger.info("xgb_model_loaded", path=_MODEL_PATH)
        except Exception as exc:
            logger.error("xgb_model_load_failed", error=str(exc))
            return _weighted_score(feat, get_settings())

    import numpy as np

    # 14-feature vector — must match training schema in scripts/train_xgb.py
    feature_vector = np.array(
        [[
            feat.get("rsi_14",           50.0) or 50.0,
            1.0 if feat.get("macd_bullish") else 0.0,
            feat.get("bb_pct",            0.5) or 0.5,
            feat.get("stoch_rsi",         0.5) or 0.5,
            1.0 if feat.get("ma_cross_bullish") else 0.0,
            feat.get("volume_anomaly",    1.0) or 1.0,
            feat.get("volatility_20d",    0.3) or 0.3,
            feat.get("technical_score",   0.5),
            0.5,  # fundamental_score frozen — matches training; retrain to unlock
            0.5,  # sentiment_score frozen — matches training; retrain to unlock
            feat.get("macro_score",       0.5),
            feat.get("volatility_score",  0.5),
            feat.get("catalyst_score",    0.5),
            float(feat.get("vix") or 20.0),  # read from feat directly (Fix 1)
        ]]
    )
    prediction = float(_xgb_model.predict(feature_vector)[0])
    return clamp(prediction)
