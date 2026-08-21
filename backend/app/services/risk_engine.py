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

# Thresholds
_LOW_MAX = 3.5
_HIGH_MIN = 6.5


def assess_risk(features: dict) -> dict:
    """
    Compute risk from a feature document.
    Returns {"risk_score": float, "risk_level": str, "explanation": str}.
    """
    factors: list[str] = []
    raw_score = 0.0  # accumulates, then normalised to 0–10

    # ── Factor 1: Volatility ─────────────────────────────────────────────────
    # Two segments. The first is the original 0→4 points across 0–80%; the
    # second adds up to 3 more between 80% and 160%.
    #
    # Capping the whole factor at 4 points meant volatility alone could never
    # reach the 6.0 that blocks a BUY, no matter how extreme. Cerebras at 143%
    # annualised — a stock that can move roughly ±9% on an ordinary day —
    # scored 4.0 MEDIUM and passed the risk gate, identical to Palantir at
    # 106%. A risk check that cannot fail on its worst input is not a check.
    vol = features.get("volatility_20d") or 0.0
    vol_contribution = clamp(vol / 0.80) * 4.0
    if vol > 0.80:
        vol_contribution += clamp((vol - 0.80) / 0.80) * 3.0
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
