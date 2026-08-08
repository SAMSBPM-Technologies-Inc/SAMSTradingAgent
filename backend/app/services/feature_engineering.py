"""
Feature Engineering Service
────────────────────────────
Reads raw price/fundamental/macro data from MongoDB and computes:

  Technical indicators  : RSI-14, MACD, Bollinger Bands, Stochastic RSI,
                          ATR, MA-20/50, volume anomaly
  Sub-scores (all 0–1)  : technical, fundamental, sentiment, macro, volatility
  Composite             : delegated to scoring.py (not computed here)

The `ta` library handles indicator math; numpy/pandas handle series ops.
"""
import math
from typing import Optional

import numpy as np
import pandas as pd
import ta

from app.db import COLL_FEATURES, COLL_RAW, get_db
from app.services.catalyst import compute_catalyst_score
from app.utils.helpers import clamp, utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def compute_features(ticker: str) -> dict:
    """
    Load the latest raw document for *ticker*, compute all features,
    and upsert into `stocks_features`. Returns the feature dict.
    """
    ticker = ticker.upper()
    db = await get_db()

    raw_doc = await db[COLL_RAW].find_one({"ticker": ticker})
    if not raw_doc:
        raise ValueError(f"No raw data found for {ticker}. Run ingestion first.")

    bars = raw_doc.get("bars", [])
    if len(bars) < 20:
        raise ValueError(
            f"Insufficient price history for {ticker} (need ≥20 bars, got {len(bars)})"
        )

    # ── Build OHLCV series ────────────────────────────────────────────────────
    index = pd.to_datetime([b["date"] for b in bars])
    closes  = pd.Series([b["close"]  for b in bars], index=index, dtype=float).sort_index()
    highs   = pd.Series([b["high"]   for b in bars], index=index, dtype=float).sort_index()
    lows    = pd.Series([b["low"]    for b in bars], index=index, dtype=float).sort_index()
    volumes = pd.Series([b["volume"] for b in bars], index=index, dtype=float).sort_index()

    current_price = float(closes.iloc[-1])

    # ── Technical indicators ──────────────────────────────────────────────────
    tech = _compute_technical_indicators(closes, highs, lows, volumes)

    # ── Sub-scores ────────────────────────────────────────────────────────────
    technical_score  = _technical_score(tech, current_price)
    volatility_score = _volatility_score(tech["volatility_20d"])

    sentiment_raw   = raw_doc.get("sentiment_raw", {})
    sentiment_score = clamp(float(sentiment_raw.get("score", 0.5)))

    fundamentals    = raw_doc.get("fundamentals", {})
    fundamental_score = _fundamental_score(fundamentals)

    macro           = raw_doc.get("macro", {})
    macro_score     = _macro_score(macro)

    # Store raw macro values needed by scoring.py XGBoost feature vector
    macro_vix          = macro.get("vix")
    macro_yield_spread = macro.get("yield_curve_spread")
    macro_cpi_yoy      = macro.get("cpi_yoy_pct")

    # catalyst_score needs both raw_doc and the partially-built feat dict
    _partial_feat = {"volume_anomaly": tech["volume_anomaly"]}
    catalyst_score = compute_catalyst_score(raw_doc, _partial_feat)

    feature_doc = {
        "ticker": ticker,
        "computed_at": utcnow(),
        "current_price": current_price,
        # ── Technical indicators ──────────────────────────────────────────────
        "rsi_14":           tech["rsi_14"],
        "macd":             tech["macd"],
        "macd_signal":      tech["macd_signal"],
        "macd_bullish":     tech["macd_bullish"],
        "bb_upper":         tech["bb_upper"],
        "bb_lower":         tech["bb_lower"],
        "bb_pct":           tech["bb_pct"],          # 0=at lower band, 1=at upper band
        "stoch_rsi":        tech["stoch_rsi"],        # 0–1
        "atr_14":           tech["atr_14"],
        "volume_anomaly":   tech["volume_anomaly"],   # ratio vs 20-day avg
        "ma_20":            tech["ma_20"],
        "ma_50":            tech["ma_50"],
        "ma_cross_bullish": tech["ma_cross_bullish"],
        "volatility_20d":   tech["volatility_20d"],
        # ── Raw macro fields (for XGBoost feature vector in scoring.py) ──────
        "vix":               macro_vix,
        "yield_curve_spread": macro_yield_spread,
        "cpi_yoy_pct":       macro_cpi_yoy,
        # ── Sub-scores (all 0–1) ─────────────────────────────────────────────
        "technical_score":    round(technical_score,   4),
        "fundamental_score":  round(fundamental_score, 4),
        "sentiment_score":    round(sentiment_score,   4),
        "macro_score":        round(macro_score,       4),
        "volatility_score":   round(volatility_score,  4),
        "catalyst_score":     round(catalyst_score,    4),
        # composite_score is set by scoring.py
    }

    await db[COLL_FEATURES].replace_one({"ticker": ticker}, feature_doc, upsert=True)

    logger.info(
        "features_computed",
        ticker=ticker,
        rsi=tech["rsi_14"],
        macd_bullish=tech["macd_bullish"],
        bb_pct=tech["bb_pct"],
        technical=round(technical_score, 4),
        fundamental=round(fundamental_score, 4),
        sentiment=round(sentiment_score, 4),
        macro=round(macro_score, 4),
        volatility=round(volatility_score, 4),
        catalyst=round(catalyst_score, 4),
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


# ── Technical indicator computation ───────────────────────────────────────────

def _compute_technical_indicators(
    closes: pd.Series,
    highs: pd.Series,
    lows: pd.Series,
    volumes: pd.Series,
) -> dict:
    """Compute all technical indicators. Returns a flat dict of floats/bools/None."""

    def last(series: pd.Series) -> Optional[float]:
        s = series.dropna()
        return round(float(s.iloc[-1]), 6) if not s.empty else None

    # RSI-14
    rsi_14 = last(ta.momentum.RSIIndicator(close=closes, window=14).rsi())

    # MACD (12, 26, 9)
    macd_ind = ta.trend.MACD(close=closes, window_slow=26, window_fast=12, window_sign=9)
    macd_val    = last(macd_ind.macd())
    macd_sig    = last(macd_ind.macd_signal())
    macd_bullish = (macd_val > macd_sig) if (macd_val is not None and macd_sig is not None) else None

    # Bollinger Bands (20, 2)
    bb = ta.volatility.BollingerBands(close=closes, window=20, window_dev=2)
    bb_upper = last(bb.bollinger_hband())
    bb_lower = last(bb.bollinger_lband())
    bb_pct   = last(bb.bollinger_pband())   # 0 = at lower, 1 = at upper

    # Stochastic RSI (14, 3, 3)
    stoch_rsi_ind = ta.momentum.StochRSIIndicator(close=closes, window=14, smooth1=3, smooth2=3)
    stoch_rsi = last(stoch_rsi_ind.stochrsi())

    # ATR-14
    atr_14 = last(ta.volatility.AverageTrueRange(high=highs, low=lows, close=closes, window=14).average_true_range())

    # Volume anomaly: latest volume vs 20-day average
    vol_avg_20 = volumes.rolling(20).mean().iloc[-1]
    volume_anomaly = round(float(volumes.iloc[-1] / vol_avg_20), 4) if vol_avg_20 > 0 else 1.0

    # MA-20, MA-50
    ma_20 = last(closes.rolling(20).mean())
    ma_50 = last(closes.rolling(50).mean()) if len(closes) >= 50 else None
    ma_cross_bullish = (float(ma_20) > float(ma_50)) if (ma_20 and ma_50) else None

    # 20-day annualised volatility
    log_ret = np.log(closes / closes.shift(1)).dropna()
    vol_window = log_ret.iloc[-20:] if len(log_ret) >= 20 else log_ret
    volatility_20d = round(float(vol_window.std() * math.sqrt(252)), 6)

    return {
        "rsi_14": rsi_14,
        "macd": macd_val,
        "macd_signal": macd_sig,
        "macd_bullish": macd_bullish,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_pct": bb_pct,
        "stoch_rsi": stoch_rsi,
        "atr_14": atr_14,
        "volume_anomaly": volume_anomaly,
        "ma_20": ma_20,
        "ma_50": ma_50,
        "ma_cross_bullish": ma_cross_bullish,
        "volatility_20d": volatility_20d,
    }


# ── Sub-score calculators ──────────────────────────────────────────────────────

def _technical_score(tech: dict, price: float) -> float:
    """
    Combine 5 technical signals into a single 0–1 score.

    Component weights:
      RSI          25 %
      MACD         25 %
      Bollinger    20 %
      Stoch RSI    15 %
      MA cross     15 %
    """
    components: list[tuple[float, float]] = []   # (score, weight)

    # 1. RSI
    rsi = tech.get("rsi_14")
    if rsi is not None:
        if rsi <= 30:
            rsi_s = 1.0
        elif rsi >= 70:
            rsi_s = 0.0
        else:
            rsi_s = 1.0 - (rsi - 30) / 40.0
        components.append((clamp(rsi_s), 0.25))

    # 2. MACD crossover
    macd_bull = tech.get("macd_bullish")
    if macd_bull is not None:
        components.append((1.0 if macd_bull else 0.0, 0.25))

    # 3. Bollinger Band position (bb_pct: 0 = at lower band, 1 = at upper)
    bb_pct = tech.get("bb_pct")
    if bb_pct is not None:
        # Near lower band (oversold) → bullish (1.0); near upper → bearish (0.0)
        bb_s = clamp(1.0 - float(bb_pct))
        components.append((bb_s, 0.20))

    # 4. Stochastic RSI (0 = oversold, 1 = overbought)
    stoch = tech.get("stoch_rsi")
    if stoch is not None:
        stoch_s = clamp(1.0 - float(stoch))
        components.append((stoch_s, 0.15))

    # 5. MA cross
    ma_cross = tech.get("ma_cross_bullish")
    if ma_cross is not None:
        components.append((1.0 if ma_cross else 0.0, 0.15))

    if not components:
        return 0.5

    total_weight = sum(w for _, w in components)
    score = sum(s * w for s, w in components) / total_weight
    return clamp(score)


def _fundamental_score(fund: dict) -> float:
    """
    Derive a 0–1 fundamental health score from yfinance data.
    Returns 0.5 (neutral) when data is absent.

    Components:
      Analyst recommendation   30 %
      Revenue growth           25 %
      P/E ratio (relative)     20 %
      Free cash flow (sign)    15 %
      Debt/equity              10 %
    """
    if not fund or "error" in fund:
        return 0.5

    components: list[tuple[float, float]] = []

    # 1. Analyst recommendation
    rec = (fund.get("analyst_recommendation") or "").lower()
    rec_map = {
        "strong_buy": 1.0, "buy": 0.85,
        "hold": 0.5, "underperform": 0.25, "sell": 0.0,
    }
    if rec in rec_map:
        components.append((rec_map[rec], 0.30))

    # 2. Revenue growth YoY (e.g. 0.20 = 20%)
    rev_growth = fund.get("revenue_growth_yoy")
    if rev_growth is not None:
        # >30% = excellent (1.0), <−20% = terrible (0.0), linear in between
        rg_score = clamp((float(rev_growth) + 0.20) / 0.50)
        components.append((rg_score, 0.25))

    # 3. P/E ratio — lower = cheaper
    pe = fund.get("pe_ratio")
    if pe is not None and float(pe) > 0:
        # PE ≤ 15 = great (1.0), PE ≥ 60 = expensive (0.0)
        pe_score = clamp(1.0 - (float(pe) - 15) / 45.0)
        components.append((pe_score, 0.20))

    # 4. Free cash flow — positive = good
    fcf = fund.get("free_cash_flow")
    if fcf is not None:
        components.append((1.0 if float(fcf) > 0 else 0.0, 0.15))

    # 5. Debt/equity — lower = healthier (0 = best, 2+ = stressed)
    de = fund.get("debt_to_equity")
    if de is not None and float(de) >= 0:
        de_score = clamp(1.0 - float(de) / 200.0)   # yfinance returns % (e.g. 45 = 45%)
        components.append((de_score, 0.10))

    if not components:
        return 0.5

    total_weight = sum(w for _, w in components)
    score = sum(s * w for s, w in components) / total_weight
    return clamp(score)


def _macro_score(macro: dict) -> float:
    """
    Derive a 0–1 macro environment score from FRED data.
    Higher = more macro-supportive for equities.
    Returns 0.5 (neutral) when data is absent.

    Components:
      VIX fear gauge           35 %  low VIX → bullish
      Yield curve spread       35 %  positive (normal) → bullish
      CPI YoY inflation        30 %  moderate → bullish, high → bearish
    """
    if not macro or macro.get("source") in ("no_api_key", "error", "exception"):
        return 0.5

    components: list[tuple[float, float]] = []

    # 1. VIX — low fear is bullish
    vix = macro.get("vix")
    if vix is not None:
        # VIX ≤ 15 = calm (1.0), VIX ≥ 35 = fearful (0.0)
        vix_score = clamp(1.0 - (float(vix) - 15) / 20.0)
        components.append((vix_score, 0.35))

    # 2. Yield curve spread (10Y − 2Y)
    spread = macro.get("yield_curve_spread")
    if spread is not None:
        # Spread ≥ +0.5% = healthy (1.0), Spread ≤ −0.5% = inverted (0.0)
        spread_score = clamp((float(spread) + 0.5) / 1.0)
        components.append((spread_score, 0.35))

    # 3. CPI YoY inflation
    cpi_yoy = macro.get("cpi_yoy_pct")
    if cpi_yoy is not None:
        # 2% = ideal (1.0), 6%+ = bad (0.0), deflation <0% also bad
        cpi = float(cpi_yoy)
        if cpi < 0:
            cpi_score = 0.3         # deflation risk
        elif cpi <= 2.5:
            cpi_score = 1.0
        elif cpi <= 6.0:
            cpi_score = clamp(1.0 - (cpi - 2.5) / 3.5)
        else:
            cpi_score = 0.0
        components.append((cpi_score, 0.30))

    if not components:
        return 0.5

    total_weight = sum(w for _, w in components)
    score = sum(s * w for s, w in components) / total_weight
    return clamp(score)


def _volatility_score(volatility: float) -> float:
    """Convert annualised volatility to 0–1 (lower vol → higher score)."""
    if volatility <= 0.15:
        return 1.0
    if volatility >= 0.80:
        return 0.0
    return clamp(1.0 - (volatility - 0.15) / (0.80 - 0.15))
