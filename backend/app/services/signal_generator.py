"""
Signal Generator
────────────────
Applies rule-based logic on top of composite score + risk assessment
to produce a BUY / SELL / HOLD signal with confidence and entry/exit hints.

Rules:
  BUY  → score > 0.70  AND  risk_score < 6
  SELL → score < 0.30
  HOLD → everything else

Confidence = distance of the score from the nearest decision boundary,
scaled to [0, 1].
"""
from datetime import datetime, timezone

from app.db import COLL_FEATURES, COLL_SIGNALS, get_db
from app.services.risk_engine import assess_risk
from app.utils.helpers import clamp, utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

BUY_THRESHOLD = 0.70
SELL_THRESHOLD = 0.30
RISK_MAX_FOR_BUY = 6.0


async def generate_signal(ticker: str) -> dict:
    """
    Load feature doc → assess risk → apply signal rules → persist + return signal dict.
    """
    ticker = ticker.upper()
    db = await get_db()

    feat = await db[COLL_FEATURES].find_one({"ticker": ticker})
    if feat is None:
        raise ValueError(f"No features found for {ticker}. Run the pipeline first.")

    score: float = feat.get("composite_score", 0.5)
    risk_dict = assess_risk(feat)
    risk_score: float = risk_dict["risk_score"]

    # ── Signal decision ───────────────────────────────────────────────────────
    if score > BUY_THRESHOLD and risk_score < RISK_MAX_FOR_BUY:
        signal = "BUY"
        confidence = clamp((score - BUY_THRESHOLD) / (1.0 - BUY_THRESHOLD))
    elif score < SELL_THRESHOLD:
        signal = "SELL"
        confidence = clamp((SELL_THRESHOLD - score) / SELL_THRESHOLD)
    else:
        signal = "HOLD"
        # Confidence = certainty of being in the middle band
        dist_from_buy = abs(score - BUY_THRESHOLD)
        dist_from_sell = abs(score - SELL_THRESHOLD)
        confidence = clamp(min(dist_from_buy, dist_from_sell) / 0.40)

    # ── Entry / exit suggestions ──────────────────────────────────────────────
    price = feat.get("current_price", 0.0)
    entry_suggestion, exit_suggestion = _price_suggestions(signal, price, feat)

    # ── Explanation ───────────────────────────────────────────────────────────
    explanation = _build_explanation(ticker, signal, score, risk_dict, feat)

    signal_doc = {
        "ticker": ticker,
        "generated_at": utcnow(),
        "score": round(score, 4),
        "risk": risk_dict,
        "signal": signal,
        "confidence": round(confidence, 4),
        "entry_suggestion": entry_suggestion,
        "exit_suggestion": exit_suggestion,
        "explanation": explanation,
    }

    # Upsert – keep only the latest signal per ticker
    await db[COLL_SIGNALS].replace_one(
        {"ticker": ticker},
        signal_doc,
        upsert=True,
    )

    logger.info(
        "signal_generated",
        ticker=ticker,
        signal=signal,
        score=score,
        risk=risk_score,
        confidence=round(confidence, 4),
    )
    return signal_doc


async def generate_signals_all(tickers: list[str]) -> dict[str, str]:
    """Generate signals for multiple tickers; returns ticker → 'ok' | error."""
    results: dict[str, str] = {}
    for ticker in tickers:
        try:
            await generate_signal(ticker)
            results[ticker] = "ok"
        except Exception as exc:
            logger.warning("signal_failed", ticker=ticker, error=str(exc))
            results[ticker] = str(exc)
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _price_suggestions(signal: str, price: float, feat: dict):
    """Return (entry_suggestion, exit_suggestion) strings."""
    if price <= 0:
        return None, None

    atr_approx = price * (feat.get("volatility_20d") or 0.02) / 16  # rough intraday ATR

    if signal == "BUY":
        entry = f"${price:.2f} (current) or limit near ${price * 0.99:.2f}"
        stop_loss = price - 2 * atr_approx
        take_profit = price + 3 * atr_approx
        exit_s = f"Stop-loss ~${stop_loss:.2f} | Take-profit ~${take_profit:.2f}"
        return entry, exit_s

    if signal == "SELL":
        entry = f"Short entry near ${price:.2f}"
        cover = price - 3 * atr_approx
        stop = price + 2 * atr_approx
        exit_s = f"Cover ~${cover:.2f} | Stop ~${stop:.2f}"
        return entry, exit_s

    return None, f"Monitor; consider re-evaluating if price moves ±5% from ${price:.2f}"


def _build_explanation(
    ticker: str, signal: str, score: float, risk: dict, feat: dict
) -> str:
    rsi = feat.get("rsi_14")
    ma_bull = feat.get("ma_cross_bullish")
    trend = "bullish" if ma_bull else ("bearish" if ma_bull is False else "neutral")
    rsi_str = f"RSI={rsi:.1f}" if rsi else "RSI=N/A"
    return (
        f"{ticker} → {signal} | AI score={score:.2f} | "
        f"Risk={risk['risk_level']} ({risk['risk_score']:.1f}/10) | "
        f"MA trend={trend} | {rsi_str}. {risk['explanation']}"
    )
