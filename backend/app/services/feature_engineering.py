"""
Feature Engineering Service
────────────────────────────
Reads raw price/fundamental/macro data from MongoDB and computes:

  Technical indicators  : RSI-14, MACD, Bollinger Bands, Stochastic RSI,
                          ATR, MA-20/50, volume anomaly, OBV, ADX-14, VWAP-20
  Sub-scores (all 0–1)  : technical, fundamental, sentiment, macro, volatility
  Composite             : delegated to scoring.py (not computed here)

The `ta` library handles indicator math; numpy/pandas handle series ops.
"""
import math
from typing import Optional

import numpy as np
import pandas as pd
import ta

from app.config import get_settings
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
    # Sector and realised volatility scale the market-wide reading to this
    # ticker's actual exposure — see _macro_sensitivity.
    macro_sensitivity = _macro_sensitivity(
        fundamentals.get("sector"), tech["volatility_20d"]
    )
    macro_score     = _macro_score(
        macro, fundamentals.get("sector"), tech["volatility_20d"]
    )

    # Store raw macro values needed by scoring.py XGBoost feature vector
    macro_vix          = macro.get("vix")
    macro_yield_spread = macro.get("yield_curve_spread")
    macro_cpi_yoy      = macro.get("cpi_yoy_pct")

    # catalyst_score needs both raw_doc and the partially-built feat dict
    _partial_feat = {"volume_anomaly": tech["volume_anomaly"]}
    catalyst_score = compute_catalyst_score(raw_doc, _partial_feat)

    from app.services.alternative_data import compute_alternative_score
    alt_data = raw_doc.get("alternative_data") or {}
    alternative_data_score = compute_alternative_score(alt_data)

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
        "obv":              tech["obv"],
        "obv_rising":       tech["obv_rising"],
        "adx_14":           tech["adx_14"],
        "vwap_20":          tech["vwap_20"],
        # ── Raw macro fields (for XGBoost feature vector in scoring.py) ──────
        "vix":               macro_vix,
        "yield_curve_spread": macro_yield_spread,
        "cpi_yoy_pct":       macro_cpi_yoy,
        # Why this ticker's macro_score differs from the market-wide reading.
        "macro_sensitivity": round(macro_sensitivity, 4),
        "sector":            fundamentals.get("sector"),
        # ── Sub-scores (all 0–1) ─────────────────────────────────────────────
        "technical_score":    round(technical_score,   4),
        "fundamental_score":  round(fundamental_score, 4),
        "sentiment_score":    round(sentiment_score,   4),
        "macro_score":        round(macro_score,       4),
        "volatility_score":   round(volatility_score,  4),
        "catalyst_score":            round(catalyst_score,          4),
        "alternative_data_score":    round(alternative_data_score,  4),
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
        alternative=round(alternative_data_score, 4),
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

    # OBV (On-Balance Volume): cumulative, so the raw level isn't
    # comparable across tickers — track direction over the last 10 bars
    # instead (rising = accumulation, falling = distribution).
    obv_series = ta.volume.OnBalanceVolumeIndicator(close=closes, volume=volumes).on_balance_volume()
    obv = last(obv_series)
    obv_clean = obv_series.dropna()
    obv_rising = bool(obv_clean.iloc[-1] > obv_clean.iloc[-11]) if len(obv_clean) >= 11 else None

    # ADX-14 (trend strength, direction-agnostic). ta's ADXIndicator
    # indexes into an internal array by `window` and raises IndexError
    # on short series instead of returning NaN, so guard the length
    # and swallow any failure rather than let one bad ticker crash the job.
    adx_14 = None
    if len(closes) >= 30:
        try:
            adx_14 = last(ta.trend.ADXIndicator(high=highs, low=lows, close=closes, window=14).adx())
        except Exception:
            adx_14 = None

    # VWAP-20: rolling 20-day volume-weighted average price. Bars here are
    # daily closes, not intraday ticks, so a same-day-reset VWAP isn't
    # meaningful — this is the daily-bar analogue used instead.
    typical_price = (highs + lows + closes) / 3.0
    vwap_num = (typical_price * volumes).rolling(20).sum()
    vwap_den = volumes.rolling(20).sum()
    vwap_20 = last(vwap_num / vwap_den)

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
        "obv": obv,
        "obv_rising": obv_rising,
        "adx_14": adx_14,
        "vwap_20": vwap_20,
    }


