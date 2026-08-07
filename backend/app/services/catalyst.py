"""
Catalyst Score Service
──────────────────────
Computes a 0–1 score representing proximity to, or presence of, a near-term
positive catalyst for a given ticker.

Components (weights must sum to 1.0):
  Earnings proximity  35 %  — closer earnings date = higher urgency
  Analyst target upside 30% — meaningful upside to consensus target = catalyst
  Volume spike        20 %  — unusual volume suggests catalyst already in play
  Analyst conviction  15 %  — strong buy/upgrade = catalyst implied

All inputs come from data already stored in stocks_raw / stocks_features,
so this adds zero additional API calls.
"""
from datetime import datetime, timezone
from typing import Optional

from app.utils.helpers import clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)


def compute_catalyst_score(raw_doc: dict, feat_doc: dict) -> float:
    """
    Derive a catalyst score from the raw and feature documents.
    Returns a float in [0, 1].
    """
    fund = raw_doc.get("fundamentals") or {}
    components: list[tuple[float, float]] = []   # (score, weight)

    # 1. Earnings proximity
    ep = _earnings_proximity_score(fund.get("next_earnings_date"))
    if ep is not None:
        components.append((ep, 0.35))

    # 2. Analyst target upside
    au = _analyst_upside_score(
        current_price=raw_doc.get("current_price"),
        analyst_target=fund.get("analyst_target_price"),
    )
    if au is not None:
        components.append((au, 0.30))

    # 3. Volume spike (from feature_engineering volume_anomaly)
    vs = _volume_spike_score(feat_doc.get("volume_anomaly"))
    if vs is not None:
        components.append((vs, 0.20))

    # 4. Analyst recommendation strength
    ar = _analyst_rec_score(fund.get("analyst_recommendation"))
    if ar is not None:
        components.append((ar, 0.15))

    if not components:
        return 0.5   # neutral when no data

    total_weight = sum(w for _, w in components)
    score = sum(s * w for s, w in components) / total_weight

    logger.debug(
        "catalyst_score_computed",
        ticker=raw_doc.get("ticker"),
        score=round(score, 4),
        components=len(components),
    )
    return clamp(score)


# ── Component calculators ──────────────────────────────────────────────────────

def _earnings_proximity_score(next_earnings_date: Optional[str]) -> Optional[float]:
    """
    Higher score = earnings are sooner (more urgency / event risk / catalyst).

    days_to_earnings ≤ 7   → 1.0  (earnings this week)
    days_to_earnings = 30  → 0.75
    days_to_earnings = 60  → 0.40
    days_to_earnings ≥ 90  → 0.0
    """
    if not next_earnings_date:
        return None
    try:
        # yfinance returns strings like "2026-10-28 00:00:00" or Timestamps
        date_str = str(next_earnings_date).split(" ")[0]
        earnings_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days = (earnings_dt - datetime.now(tz=timezone.utc)).days
        if days < 0:
            return None   # earnings already passed
        return clamp(1.0 - days / 90.0)
    except Exception:
        return None


def _analyst_upside_score(
    current_price: Optional[float],
    analyst_target: Optional[float],
) -> Optional[float]:
    """
    Upside to analyst consensus target → 0–1 score.

    upside ≥ 30 %  → 1.0
    upside = 10 %  → 0.5
    upside ≤ 0 %   → 0.0  (at or above target = no upside catalyst)
    """
    if not current_price or not analyst_target or current_price <= 0:
        return None
    upside = (analyst_target - current_price) / current_price  # e.g. 0.20 = 20%
    return clamp(upside / 0.30)   # 30% upside = full score


def _volume_spike_score(volume_anomaly: Optional[float]) -> Optional[float]:
    """
    Unusual volume suggests a catalyst is already in play.

    anomaly ≥ 3x  → 1.0
    anomaly = 2x  → 0.67
    anomaly = 1x  → 0.0  (normal volume)
    anomaly < 1x  → 0.0  (below-average = no catalyst signal)
    """
    if volume_anomaly is None:
        return None
    va = float(volume_anomaly)
    if va <= 1.0:
        return 0.0
    return clamp((va - 1.0) / 2.0)   # 3x anomaly = full score


def _analyst_rec_score(recommendation: Optional[str]) -> Optional[float]:
    """Map analyst consensus recommendation to a 0–1 catalyst strength."""
    if not recommendation:
        return None
    rec_map = {
        "strong_buy": 1.0,
        "buy": 0.80,
        "hold": 0.40,
        "underperform": 0.15,
        "sell": 0.0,
    }
    return rec_map.get(str(recommendation).lower())
