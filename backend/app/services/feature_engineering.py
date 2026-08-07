"""
Feature Engineering Service
────────────────────────────
Reads raw price data from MongoDB, computes technical indicators
(RSI-14, MA-20, MA-50, 20-day annualised volatility), and derives
normalised sub-scores that feed the scoring engine.
"""
import math
from typing import Optional

import numpy as np
import pandas as pd

from app.db import COLL_FEATURES, COLL_RAW, get_db
from app.utils.helpers import clamp, utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def compute_features(ticker: str) -> dict:
    """
    Load the latest raw document for *ticker*, compute features,
    and upsert into `stocks_features`.  Returns the feature dict.
    """
    ticker = ticker.upper()
    db = await get_db()

    raw_doc = await db[COLL_RAW].find_one({"ticker": ticker})
    if not raw_doc:
        raise ValueError(f"No raw data found for {ticker}. Run ingestion first.")

    bars = raw_doc.get("bars", [])
    if len(bars) < 20:
        raise ValueError(f"Insufficient price history for {ticker} (need ≥20 bars, got {len(bars)})")

    # Build a price Series (index = datetime, values = close)
    closes = pd.Series(
        [b["close"] for b in bars],
        index=pd.to_datetime([b["date"] for b in bars]),
        dtype=float,
    ).sort_index()

    # ── Technical indicators ──────────────────────────────────────────────────
    rsi = _calc_rsi(closes, period=14)
    ma_20 = closes.rolling(20).mean().iloc[-1]
    ma_50 = closes.rolling(50).mean().iloc[-1] if len(closes) >= 50 else None
    volatility = _calc_annualised_volatility(closes, window=20)
    current_price = float(closes.iloc[-1])

    # ── Sub-scores (all normalised 0–1) ──────────────────────────────────────
    technical_score = _technical_score(rsi, current_price, float(ma_20), ma_50)
    volatility_score = _volatility_score(volatility)

    # Sentiment from mock field stored during ingestion
    sentiment_raw = raw_doc.get("sentiment_raw", {})
    sentiment_score = clamp(float(sentiment_raw.get("score", 0.5)))

    # ── Composite (weighted) ──────────────────────────────────────────────────
    from app.config import get_settings
    cfg = get_settings()
    composite = (
        cfg.weight_technical * technical_score
        + cfg.weight_sentiment * sentiment_score
        + cfg.weight_volatility * volatility_score
    )
    composite = clamp(composite)

    feature_doc = {
        "ticker": ticker,
        "computed_at": utcnow(),
        "current_price": current_price,
        # Indicators
        "rsi_14": round(float(rsi), 4) if not math.isnan(rsi) else None,
        "ma_20": round(float(ma_20), 4),
        "ma_50": round(float(ma_50), 4) if ma_50 is not None else None,
        "ma_cross_bullish": (float(ma_20) > float(ma_50)) if ma_50 is not None else None,
        "volatility_20d": round(float(volatility), 6),
        # Sub-scores
        "technical_score": round(technical_score, 4),
        "sentiment_score": round(sentiment_score, 4),
        "volatility_score": round(volatility_score, 4),
        # Composite
        "composite_score": round(composite, 4),
    }

    await db[COLL_FEATURES].replace_one(
        {"ticker": ticker},
        feature_doc,
        upsert=True,
    )

    logger.info(
        "features_computed",
        ticker=ticker,
        rsi=feature_doc["rsi_14"],
        composite=composite,
    )
    return feature_doc


async def compute_features_all(tickers: list[str]) -> dict[str, str]:
    """Compute features for all tickers; returns ticker → 'ok' | error."""
    results: dict[str, str] = {}
    for ticker in tickers:
        try:
            await compute_features(ticker)
            results[ticker] = "ok"
        except Exception as exc:
            logger.warning("feature_compute_failed", ticker=ticker, error=str(exc))
            results[ticker] = str(exc)
    return results


# ── Internal calculations ─────────────────────────────────────────────────────

def _calc_rsi(closes: pd.Series, period: int = 14) -> float:
    """Wilder's RSI for the most-recent bar."""
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def _calc_annualised_volatility(closes: pd.Series, window: int = 20) -> float:
    """Standard deviation of log-returns × √252."""
    log_returns = np.log(closes / closes.shift(1)).dropna()
    if len(log_returns) < window:
        return float(log_returns.std() * math.sqrt(252))
    return float(log_returns.iloc[-window:].std() * math.sqrt(252))


def _technical_score(
    rsi: float,
    price: float,
    ma_20: float,
    ma_50: Optional[float],
) -> float:
    """
    Combine RSI and MA positions into a 0–1 technical score.

    RSI component (50 % weight):
      - RSI < 30 → oversold → bullish → score 1.0
      - RSI > 70 → overbought → bearish → score 0.0
      - Linear interpolation between 30–70

    MA component (50 % weight):
      - price > ma_20 > ma_50 → strong uptrend → 1.0
      - price < ma_20 < ma_50 → downtrend → 0.0
      - otherwise 0.5
    """
    # RSI sub-score
    rsi = clamp(rsi, 0, 100)
    if rsi <= 30:
        rsi_score = 1.0
    elif rsi >= 70:
        rsi_score = 0.0
    else:
        # Invert: lower RSI = more oversold = higher score
        rsi_score = 1.0 - (rsi - 30) / 40.0

    # MA sub-score
    if ma_50 is not None:
        if price > ma_20 and ma_20 > ma_50:
            ma_score = 1.0
        elif price < ma_20 and ma_20 < ma_50:
            ma_score = 0.0
        else:
            ma_score = 0.5
    else:
        # Only MA-20 available
        ma_score = 1.0 if price > ma_20 else 0.0

    return clamp(0.5 * rsi_score + 0.5 * ma_score)


def _volatility_score(volatility: float) -> float:
    """
    Convert annualised volatility to a 0–1 score (lower vol → higher score).
    Thresholds:
      vol ≤ 0.15  → 1.0  (very stable)
      vol ≥ 0.80  → 0.0  (extremely volatile)
    """
    if volatility <= 0.15:
        return 1.0
    if volatility >= 0.80:
        return 0.0
    return clamp(1.0 - (volatility - 0.15) / (0.80 - 0.15))
