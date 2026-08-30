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

Three weighted components, chosen because each is genuinely forward-looking and
none is already priced elsewhere in the model, plus one additive modifier:

    Volume anomaly     40 %      something is happening now
    News flow          30 %      attention is arriving
    Analyst upside     30 %      the street expects repricing
    Earnings proximity +0.10 max a known repricing event, on a known date

`buzz` and `analyst_target_price` were both already being fetched and stored,
and neither was read by any scorer. Insider activity and options flow were
deliberately NOT included despite being available: `alternative_data_score`
already prices both, and importing them here would recreate exactly the
double-count that was just removed from volatility.

Earnings proximity was absent for a data reason, not an oversight, and that
reason has now gone: `next_earnings_date` is supplied by the Alpha Vantage
EARNINGS endpoint and folded into the fundamentals snapshot.

It is an **additive bonus, not a fourth weighted component**, and the
difference matters. As a weighted component its absence would cost coverage,
and coverage is a penalty — so every ticker whose earnings date we do not have
would be pulled toward neutral relative to one we do. Alpha Vantage's daily cap
is smaller than the watchlist, so that is a permanent split in the universe:
covered tickers would score on a wider range than uncovered ones for a reason
that has nothing to do with either company. As a bonus, an unknown date and a
report two months out both add nothing, which is exactly right — neither is a
catalyst — and only genuine proximity moves the score. This mirrors how
`scoring.py` treats alternative data, for the same reason.

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
from datetime import datetime, timezone
from typing import Optional

from app.utils.helpers import clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Component weights. Volume leads because it is the only one that reflects
#: something happening *right now* rather than something expected.
_W_VOLUME  = 0.40
_W_NEWS    = 0.30
_W_UPSIDE  = 0.30

#: Ceiling on the earnings-proximity bonus, added on top of the weighted score
#: rather than mixed into it. Bounded deliberately: an imminent report is a
#: reason to expect movement, not a reason to expect movement *upward*, and the
#: catalyst factor feeds a directional composite.
_W_EARNINGS_BONUS = 0.10

#: Earnings-proximity curve, in calendar days to the next report. A report two
#: months out is not a catalyst; one next week is the single most reliable
#: volatility event a scheduled equity has. Past the report the score falls back
#: to neutral rather than to zero — the aftermath is genuinely uncertain, not
#: genuinely quiet.
_EARNINGS_IMMINENT_DAYS = 7      # within a week → 1.0
_EARNINGS_HORIZON_DAYS  = 45     # beyond this → no signal

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


#: Sentiment `source` values that mean the headline count was never observed.
#:
#: The neutral stub `news.py` returns on these carries `article_count: 0`, which
#: is indistinguishable at this layer from a real week in which Finnhub answered
#: and there was genuinely nothing. The two must not be scored alike: silence
#: that was *measured* is evidence, and silence that means "we never looked" is
#: the absence of evidence. `no_articles` is deliberately NOT in this set — that
#: is Finnhub answering with zero, which is the measured case.
_UNOBSERVED_NEWS_SOURCES = frozenset({"no_api_key", "error", "exception"})


def _news_component(article_count: Optional[int]) -> Optional[float]:
    """
    News flow as an attention proxy, independent of whether the news is good.

    Direction is sentiment's job; this asks only whether the market is paying
    unusual attention. Three articles over the lookback is an ordinary week for
    a covered name, so that sits at neutral; ten or more is a story.

    `None` means the count was not observed, and the caller drops the component
    rather than scoring it — see `_UNOBSERVED_NEWS_SOURCES`.
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


def _earnings_component(next_earnings_date: Optional[str]) -> Optional[float]:
    """
    Nearness of the next scheduled earnings report, as a 0–1 signal.

    Returns None when no date is known. The caller treats that the same as a
    distant report — no bonus — because neither is a catalyst, and unlike a
    weighted component this cannot penalise a ticker for data we simply have
    not fetched yet.

    A date already in the past is also None. Alpha Vantage lists the next
    report before it happens, so a stale past date means our copy has not
    caught up — and scoring the catalyst off a report that already happened is
    worse than scoring nothing.
    """
    if not next_earnings_date:
        return None
    try:
        due = datetime.fromisoformat(str(next_earnings_date)[:10]).replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None

    days = (due - datetime.now(tz=timezone.utc)).total_seconds() / 86400.0
    if days < 0:
        return None
    if days <= _EARNINGS_IMMINENT_DAYS:
        return 1.0
    if days >= _EARNINGS_HORIZON_DAYS:
        return 0.0
    span = _EARNINGS_HORIZON_DAYS - _EARNINGS_IMMINENT_DAYS
    return clamp(1.0 - (days - _EARNINGS_IMMINENT_DAYS) / span)


def compute_catalyst_score(raw_doc: dict, feat_doc: dict) -> float:
    """The catalyst score alone — see `compute_catalyst` for its coverage."""
    return compute_catalyst(raw_doc, feat_doc)[0]


def compute_catalyst(raw_doc: dict, feat_doc: dict) -> tuple[float, float]:
    """
    Derive a catalyst score in [0, 1] from volume, news flow and analyst upside.

    Returns `(score, coverage)`. Coverage is the share of the factor's inputs
    that were actually measured; it was computed here from the first version
    and thrown away, which meant a score pulled toward neutral by *thin data*
    and one pulled there by *mixed evidence* were the same number to every
    reader. It is now reported so the two can be told apart.

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

    # A missing Finnhub key must not read as a quiet tape. The neutral stub
    # `news.py` returns carries `article_count: 0`, and 0 articles scores 0.40
    # here — so an absent key did not merely neutralise the sentiment factor,
    # it fed a mild negative into 30% of this one and dragged the composite
    # down. An unconfigured provider is not a bearish fact about the company.
    # Dropping the component instead lets coverage weighting pull the score
    # toward 0.5, which is what "we do not know" is supposed to look like.
    news_observed = sentiment.get("source") not in _UNOBSERVED_NEWS_SOURCES
    news = _news_component(sentiment.get("article_count") if news_observed else None)
    if news is not None:
        components.append((news, _W_NEWS))

    upside = _upside_component(
        fundamentals.get("analyst_target_price"),
        feat_doc.get("current_price") or raw_doc.get("current_price"),
    )
    if upside is not None:
        components.append((upside, _W_UPSIDE))

    if not components:
        return 0.5, 0.0

    # Coverage weighting — see _fundamental_score for the reasoning.
    coverage = sum(w for _, w in components)
    raw = sum(s * w for s, w in components) / coverage
    score = clamp(raw * coverage + 0.5 * (1.0 - coverage))

    # Applied after coverage weighting, so a known report date lifts the score
    # without an unknown one dragging it. `None` and "45 days out" both add
    # zero here, which is the whole point — see the module docstring.
    earnings = _earnings_component(fundamentals.get("next_earnings_date"))
    if earnings:
        score = clamp(score + _W_EARNINGS_BONUS * earnings)

    logger.debug(
        "catalyst_score_computed",
        ticker=raw_doc.get("ticker"),
        volume=None if volume is None else round(volume, 4),
        earnings=None if earnings is None else round(earnings, 4),
        news=None if news is None else round(news, 4),
        upside=None if upside is None else round(upside, 4),
        coverage=round(coverage, 4),
        score=round(score, 4),
    )
    return score, coverage