# ── Sub-score calculators ──────────────────────────────────────────────────────

#: Component weights per technical stance, as (rsi, macd, bb, stoch, ma_cross).
#:
#: The stance is now declared rather than implied. The original weights blended
#: two opposing philosophies without saying so: RSI, Bollinger and Stochastic
#: are MEAN-REVERSION signals that score higher as price weakens, while MACD and
#: the MA cross are TREND signals that score higher as it strengthens. At 60/40
#: the mean-reversion side quietly held the majority, so the model was a
#: dip-buyer by accident of weighting.
#:
#: Palantir showed the tension plainly: RSI 66, Bollinger 0.72 and Stochastic
#: 0.71 all marked it down for being extended, while MACD and the MA cross both
#: marked it up for trending — a stock penalised and rewarded for the same fact.
_STANCE_WEIGHTS = {
    # Buy weakness in sound companies. Trend signals act as confirmation only,
    # which is what the dip-buy setup scan already assumes.
    "mean_reversion": (0.30, 0.15, 0.25, 0.20, 0.10),
    # Buy strength. The mean-reversion inputs are INVERTED below, so an extended
    # RSI reads bullish rather than bearish.
    "momentum":       (0.20, 0.30, 0.15, 0.10, 0.25),
    # The historical blend — kept so results before this change stay reproducible.
    "blended":        (0.25, 0.25, 0.20, 0.15, 0.15),
}

#: Relative weights of the three oscillators *within* the reversion signal,
#: renormalised from the stance weights above so the split stays recognisable.
_OSC_WEIGHTS = (0.40, 0.33, 0.27)   # (rsi, bb, stoch)

#: How much trend confirmation can suppress an oscillator reading, as
#: `gate = _TREND_FLOOR + (1 - _TREND_FLOOR) * trend`.
#:
#: 0.40 rather than 0.0 because an oscillator extreme against the trend is a
#: discounted signal, not a meaningless one — a genuine capitulation low still
#: deserves to outrank a mid-range drift. It is the *ranking* that matters here,
#: not the absolute level.
_TREND_FLOOR = 0.40


def _trend_confirmation(tech: dict) -> Optional[float]:
    """
    0–1 reading of whether price structure supports the oscillators.

    Returns None when neither trend input is available, so the caller can fall
    back to the additive blend rather than inventing a gate from nothing.
    """
    parts = [
        1.0 if v else 0.0
        for v in (tech.get("macd_bullish"), tech.get("ma_cross_bullish"))
        if v is not None
    ]
    return sum(parts) / len(parts) if parts else None


