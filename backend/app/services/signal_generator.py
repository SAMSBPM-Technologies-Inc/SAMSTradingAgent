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
from app.services.risk_engine import RISK_MAX_FOR_BUY, assess_risk
from app.utils.helpers import clamp, utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Canonical signal thresholds. `scoring.compute_personalized_score` imports
#: these rather than restating them: it used to hold its own copies, so tuning
#: one place left any user with custom weights on a different model from the
#: stored signal, silently. RISK_MAX_FOR_BUY comes from risk_engine, which owns
#: the risk scale it belongs to.
BUY_THRESHOLD = 0.70
SELL_THRESHOLD = 0.30

#: How far back through a threshold the score must travel before an established
#: verdict is given up. A score does not sit still: it is recomputed every
#: ingestion cycle from live prices, so one hovering within a rounding error of
#: 0.70 crosses back and forth all session, and a bare comparison turns that
#: noise into a stream of contradictory verdicts. Entering BUY still requires
#: clearing 0.70; leaving it requires falling under 0.67. The band is one-sided
#: on purpose — it makes an existing verdict sticky, never easier to acquire.
SIGNAL_HYSTERESIS = 0.03

__all__ = ["BUY_THRESHOLD", "SELL_THRESHOLD", "SIGNAL_HYSTERESIS",
           "RISK_MAX_FOR_BUY", "generate_signal", "generate_signals_all",
           "classify_signal"]


def classify_signal(
    score: float, risk_score: float, previous_signal: str | None = None
) -> str:
    """
    The BUY / SELL / HOLD rule, in one place.

    BUY is the only verdict gated on risk. That asymmetry is deliberate: the
    gate answers "is it safe to take on this exposure", which has no bearing on
    whether to leave one you already hold. Refusing to exit a position because
    conditions are dangerous would be exactly backwards.

    `previous_signal` engages the hysteresis band: a verdict already in force is
    held until the score retreats `SIGNAL_HYSTERESIS` past the threshold that
    produced it. Omit it (the default) to get the raw rule — that is what
    calibration and threshold sweeps want, since a replay has no "previous".
    """
    buy_exit = BUY_THRESHOLD - SIGNAL_HYSTERESIS if previous_signal == "BUY" else BUY_THRESHOLD
    sell_exit = SELL_THRESHOLD + SIGNAL_HYSTERESIS if previous_signal == "SELL" else SELL_THRESHOLD

    if score > buy_exit and risk_score < RISK_MAX_FOR_BUY:
        return "BUY"
    if score < sell_exit:
        return "SELL"
    return "HOLD"


async def generate_signal(ticker: str, previous_signal: str | None = None) -> dict:
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
    signal = classify_signal(score, risk_score, previous_signal)

    # Confidence is DISTANCE FROM THE DECISION BOUNDARY, not a probability.
    # It says how far from flipping the verdict is, which is not the same as how
    # often verdicts at this level have been right — nothing has ever compared
    # it against stocks_signal_history. Read it as conviction in the arithmetic,
    # not as a hit rate.
    if signal == "BUY":
        confidence = clamp((score - BUY_THRESHOLD) / (1.0 - BUY_THRESHOLD))
    elif signal == "SELL":
        confidence = clamp((SELL_THRESHOLD - score) / SELL_THRESHOLD)
    else:
        # Certainty of being in the middle band
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
        # SELL means "exit the position", never "open a short". It previously
        # read "Short entry near $X | Cover ~$Y", which contradicted both the
        # account and the code: shorting is not permitted in a TFSA, and
        # trade_manager only ever sells to close what the broker actually holds
        # — it has no path that opens a short.
        limit = price * 1.005
        exit_s = (
            f"Exit at ${price:.2f} (current) or limit near ${limit:.2f}. "
            f"No position — no action; this is not a short signal."
        )
        return None, exit_s

    return None, f"Monitor; consider re-evaluating if price moves ±5% from ${price:.2f}"


def _build_explanation(
    ticker: str, signal: str, score: float, risk: dict, feat: dict
) -> str:
    # Technical
    rsi = feat.get("rsi_14")
    rsi_str = f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A"
    ma_bull = feat.get("ma_cross_bullish")
    trend = "bullish" if ma_bull else ("bearish" if ma_bull is False else "neutral")
    macd_bull = feat.get("macd_bullish")
    macd_str = "MACD↑" if macd_bull else ("MACD↓" if macd_bull is False else "")
    bb_pct = feat.get("bb_pct")
    bb_str = f"BB={bb_pct:.0%}" if bb_pct is not None else ""

    # Sub-scores
    tech  = feat.get("technical_score",   0.5)
    fund  = feat.get("fundamental_score", 0.5)
    sent  = feat.get("sentiment_score",   0.5)
    macro = feat.get("macro_score",       0.5)

    indicators = " | ".join(filter(None, [rsi_str, macd_str, bb_str, f"MA={trend}"]))
    scores_str = (
        f"tech={tech:.2f} fund={fund:.2f} sent={sent:.2f} macro={macro:.2f}"
    )

    return (
        f"{ticker} → {signal} | score={score:.2f} | "
        f"Risk={risk['risk_level']} ({risk['risk_score']:.1f}/10) | "
        f"{indicators} | [{scores_str}]. {risk['explanation']}"
    )
