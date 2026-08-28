"""
Social evidence — what holders are saying (prefix `S`).

Counts, not conclusions. No item here says retail is bullish or bearish; each
says how many messages there were, how many carried a direction, and what the
split was, with the window and the source attached. That distinction is the
whole design: message boards are promoted, brigaded and botted, and a
"sentiment score" computed from them would launder that noise into a number an
agent would then reason from as though it were a measurement.

What an agent can legitimately do with these is notice a *change* — chatter
that has tripled against a quiet news tape is a fact about positioning — and
cite the count that shows it. What it cannot do is claim a crowd view, because
no item asserts one.

Absence stays absent. A board with nothing to say and a board that could not be
reached are both simply missing here; `Ledger.add` refuses a None, so neither
gets an id an agent could cite.
"""
from __future__ import annotations

from typing import Optional

from app.services.research.evidence import Ledger

_SOURCE_ST = "StockTwits public stream"
_SOURCE_RD = "Reddit search (r/stocks, r/investing, r/wallstreetbets, r/SecurityAnalysis)"


def build(ledger: Ledger, social: Optional[dict]) -> dict:
    """Add social evidence and return a coverage summary."""
    if not social or not social.get("enabled"):
        return {"available": False, "reason": "collection disabled"}

    stocktwits = social.get("stocktwits")
    reddit = social.get("reddit")
    added = 0

    if stocktwits:
        as_of = stocktwits.get("as_of")
        window = stocktwits.get("window_days")

        def add_st(claim: str, value, meta: bool = False) -> None:
            nonlocal added
            if ledger.add("S", claim, value, _SOURCE_ST, as_of=as_of, meta=meta):
                added += 1

        add_st(f"StockTwits messages in the last {window} days",
               stocktwits.get("messages"))
        add_st("Of those, messages the author tagged with a direction",
               stocktwits.get("tagged"))
        add_st("Tagged bullish", stocktwits.get("bullish"))
        add_st("Tagged bearish", stocktwits.get("bearish"))
        share = stocktwits.get("bull_share")
        if share is not None:
            add_st("Share of tagged messages that were bullish",
                   f"{share:.0%} — a self-reported tag on a public board, not a "
                   f"survey and not a position")
        else:
            # Meta: this describes our data, not the company. An agent needs to
            # see the boundary or it will read the raw counts as a direction.
            add_st("Directional split", "no message carried a direction tag", meta=True)
    else:
        ledger.add("S", "StockTwits", "no data collected for this ticker",
                   _SOURCE_ST, meta=True)

    if reddit:
        as_of = reddit.get("as_of")
        window = reddit.get("window_days")

        def add_rd(claim: str, value, meta: bool = False) -> None:
            nonlocal added
            if ledger.add("S", claim, value, _SOURCE_RD, as_of=as_of, meta=meta):
                added += 1

        add_rd(f"Reddit posts mentioning this ticker in the last {window} days",
               reddit.get("posts"))
        add_rd("Total upvote score across those posts", reddit.get("total_score"))
        add_rd("Total comments across those posts", reddit.get("total_comments"))
        subs = reddit.get("subreddits") or {}
        if subs:
            add_rd("Where those posts appeared",
                   ", ".join(f"r/{name} ({count})" for name, count in subs.items()))
    else:
        ledger.add("S", "Reddit", "no posts found in the window", _SOURCE_RD,
                   meta=True)

    return {
        "available": added > 0,
        "stocktwits": bool(stocktwits),
        "reddit": bool(reddit),
        "items": added,
    }
