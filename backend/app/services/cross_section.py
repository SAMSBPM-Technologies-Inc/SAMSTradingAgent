"""
Cross-Section
─────────────
Where a ticker's score sits *relative to the rest of the watchlist*, rather than
against an absolute cutoff.

Why this exists
───────────────
The composite is a convex combination of six sub-scores that each sit near 0.5,
and three separate mechanisms push it back toward the middle:

  * **Coverage weighting.** `_fundamental_score`, `compute_catalyst` and
    `news.score_headlines` all end in `raw * coverage + 0.5 * (1 - coverage)`.
    That is the right way to report thin evidence and it shrinks the field.
  * **Macro is common-mode.** Fed funds, CPI and VIX are identical for every
    ticker, so 0.15 of the weight moves the whole field together and can never
    separate one name from another.
  * **Volatility is 0.00**, correctly — it is priced at the risk gate. So only
    about 0.65 of the weight ranks anything at all, and that 0.65 is itself
    shrunk toward neutral.

Work a near-best case through the default weights — technical 0.80, a
full-coverage fundamental 0.92, sentiment 0.70, a neutral macro 0.50, catalyst
0.65 on a 2x volume day — and the composite is 0.747 against a BUY threshold of
0.70. A typical name is 0.567. The recorded history says the same thing out
loud: 592 of 602 signals were HOLD.

An absolute cutoff on a distribution that narrow is arbitrary. It is set in
score units, but what it actually selects for is *how much data happened to be
available* — and it moves the whole watchlist in and out of range together
whenever the macro reading shifts, for reasons that have nothing to do with any
of the companies.

A percentile does not have that problem. "Is this one of the better things I am
watching" is the question a swing trader actually asks, it is invariant to the
common-mode shift, and it does not need re-tuning as coverage improves.

The floor is not optional
─────────────────────────
A rank on its own always fires. Somebody is always in the top quintile, so a
pure ranking rule buys the least-bad name in a uniformly terrible field, every
day, forever. `signal_generator` therefore requires **both** a rank and an
absolute level — `RANK_BUY_FLOOR` — and the floor is the part that can say
"nothing here is worth owning". The rank decides *which*; the floor decides
*whether*.

The cohort
──────────
Every ticker the engine scores on the cycle: config's `DEFAULT_TICKERS` plus
the union of every user's watchlist, which is exactly what `market_pipeline`
runs. Scores are read from `stocks_features`, where `score_ticker` has just
written this ticker's own — so a name is always ranked against a fresh copy of
itself and peers that are at most one cycle (five minutes) old.

That staleness is deliberate rather than tolerated. Ranking every ticker
against a complete same-cycle snapshot would mean scoring the whole universe
before classifying any of it, which splits `run_pipeline` in half and changes
the order in which alerts, stability and trades happen. A five-minute-old peer
score is a much smaller error than that restructure is a risk.

Ties rank pessimistically
─────────────────────────
`percentile_rank` counts how many of the cohort this score is *strictly* above.
Three tickers all at 0.60 therefore each rank 0.0, not 0.5 — so a flat field
produces no BUY at all. Given the compression described above, a field that
looks flat usually is one, and the honest reading of "these are
indistinguishable" is that none of them is the better opportunity.
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Sequence

from app.config import get_settings
from app.db import COLL_FEATURES, COLL_WATCHED, get_db
from app.utils.helpers import utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: How stale a peer's score may be and still count toward the cohort. The
#: pipeline runs every five minutes during market hours, so anything much older
#: than a couple of cycles is a ticker that has been failing to ingest — and a
#: name that cannot be scored should not be quietly setting the bar for one
#: that can. Generous rather than tight: the cost of dropping a live peer is a
#: smaller cohort, which `RANK_MIN_COHORT` already guards.
_MAX_COHORT_AGE = timedelta(minutes=30)

__all__ = ["Cohort", "percentile_rank", "cohort_for", "universe"]


@dataclass(frozen=True)
class Cohort:
    """
    One ticker's standing in the field it was scored alongside.

    Passed to `classify_signal` as a whole rather than as two loose floats, so
    that "there is no cohort" is a single `None` the caller cannot half-supply.
    """

    #: Share of the rest of the cohort this score is strictly above, 0–1.
    percentile: float
    #: How many tickers were ranked, this one included.
    size: int


def percentile_rank(score: float, cohort: Sequence[float]) -> Optional[float]:
    """
    Where *score* sits in *cohort*, as the fraction it is strictly above.

    `cohort` includes *score* itself — it is the whole field, not the peers —
    so the denominator is `len(cohort) - 1`.

    Returns None for a cohort of fewer than two, where there is no field to
    rank against and any number would be an invention. Callers treat None the
    same way they treat a missing cohort: fall back to the absolute rule.

    Ties are counted pessimistically (strictly-above, not above-or-equal), so a
    field of identical scores ranks every member at 0.0. See the module
    docstring for why that is the wanted behaviour rather than an edge case to
    smooth over.
    """
    if len(cohort) < 2:
        return None
    below = sum(1 for peer in cohort if peer < score)
    return below / (len(cohort) - 1)


async def universe() -> list[str]:
    """
    Every ticker the engine scores: configured defaults plus every watchlist.

    This is the cohort a percentile is measured in, and it is also exactly what
    `market_pipeline` iterates — the scheduler's `_get_all_tickers` delegates
    here so the two cannot drift. If they did, a ticker could be scored on one
    cycle and ranked against a field it was not part of.

    A database failure degrades to the configured list rather than raising: the
    caller's fallback for a thin cohort is the absolute rule, which is where a
    ranking failure should land anyway.
    """
    settings = get_settings()
    tickers = set(settings.ticker_list)
    try:
        db = await get_db()
        watched = await db[COLL_WATCHED].find({}, {"ticker": 1}).to_list(length=2000)
        tickers.update(d["ticker"] for d in watched)
    except Exception as exc:
        logger.warning("cohort_universe_fetch_failed", error=str(exc))
    return sorted(tickers)


async def cohort_for(ticker: str, score: float) -> Optional[Cohort]:
    """
    Rank *score* against the current field, or None if it cannot be ranked.

    Returns None — meaning "use the absolute rule" — on every uncertain path:
    ranking switched off, an unreadable database, a field too small or too
    stale to say anything. This is the same fail-open instinct as
    `_research_veto`: a ranking that cannot be computed must fall back to the
    rule that was already there, never halt or invent a verdict. The one
    difference is that falling back here is *stricter*, not looser, since the
    absolute rule is the harder bar to clear.

    `score` is passed in rather than re-read, because the caller has just
    computed it and the stored copy may be a rounded version of the same
    number.
    """
    settings = get_settings()
    if not settings.enable_rank_signals:
        return None

    try:
        tickers = await universe()
        db = await get_db()
        cutoff = utcnow() - _MAX_COHORT_AGE
        docs = await db[COLL_FEATURES].find(
            {"ticker": {"$in": tickers}},
            {"ticker": 1, "composite_score": 1, "computed_at": 1},
        ).to_list(length=2000)
    except Exception as exc:
        logger.warning("cohort_read_failed", ticker=ticker, error=str(exc))
        return None

    scores: list[float] = []
    for doc in docs:
        value = doc.get("composite_score")
        if not isinstance(value, (int, float)):
            continue
        if doc.get("ticker") == ticker:
            # This ticker's own score comes from the caller, not from the copy
            # on disk — same number, but the caller's is unrounded and is what
            # the verdict will be classified from.
            continue
        computed_at = doc.get("computed_at")
        if computed_at is not None and _aware(computed_at) < cutoff:
            # A ticker that has not been scored in half an hour is failing to
            # ingest. It must not set the bar for one that is working.
            continue
        scores.append(float(value))

    scores.append(float(score))
    percentile = percentile_rank(float(score), scores)
    if percentile is None:
        return None

    return Cohort(percentile=round(percentile, 4), size=len(scores))


def _aware(value):
    """
    Normalise a Mongo datetime to UTC-aware.

    Motor hands back naive datetimes for values written as aware ones, and
    comparing a naive against an aware raises — inside the pipeline that would
    be swallowed and every cohort would silently come back None. Same fix, same
    reason, as `signal_stability._aware`.
    """
    from datetime import datetime, timezone

    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
