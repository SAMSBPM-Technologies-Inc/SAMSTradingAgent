"""
Catalyst Score Service
──────────────────────
A 0–1 score for "is something about to move this stock" — near-term events and
expected repricing, as distinct from whether the business is sound (fundamental)
or where price sits in its range (technical).

Why this was rebuilt
────────────────────
It was volume anomaly and nothing else. On typical volume — 0.8× to 1.5× the
20-day average, which is most days — the whole component moved the composite
between -0.003 and +0.019. It carried 0.15 of the weight and was, in practice,
a constant. One thin input under a name promising much more.

Three components now, chosen because each is genuinely forward-looking and none
is already priced elsewhere in the model:

    Volume anomaly     40 %   something is happening now
    News flow          30 %   attention is arriving
    Analyst upside     30 %   the street expects repricing

`buzz` and `analyst_target_price` were both already being fetched and stored,
and neither was read by any scorer. Insider activity and options flow were
deliberately NOT included despite being available: `alternative_data_score`
already prices both, and importing them here would recreate exactly the
double-count that was just removed from volatility.

Earnings proximity would be the strongest component of the three and is absent
for a data reason, not an oversight — `next_earnings_date` is not supplied by
either fundamentals provider (see the note atop fundamentals.py). Worth adding
if a provider ever carries it.

Coverage weighting follows `_fundamental_score`: a score built from one
component is pulled toward neutral rather than trusted as if built from three.

⚠️  XGBoost training schema
The curve here no longer matches scripts/train_xgb.py, which uses volume spike
as the sole catalyst component. Any existing xgb_scorer.json is trained on a
differently-shaped feature than this produces and would mislabel every row.
That path does not run in production (the model file is gitignored and never
reaches the box, and ENABLE_ML_MODEL defaults to false), but train_xgb.py must
be updated to match and the model retrained before it is ever switched on.
"""
from typing import Optional

from app.utils.helpers import clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Component weights. Volume leads because it is the only one that reflects
#: something happening *right now* rather than something expected.
_W_VOLUME  = 0.40
_W_NEWS    = 0.30
_W_UPSIDE  = 0.30

#: Analyst upside bounds. Asymmetric on purpose: a target below the current
#: price is a stronger statement than the same distance above it, targets being
#: chronically optimistic across the sell side.
_UPSIDE_MAX = 0.25    # +25% to target → 1.0
_UPSIDE_MIN = -0.15   # -15% to target → 0.0


def _volume_component(va: Optional[float]) -> Optional[float]:
    """
    Volume against the 20-day average.

    Average volume pivots at neutral, not at zero. The original curve returned
    0.0 for anything at or below 1x, so an ordinary trading day scored maximally
    bearish — strictly worse than having no data, which returned 0.5. With real
    data that produced exactly 0.000 across the entire watchlist and alone kept
    the composite under the BUY threshold.
    """
    if va is None:
        return None
    va = float(va)
    if va >= 1.0:
        # 1x → 0.5, rising to 1.0 at 3x and capped there.
        return clamp(0.5 + clamp((va - 1.0) / 4.0, 0.0, 0.5))
    # Below average tapers gently to a 0.4 floor: a quiet tape means no
    # catalyst, which is not the same as a reason to sell.
    return clamp(0.4 + 0.1 * clamp(va, 0.0, 1.0))


def _news_component(article_count: Optional[int]) -> Optional[float]:
    """
    News flow as an attention proxy, independent of whether the news is good.

    Direction is sentiment's job; this asks only whether the market is paying
    unusual attention. Three articles over the lookback is an ordinary week for
    a covered name, so that sits at neutral; ten or more is a story.
    """
    if article_count is None:
        return None
    n = int(article_count)
    if n >= 3:
        # 3 → 0.5, rising to 1.0 at 12+
        return clamp(0.5 + (n - 3) / 18.0)
    # Silence is mildly negative for a catalyst score, not damning.
    return clamp(0.40 + n * (0.10 / 3.0))


def _upside_component(target: Optional[float], price: Optional[float]) -> Optional[float]:
    """Distance from the current price to the mean analyst target."""
    if target is None or price is None:
        return None
    try:
        target, price = float(target), float(price)
    except (TypeError, ValueError):
        return None
    if price <= 0 or target <= 0:
        return None
    upside = (target - price) / price
    return clamp((upside - _UPSIDE_MIN) / (_UPSIDE_MAX - _UPSIDE_MIN))


def compute_catalyst_score(raw_doc: dict, feat_doc: dict) -> float:
    """
    Derive a catalyst score in [0, 1] from volume, news flow and analyst upside.

    Returns 0.5 when nothing is available. Partial data lands nearer neutral
    than complete data would, so the score never claims more evidence than it
    has.
    """
    sentiment = raw_doc.get("sentiment_raw") or {}
    fundamentals = raw_doc.get("fundamentals") or {}

    components: list[tuple[float, float]] = []

    volume = _volume_component(feat_doc.get("volume_anomaly"))
    if volume is not None:
        components.append((volume, _W_VOLUME))

    news = _news_component(sentiment.get("article_count"))
    if news is not None:
        components.append((news, _W_NEWS))

    upside = _upside_component(
        fundamentals.get("analyst_target_price"),
        feat_doc.get("current_price") or raw_doc.get("current_price"),
    )
    if upside is not None:
        components.append((upside, _W_UPSIDE))

    if not components:
        return 0.5

    # Coverage weighting — see _fundamental_score for the reasoning.
    coverage = sum(w for _, w in components)
    raw = sum(s * w for s, w in components) / coverage
    score = clamp(raw * coverage + 0.5 * (1.0 - coverage))

    logger.debug(
        "catalyst_score_computed",
        ticker=raw_doc.get("ticker"),
        volume=None if volume is None else round(volume, 4),
        news=None if news is None else round(news, 4),
        upside=None if upside is None else round(upside, 4),
        coverage=round(coverage, 4),
        score=round(score, 4),
    )
    return score
