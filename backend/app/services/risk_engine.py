"""
Risk Engine
───────────
Converts computed features into a risk assessment:
  - risk_score  : 0 (safest) → 10 (most dangerous)
  - risk_level  : LOW | MEDIUM | HIGH
  - explanation : human-readable string

Risk factors considered:
  1. Annualised volatility          (higher → more risk)
  2. RSI extremes                   (>75 or <25 → more risk)
  3. Composite score divergence     (low score = already declining → more risk)
  4. MA trend alignment             (bearish alignment → more risk)
"""
from app.utils.helpers import clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: A BUY is refused at or above this risk score. Defined here rather than in
#: signal_generator because it is a property of the risk scale, and because the
#: volatility curve below is calibrated so that its knee lands exactly on it.
RISK_MAX_FOR_BUY = 6.0

# Thresholds
_LOW_MAX = 3.5
#: HIGH begins where the BUY veto begins. These were 6.5 and 6.0 respectively,
#: so a score of 6.2 reported MEDIUM while silently blocking the trade — anyone
#: reading the explanation saw a moderate risk and an unexplained missing
#: signal. Deriving one from the other makes the label and the behaviour
#: incapable of disagreeing.
_HIGH_MIN = RISK_MAX_FOR_BUY


def assess_risk(features: dict) -> dict:
    """
    Compute risk from a feature document.
    Returns {"risk_score": float, "risk_level": str, "explanation": str}.
    """
    factors: list[str] = []
    raw_score = 0.0  # accumulates, then normalised to 0–10

    # ── Factor 1: Volatility ─────────────────────────────────────────────────
    # Two segments with the knee placed exactly on the BUY veto: 100% annualised
    # volatility scores RISK_MAX_FOR_BUY, so "the gate refuses this on
    # volatility alone" and "this name moves more than 100% annualised" are the
    # same statement, which is the only version of this curve that explains
    # itself.
    #
    # Steepened when volatility was removed from the composite. It had been
    # charged twice — 0.10 of the score AND up to 7 risk points — and taking it
    # out of the score removed a soft brake the gate was never calibrated to
    # replace. Under the previous curve a name needed 135% annualised before
    # volatility alone refused a BUY; a 130% stock, one that moves roughly ±8%
    # on an ordinary day, sailed through at 5.88. It now scores 7.0.
    #
    # Caps at 8.0 rather than 10 so the remaining factors still have room to
    # push a genuinely broken name higher.
    vol = features.get("volatility_20d") or 0.0
    if vol <= 1.00:
        vol_contribution = clamp(vol / 1.00) * RISK_MAX_FOR_BUY
    else:
        vol_contribution = RISK_MAX_FOR_BUY + clamp((vol - 1.00) / 0.60) * 2.0
    raw_score += vol_contribution
    if vol > 1.20:
        factors.append(f"extreme annualised volatility ({vol:.0%}) — position risk is severe")
    elif vol > 0.50:
        factors.append(f"very high annualised volatility ({vol:.0%})")
    elif vol > 0.30:
        factors.append(f"elevated volatility ({vol:.0%})")

    # ── Factor 2: RSI extremes ───────────────────────────────────────────────
    rsi = features.get("rsi_14") or 50.0
    if rsi > 75:
        raw_score += 2.5
        factors.append(f"RSI overbought at {rsi:.1f}")
    elif rsi < 25:
        raw_score += 1.5   # oversold is risky but also opportunity
        factors.append(f"RSI oversold at {rsi:.1f}")

    # ── Factor 3: Composite score ────────────────────────────────────────────
    comp = features.get("composite_score", 0.5)
    if comp < 0.3:
        raw_score += 2.0
        factors.append(f"low composite AI score ({comp:.2f})")
    elif comp < 0.45:
        raw_score += 1.0

    # ── Factor 4: MA trend alignment ─────────────────────────────────────────
    ma_cross_bullish = features.get("ma_cross_bullish")
    if ma_cross_bullish is False:  # explicit bearish cross
        raw_score += 1.5
        factors.append("bearish MA cross (MA-20 < MA-50)")

    # ── Normalise ─────────────────────────────────────────────────────────────
    risk_score = clamp(raw_score, 0.0, 10.0)

    if risk_score <= _LOW_MAX:
        risk_level = "LOW"
    elif risk_score >= _HIGH_MIN:
        risk_level = "HIGH"
    else:
        risk_level = "MEDIUM"

    if factors:
        explanation = "Risk driven by: " + "; ".join(factors) + "."
    else:
        explanation = "No significant risk flags detected."

    result = {
        "risk_score": round(risk_score, 2),
        "risk_level": risk_level,
        "explanation": explanation,
    }
    logger.debug("risk_assessed", **result)
    return result
