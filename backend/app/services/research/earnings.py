"""
Earnings evidence — what was expected, what was delivered, and what is next.

This is the only place in the system that carries an *expectation*. Everything
else describes what happened: a margin, a price, a cash flow. The spec this was
built against asks the model to compare what management expected, what
happened, what changed, what the market expected, and what happens next — and
without an estimate series, four of those five questions have no data behind
them at all.

What is reachable here is the second and fourth: reported EPS against the
consensus estimate, quarter by quarter, plus the announced date of the next
report. Guidance and earnings-call commentary are not available from this
provider, so "what management expected" and "what management said" remain out of
reach and are declared as gaps rather than inferred from the numbers.
"""
from __future__ import annotations

from typing import Optional

from app.services.research.evidence import Ledger
from app.services.research.formatting import pct, ratio

_SOURCE = "Alpha Vantage EARNINGS"

#: Quarters spelled out individually. Two years is long enough to read as a
#: record rather than a mood, and short enough that a company which has changed
#: shape is not judged on what it was a decade ago.
_DETAIL_QUARTERS = 8


def build(ledger: Ledger, earnings: dict, fundamentals: dict) -> dict:
    """Add earnings evidence and return a summary of the record."""
    quarterly = earnings.get("quarterly_earnings") or []
    annual = earnings.get("annual_earnings") or []
    as_of = str(earnings.get("fetched_at") or "")[:10] or None

    def add(claim: str, value, item_as_of: Optional[str] = None,
            meta: bool = False) -> None:
        ledger.add("E", claim, value, _SOURCE, as_of=item_as_of or as_of, meta=meta)

    if not quarterly and not annual:
        # Said out loud rather than left silent. An agent that sees no earnings
        # section cannot distinguish "this company has never missed" from "we
        # have no estimate data", and the two support opposite conclusions.
        add("Earnings history",
            "Not available — no estimate-versus-actual data collected for this ticker",
            meta=True)
        return {"quarters": 0, "has_next_date": False}

    next_date = earnings.get("next_earnings_date") or fundamentals.get("next_earnings_date")
    if next_date:
        add("Next scheduled earnings report", next_date)
    else:
        add("Next scheduled earnings report", "Not announced in the collected data",
            meta=True)

    add("Beat rate, last 8 reported quarters", _beat_rate(earnings))
    add("Average surprise, last 8 reported quarters",
        ratio(earnings.get("avg_surprise_pct"), digits=1, suffix="%"))

    settled = [row for row in quarterly if row.get("reported_eps") is not None]
    for row in settled[:_DETAIL_QUARTERS]:
        period = row.get("fiscal_date_ending")
        reported = row.get("reported_eps")
        estimated = row.get("estimated_eps")
        if estimated is None:
            add(f"Reported EPS, quarter ending {period}", ratio(reported),
                item_as_of=row.get("reported_date") or period)
            continue
        verdict = _verdict(reported, estimated)
        surprise = row.get("surprise_pct")
        surprise_text = f", {surprise:+.1f}% surprise" if surprise is not None else ""
        add(
            f"EPS versus estimate, quarter ending {period}",
            f"reported {reported:.2f} vs estimate {estimated:.2f} — {verdict}{surprise_text}",
            item_as_of=row.get("reported_date") or period,
        )

    for row in annual[:5]:
        add(f"Annual reported EPS, year ending {row['fiscal_date_ending']}",
            ratio(row.get("reported_eps")), item_as_of=row.get("fiscal_date_ending"))

    _declare_gaps(add)

    return {
        "quarters": len(settled),
        "has_next_date": bool(next_date),
        "beat_rate": earnings.get("earnings_beat_rate"),
    }


def _verdict(reported: float, estimated: float) -> str:
    """
    Beat, miss, or in line.

    "In line" is a real third state, not a rounding of the other two: a penny
    against a two-dollar estimate is noise, and calling it a beat is how a
    company with an unremarkable record acquires a streak.
    """
    if estimated == 0:
        return "beat" if reported > 0 else "missed"
    delta = (reported - estimated) / abs(estimated)
    if delta > 0.01:
        return "beat"
    if delta < -0.01:
        return "missed"
    return "in line"


def _beat_rate(earnings: dict) -> Optional[str]:
    rate = earnings.get("earnings_beat_rate")
    if rate is None:
        return None
    beats = earnings.get("earnings_beat_count")
    scored = earnings.get("earnings_quarters_scored")
    if beats is not None and scored:
        return f"{pct(rate, digits=0)} ({beats} of {scored})"
    return pct(rate, digits=0)


def _declare_gaps(add) -> None:
    """
    Name what this section cannot answer.

    Stated as evidence so it is visible to the agents rather than only to
    whoever reads this file. A model told the earnings data covers estimates
    and actuals only will not write about guidance; a model shown an earnings
    section with no boundary marked may fill the silence.
    """
    add("Earnings data coverage",
        "Estimate-versus-actual and report dates only. Management guidance, "
        "earnings-call transcripts and analyst estimate revisions are not "
        "available from this provider and must not be inferred",
        meta=True)
