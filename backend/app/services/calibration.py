"""
Threshold Calibration
─────────────────────
Reads settled signal history and asks the question the engine has never asked
itself: **were the thresholds in the right place?**

Every pipeline run writes to `stocks_signal_history`, and the scheduler settles
each record with `return_20d` about twenty trading days later. Nothing consumed
either. The evidence needed to place BUY_THRESHOLD empirically was being
collected and thrown away, while the threshold stayed where it was originally
guessed.

This module reports; it does not tune. Auto-fitting a threshold to its own
history is how a system talks itself into whatever the last few months
happened to reward, and with a few hundred records the noise is larger than the
signal. The output is evidence for a human decision.

Three questions, each answerable from the same records:

  score_buckets       Does a higher score actually earn a higher return? If the
                      curve is flat, the composite is not ranking anything and
                      no threshold placement will help.
  threshold_sweep     What would BUY at each candidate cutoff have returned?
  confidence_buckets  Does stated confidence track being right? Confidence is
                      computed as distance from the decision boundary and has
                      never been checked against outcomes.

Every result carries `n`. With fewer than ~30 settled records in a bucket the
numbers are anecdote — `MIN_SAMPLES_FOR_SIGNAL` marks that line and the API
surfaces it rather than hiding it behind a confident-looking percentage.
"""
from statistics import median
from typing import Any, Iterable, Optional, Sequence

from app.db import COLL_SIGNAL_HISTORY, get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Below this, a bucket's win rate is noise. Not a hard filter — the caller
#: still sees the row, flagged — because "we have no evidence here" is itself
#: worth knowing.
MIN_SAMPLES_FOR_SIGNAL = 30

#: Default score bucket edges. Deliberately spans the whole range rather than
#: clustering near 0.70: if scores never reach the upper buckets, that is the
#: finding.
DEFAULT_SCORE_EDGES: tuple[float, ...] = (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0)

#: Candidate BUY cutoffs to sweep. 0.70 is the incumbent.
DEFAULT_THRESHOLDS: tuple[float, ...] = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)


def _settled(records: Iterable[dict]) -> list[dict]:
    """Records whose 20-day outcome is known. Anything else cannot inform this."""
    return [
        r for r in records
        if isinstance(r.get("return_20d"), (int, float))
        and isinstance(r.get("score"), (int, float))
    ]


def _stats(returns: Sequence[float]) -> dict[str, Any]:
    """Win rate and central tendency for one group of realised returns."""
    n = len(returns)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_return": None,
                "median_return": None, "significant": False}
    wins = sum(1 for r in returns if r > 0)
    return {
        "n": n,
        "win_rate": round(wins / n, 4),
        "avg_return": round(sum(returns) / n, 6),
        "median_return": round(median(returns), 6),
        "significant": n >= MIN_SAMPLES_FOR_SIGNAL,
    }


def score_buckets(
    records: Iterable[dict],
    edges: Sequence[float] = DEFAULT_SCORE_EDGES,
) -> list[dict]:
    """
    Realised outcome per score band.

    This is the first thing to look at. A composite that ranks well produces
    returns that rise with the bucket; a flat or non-monotonic curve means the
    score is not separating winners from losers, and moving the BUY threshold
    around would only be choosing a different arbitrary point on a flat line.
    """
    rows = _settled(records)
    out: list[dict] = []
    for lo, hi in zip(edges, edges[1:]):
        # Upper edge inclusive only in the final bucket, so 1.0 is not dropped.
        last = hi == edges[-1]
        group = [
            r["return_20d"] for r in rows
            if lo <= r["score"] < hi or (last and r["score"] == hi)
        ]
        out.append({"lo": lo, "hi": hi, **_stats(group)})
    return out


def threshold_sweep(
    records: Iterable[dict],
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
    risk_max: Optional[float] = None,
) -> list[dict]:
    """
    What a BUY at each candidate cutoff would have returned.

    `risk_max` applies the risk veto as well, but only to records that stored a
    risk score — history did not carry one until this module was written, so
    older rows are score-only and `risk_coverage` reports what fraction of the
    sample the veto could actually be applied to. Reading a sweep with low
    coverage as if it modelled the real gate would overstate it.
    """
    rows = _settled(records)
    with_risk = [r for r in rows if isinstance(r.get("risk_score"), (int, float))]
    coverage = round(len(with_risk) / len(rows), 4) if rows else 0.0

    out: list[dict] = []
    for t in thresholds:
        selected = []
        for r in rows:
            if r["score"] <= t:
                continue
            if risk_max is not None:
                rs = r.get("risk_score")
                if isinstance(rs, (int, float)) and rs >= risk_max:
                    continue
            selected.append(r["return_20d"])
        out.append({
            "threshold": t,
            "risk_filtered": risk_max is not None,
            "risk_coverage": coverage,
            **_stats(selected),
        })
    return out


def confidence_buckets(records: Iterable[dict], bins: int = 5) -> list[dict]:
    """
    Does stated confidence track being right?

    Confidence is distance from the decision boundary, which is not a hit rate
    and has never been compared to one. If win rate does not rise across these
    bands, the number is presentation rather than information — worth knowing
    before it is shown to anyone as though it means something.
    """
    rows = [r for r in _settled(records)
            if isinstance(r.get("confidence"), (int, float))]
    out: list[dict] = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        last = i == bins - 1
        group = [
            r["return_20d"] for r in rows
            if lo <= r["confidence"] < hi or (last and r["confidence"] == 1.0)
        ]
        out.append({"lo": round(lo, 4), "hi": round(hi, 4), **_stats(group)})
    return out


def summarise(records: Iterable[dict], risk_max: Optional[float] = None) -> dict:
    """Everything above, plus the base rate the buckets should be judged against."""
    rows = _settled(records)
    base = _stats([r["return_20d"] for r in rows])
    buckets = score_buckets(rows)

    # Does return rise with score? Compared across buckets that actually have
    # enough data to say — a monotonic run of three-sample buckets means nothing.
    usable = [b for b in buckets if b["significant"] and b["avg_return"] is not None]
    monotonic = (
        all(a["avg_return"] <= b["avg_return"] for a, b in zip(usable, usable[1:]))
        if len(usable) >= 2 else None
    )

    return {
        "settled_records": len(rows),
        "base_rate": base,
        "score_buckets": buckets,
        "score_ranks_outcomes": monotonic,
        "usable_buckets": len(usable),
        "threshold_sweep": threshold_sweep(rows, risk_max=risk_max),
        "confidence_buckets": confidence_buckets(rows),
        "min_samples_for_signal": MIN_SAMPLES_FOR_SIGNAL,
    }


async def calibration_report(
    ticker: Optional[str] = None,
    risk_max: Optional[float] = None,
) -> dict:
    """Load settled history from MongoDB and summarise it."""
    db = await get_db()
    query: dict[str, Any] = {"return_20d": {"$ne": None}}
    if ticker:
        query["ticker"] = ticker.upper()

    records = await db[COLL_SIGNAL_HISTORY].find(
        query,
        {"ticker": 1, "score": 1, "signal": 1, "confidence": 1,
         "risk_score": 1, "return_20d": 1, "generated_at": 1},
    ).to_list(length=100_000)

    report = summarise(records, risk_max=risk_max)
    report["ticker"] = ticker.upper() if ticker else None
    logger.info(
        "calibration_report",
        ticker=ticker or "ALL",
        settled=report["settled_records"],
        ranks=report["score_ranks_outcomes"],
    )
    return report
