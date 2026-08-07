"""
Catalyst Score Service
──────────────────────
Computes a 0–1 score representing presence of a near-term catalyst.

Uses volume anomaly only — this matches the training schema in
scripts/train_xgb.py which also uses volume spike as the sole catalyst
component (historical earnings/analyst data are not available for training).

To add multi-component catalyst scoring (earnings proximity, analyst upside,
analyst rec), update train_xgb.py to match and retrain xgb_scorer.json first.
"""
from app.utils.helpers import clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)


def compute_catalyst_score(raw_doc: dict, feat_doc: dict) -> float:
    """
    Derive a catalyst score from volume anomaly.
    Returns a float in [0, 1].

    anomaly ≥ 3x  → 1.0
    anomaly = 2x  → 0.67
    anomaly = 1x  → 0.0  (normal volume)
    anomaly < 1x  → 0.0  (below-average = no catalyst signal)
    neutral 0.5 when volume_anomaly is unavailable
    """
    va = feat_doc.get("volume_anomaly")
    if va is None:
        return 0.5

    score = clamp((float(va) - 1.0) / 2.0) if float(va) > 1.0 else 0.0

    logger.debug(
        "catalyst_score_computed",
        ticker=raw_doc.get("ticker"),
        volume_anomaly=va,
        score=round(score, 4),
    )
    return score