def _technical_score(tech: dict, price: float) -> float:
    """
    Combine 5 technical signals into a single 0–1 score.

    Direction and weighting both follow `technical_stance` (see
    `_STANCE_WEIGHTS`). Under `momentum` the RSI, Bollinger and Stochastic
    components are inverted, so the same indicator that reads bullish when
    oversold under mean-reversion reads bullish when overbought instead.

    Trend GATES the oscillators rather than being averaged against them
    ────────────────────────────────────────────────────────────────────
    Averaging made the two halves cancel, and the casualty was the distinction
    that matters most to a dip-buyer: a pullback within an uptrend versus a
    stock in free fall. Both look oversold on RSI, Bollinger and Stochastic;
    only the first is worth buying. Under the old additive blend, a deep
    selloff with MACD and the MA cross both bearish scored 0.728 while the
    textbook pullback-in-uptrend scored 0.772 — a separation of 0.045, well
    inside the noise. The engine was, in effect, indifferent between catching
    a falling knife and buying a dip.

    Multiplying instead of averaging restores the conditional the strategy
    always implied: *oversold is a reason to buy only when the trend is still
    intact*. The same two cases now score 0.388 and 0.697 — a separation of
    0.309, roughly seven times wider. The ceiling also improves: a shallow
    pullback in a strong uptrend can now approach 1.0, which the additive form
    made unreachable, because a perfect oscillator reading forced the trend
    components to 0.

    `blended` keeps the additive path unchanged, as its name promises, so
    historical results stay reproducible.
    """
    stance = get_settings().technical_stance
    w_rsi, w_macd, w_bb, w_stoch, w_ma = _STANCE_WEIGHTS.get(
        stance, _STANCE_WEIGHTS["mean_reversion"]
    )
    momentum = stance == "momentum"

    # ── Oscillator readings, oriented so 1.0 always means "bullish" ──────────
    # Each carries both weightings: the within-signal weight used by the gated
    # path, and the stance weight used by the additive fallback.
    oscillators: list[tuple[float, float, float]] = []   # (score, osc_w, stance_w)
    w_osc_rsi, w_osc_bb, w_osc_stoch = _OSC_WEIGHTS

    def _orient(bullish_when_weak: float) -> float:
        return 1.0 - bullish_when_weak if momentum else bullish_when_weak

    # 1. RSI — oversold is bullish under mean-reversion, bearish under momentum
    rsi = tech.get("rsi_14")
    if rsi is not None:
        if rsi <= 30:
            rsi_s = 1.0
        elif rsi >= 70:
            rsi_s = 0.0
        else:
            rsi_s = 1.0 - (rsi - 30) / 40.0
        oscillators.append((_orient(clamp(rsi_s)), w_osc_rsi, w_rsi))

    # 2. Bollinger Band position (bb_pct: 0 = at lower band, 1 = at upper)
    bb_pct = tech.get("bb_pct")
    if bb_pct is not None:
        oscillators.append((_orient(clamp(1.0 - float(bb_pct))), w_osc_bb, w_bb))

    # 3. Stochastic RSI (0 = oversold, 1 = overbought)
    stoch = tech.get("stoch_rsi")
    if stoch is not None:
        oscillators.append((_orient(clamp(1.0 - float(stoch))), w_osc_stoch, w_stoch))

    trend = _trend_confirmation(tech)

    # ── Gated path (mean_reversion / momentum) ───────────────────────────────
    if stance != "blended" and oscillators and trend is not None:
        osc = sum(s * w for s, w, _ in oscillators) / sum(w for _, w, _ in oscillators)
        return clamp(osc * (_TREND_FLOOR + (1.0 - _TREND_FLOOR) * trend))

    # ── Additive path — `blended`, or whenever a trend input is missing ──────
    # Without a trend reading there is nothing to gate on, and gating against an
    # invented neutral would silently scale every score down. Falling back to
    # the stance weights keeps that case identical to the previous behaviour.
    components: list[tuple[float, float]] = [(s, sw) for s, _, sw in oscillators]

    macd_bull = tech.get("macd_bullish")
    if macd_bull is not None:
        components.append((1.0 if macd_bull else 0.0, w_macd))

    ma_cross = tech.get("ma_cross_bullish")
    if ma_cross is not None:
        components.append((1.0 if ma_cross else 0.0, w_ma))

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
        de_score = clamp(1.0 - float(de) / 200.0)   # percentage scale (45 = 45%)
        components.append((de_score, 0.10))

    if not components:
        return 0.5

    # Blend toward neutral in proportion to what is MISSING, rather than
    # re-normalising over whatever happens to be present.
    #
    # Plain re-normalisation rewards absent data. Cerebras (CBRS) listed in May
    # 2026 and has filed no annual report, so P/E, free cash flow and
    # debt/equity — every valuation and balance-sheet check — were unavailable.
    # The two that survived were analyst consensus and revenue growth, both
    # bullish, and re-normalising over them scored it 0.918: the highest
    # fundamental score in the watchlist, above NVDA's 0.864, which is measured
    # on all five INCLUDING a P/E that counts against it.
    #
    # A company whose only available data is optimistic should not outrank one
    # with a complete picture. Coverage-weighting pulls the unmeasured portion
    # to 0.5, so a partial read lands nearer neutral and confidence tracks
    # evidence. CBRS becomes ~0.73 at 55% coverage; full-coverage names are
    # arithmetically unchanged.
    coverage = sum(w for _, w in components)          # 0..1; 1.0 = all five
    raw = sum(s * w for s, w in components) / coverage
    score = raw * coverage + 0.5 * (1.0 - coverage)
    return clamp(score)


