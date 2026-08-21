"""
Catalyst Score Service
──────────────────────
Computes a 0–1 score representing presence of a near-term catalyst.

Uses volume anomaly only — this matches the training schema in
scripts/train_xgb.py which also uses volume spike as the sole catalyst
component (historical earnings/analyst data are not available for training).

⚠️  The curve here and the one in scripts/train_xgb.py must stay identical.
Training on a differently-shaped feature than inference produces would mislabel
every row. Both were changed together when the neutral pivot was fixed; any
existing xgb_scorer.json predates that and needs retraining before
ENABLE_ML_MODEL is turned on.

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

    anomaly ≥ 3x  → 1.00  (heavy volume — something is happening)
    anomaly = 2x  → 0.75
    anomaly = 1x  → 0.50  (average volume — no information either way)
    anomaly = 0.5x→ 0.45
    anomaly → 0   → 0.40  (unusually quiet; mildly negative, not damning)
    unavailable   → 0.50

    **Average volume pivots at neutral, not at zero.** The previous curve
    returned 0.0 for anything at or below 1x, so an ordinary trading day scored
    maximally bearish — strictly worse than having no volume data at all, which
    returned 0.5. Every other component in this codebase uses 0.5 for "absent or
    unremarkable"; catalyst was the sole exception, and since it carries 0.15 of
    the composite weight it dragged every score down by up to 0.075.

    That was not a hypothetical: with real data across the whole watchlist this
    function returned exactly 0.000 for every ticker, which alone kept the
    composite ceiling below the 0.70 BUY threshold and left the engine unable to
    emit a directional signal at all.

    The curve is continuous at 1x (both branches give 0.5) so there is no jump
    across the pivot, and the spike range is compressed into the upper half:
    3x volume still earns the maximum, it just starts from neutral rather than
    from zero.
    """
    va = feat_doc.get("volume_anomaly")
    if va is None:
        return 0.5

    va = float(va)
    if va >= 1.0:
        # 1x → 0.5, rising to 1.0 at 3x and capped there.
        score = 0.5 + clamp((va - 1.0) / 4.0, 0.0, 0.5)
    else:
        # Below average tapers gently to a 0.4 floor: a quiet tape means no
        # catalyst, which is not the same as a reason to sell.
        score = 0.4 + 0.1 * clamp(va, 0.0, 1.0)

    score = clamp(score)

    logger.debug(
        "catalyst_score_computed",
        ticker=raw_doc.get("ticker"),
        volume_anomaly=va,
        score=round(score, 4),
    )
    return score