#: How hard each sector reacts to the macro regime, as a multiplier on the
#: market-wide reading. Long-duration cash flows and discretionary demand swing
#: with rates and risk appetite; inelastic demand does not.
#:
#: Utilities sit high despite stable demand because they trade as bond proxies —
#: it is the rates leg of the macro score they respond to, not the growth leg.
#: Names are matched case-insensitively and cover both the yfinance and Alpha
#: Vantage spellings, which differ ("Consumer Cyclical" vs "Consumer Discretionary").
_SECTOR_MACRO_BETA = {
    "real estate":             1.25,
    "technology":              1.15,
    "information technology":  1.15,
    "consumer cyclical":       1.15,
    "consumer discretionary":  1.15,
    "financial services":      1.10,
    "financials":              1.10,
    "industrials":             1.05,
    "communication services":  1.00,
    "basic materials":         1.00,
    "materials":               1.00,
    "energy":                  0.95,
    "utilities":               0.85,
    "health care":             0.75,
    "healthcare":              0.75,
    "consumer defensive":      0.65,
    "consumer staples":        0.65,
}


def _macro_sensitivity(sector: Optional[str], volatility_20d: Optional[float]) -> float:
    """
    How much *this* ticker should care about the market-wide macro reading.

    1.0 means "feels the macro exactly as scored"; below 1.0 damps it toward
    neutral. Derived from sector plus realised volatility, the latter standing in
    for beta, which no provider in the stack currently supplies.

    Volatility is used only as a ±30% adjustment, not as the primary term, so a
    quiet month in a cyclical name does not turn it into a defensive one.
    """
    base = _SECTOR_MACRO_BETA.get((sector or "").strip().lower(), 1.0)

    # 30% annualised is the pivot: at that level the adjustment is neutral.
    if volatility_20d is not None and volatility_20d > 0:
        vol_factor = clamp(0.70 + (float(volatility_20d) / 0.30) * 0.30, 0.70, 1.30)
    else:
        vol_factor = 1.0

    return clamp(base * vol_factor, 0.0, 1.5)


def _macro_score(
    macro: dict,
    sector: Optional[str] = None,
    volatility_20d: Optional[float] = None,
) -> float:
    """
    Derive a 0–1 macro environment score from FRED data.
    Higher = more macro-supportive for equities.

    Scaled by per-ticker sensitivity
    ────────────────────────────────
    VIX, the yield curve and CPI are properties of the market, not of a stock,
    so the raw reading is identical for every ticker in the watchlist. Carrying
    0.15 of the composite weight, and ranging 0.32 (stress) to 1.00 (benign) in
    practice, it moved every score by up to 0.10 in the same direction at the
    same time — a market-timing overlay sitting inside a stock-picking score. It
    could not rank two tickers against each other, only raise or lower the whole
    book, which meant the BUY count tracked the regime rather than the names.

    Sensitivity restores the discrimination: the market reading is damped toward
    neutral for tickers that are genuinely less exposed to it. A utility and a
    high-beta software name no longer receive the same macro verdict. With
    sensitivity 1.0 the behaviour is exactly as before.

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

    # Damp the market-wide reading toward neutral by this ticker's exposure.
    sensitivity = _macro_sensitivity(sector, volatility_20d)
    return clamp(0.5 + sensitivity * (clamp(score) - 0.5))


def _volatility_score(volatility: float) -> float:
    """
    Convert annualised volatility to 0–1 (lower vol → higher score).

        ≤15%  → 1.00
         80%  → 0.15
        ≥150% → 0.00

    Two segments rather than one, because the old curve bottomed out at 80% and
    reported everything above it as an identical 0.0 — Cerebras at 143% and
    Palantir at 106% were indistinguishable, though one is roughly a third more
    volatile than the other. The 15–80% ramp is essentially unchanged, so names
    in the normal range score as before; the second segment only restores
    discrimination among the genuinely extreme, where it matters most.
    """
    if volatility <= 0.15:
        return 1.0
    if volatility >= 1.50:
        return 0.0
    if volatility <= 0.80:
        # 1.00 at 15% down to 0.15 at 80% — the original slope, floored at 0.15
        # instead of 0 so the tail below still has somewhere to go.
        return clamp(1.0 - (volatility - 0.15) / (0.80 - 0.15) * 0.85)
    # 0.15 at 80% down to 0.00 at 150%
    return clamp(0.15 * (1.0 - (volatility - 0.80) / (1.50 - 0.80)))
