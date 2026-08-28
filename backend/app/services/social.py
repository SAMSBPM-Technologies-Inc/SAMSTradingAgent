"""
Retail Sentiment — StockTwits and Reddit
────────────────────────────────────────
What non-professional holders are saying, and how many of them are saying it.

The engine already reads news sentiment (Finnhub headlines through VADER),
which is a measure of what *publishers* wrote. That is a different quantity
from what holders think, and the gap between the two is occasionally the whole
story — a name whose coverage is neutral and whose retail chatter has tripled
in a week is in a different state from one where both are quiet.

Three things about this data are true and shape every decision below.

**It is noisy to the point of being adversarial.** Message boards are promoted,
brigaded and botted. Nothing here is admitted as a *judgement* — no "retail is
bullish" verdict is computed. What enters the ledger is counts and ratios with
their source and window attached, so an agent reading them can say "chatter has
risen sharply [S2]" and cannot say "retail likes this" without the evidence
supporting it.

**It must not touch the composite score.** Adding a factor would change every
published signal and invalidate the settled history the calibration work
depends on. This feeds the research ledger only.

**Neither source is contractually available.** StockTwits' public endpoint is
undocumented and rate-limited without notice; Reddit's JSON endpoints require a
descriptive User-Agent and throttle aggressively. Both are development-grade,
exactly as `price_providers.py` says of the Yahoo path — and both fail to
`None`, never to a fabricated neutral reading.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
_REDDIT_SEARCH = "https://www.reddit.com/search.json"
_TIMEOUT = 10.0

#: Reddit rejects a generic agent outright. Descriptive and honest about what
#: this is — spoofing a browser here would be the same mistake the Yahoo price
#: path is criticised for in `price_providers.py`.
_UA = "SAMSTradingAgent/1.0 (research dossier evidence collection)"

#: Subreddits worth reading for equities. Deliberately short: breadth here buys
#: noise, not signal.
_SUBREDDITS = ("stocks", "investing", "wallstreetbets", "SecurityAnalysis")

#: How far back a mention counts. Matches the news window so the two sentiment
#: readings in a dossier describe the same period.
_WINDOW_DAYS = 7


async def fetch_stocktwits(ticker: str) -> Optional[dict]:
    """
    Recent StockTwits messages for a ticker, reduced to counts.

    Returns None on any failure. A silent source and a source with nothing to
    say are different facts, and this cannot tell them apart — so it reports
    neither rather than inventing the second.
    """
    url = _STOCKTWITS_URL.format(symbol=ticker.upper())
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers={"User-Agent": _UA})
            if resp.status_code == 404:
                # The symbol is not covered. Distinct from an outage, and worth
                # logging differently, but the caller sees the same absence.
                logger.info("stocktwits_symbol_unknown", ticker=ticker)
                return None
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("stocktwits_fetch_failed", ticker=ticker, error=str(exc))
        return None

    messages = payload.get("messages") or []
    if not messages:
        return None

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_WINDOW_DAYS)
    bullish = bearish = tagged = recent = 0
    for message in messages:
        created = _parse_time(message.get("created_at"))
        if created is not None and created < cutoff:
            continue
        recent += 1
        # Only messages the author explicitly tagged are counted. Inferring a
        # direction from the text would be this module producing a judgement,
        # which is exactly what it must not do.
        basic = ((message.get("entities") or {}).get("sentiment") or {}).get("basic")
        if basic == "Bullish":
            bullish += 1
            tagged += 1
        elif basic == "Bearish":
            bearish += 1
            tagged += 1

    if recent == 0:
        return None

    return {
        "source": "StockTwits",
        "window_days": _WINDOW_DAYS,
        "messages": recent,
        "tagged": tagged,
        "bullish": bullish,
        "bearish": bearish,
        # None rather than 0.5 when nobody tagged a direction. A ratio computed
        # from an empty denominator is not a neutral reading, it is no reading.
        "bull_share": round(bullish / tagged, 3) if tagged else None,
        "as_of": datetime.now(tz=timezone.utc).date().isoformat(),
    }


async def fetch_reddit(ticker: str) -> Optional[dict]:
    """
    Mention volume and engagement for a ticker across a few equity subreddits.

    Counts and scores only — no sentiment is inferred. Reddit's own score is
    already a crowd measure and does not need a language model's opinion layered
    on top of it.
    """
    query = f"${ticker.upper()} OR {ticker.upper()}"
    params = {
        "q": query,
        "restrict_sr": "false",
        "sort": "new",
        "t": "week",
        "limit": "100",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_REDDIT_SEARCH, params=params,
                                    headers={"User-Agent": _UA})
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.warning("reddit_fetch_failed", ticker=ticker, error=str(exc))
        return None

    children = ((payload.get("data") or {}).get("children")) or []
    if not children:
        return None

    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=_WINDOW_DAYS)).timestamp()
    posts = 0
    total_score = 0
    total_comments = 0
    subs: dict[str, int] = {}
    for child in children:
        data = child.get("data") or {}
        subreddit = str(data.get("subreddit") or "")
        if subreddit.lower() not in {s.lower() for s in _SUBREDDITS}:
            continue
        created = data.get("created_utc")
        if isinstance(created, (int, float)) and created < cutoff:
            continue
        posts += 1
        total_score += int(data.get("score") or 0)
        total_comments += int(data.get("num_comments") or 0)
        subs[subreddit] = subs.get(subreddit, 0) + 1

    if posts == 0:
        return None

    return {
        "source": "Reddit",
        "window_days": _WINDOW_DAYS,
        "posts": posts,
        "total_score": total_score,
        "total_comments": total_comments,
        "median_score": round(total_score / posts, 1),
        "subreddits": dict(sorted(subs.items(), key=lambda kv: -kv[1])),
        "as_of": datetime.now(tz=timezone.utc).date().isoformat(),
    }


async def fetch_social(ticker: str) -> dict:
    """
    Both sources at once, each independently optional.

    Concurrent because they are unrelated, and `return_exceptions=True` because
    one board being down must not cost the other's reading.
    """
    if not get_settings().social_sentiment_enabled:
        return {"stocktwits": None, "reddit": None, "enabled": False}

    results = await asyncio.gather(
        fetch_stocktwits(ticker), fetch_reddit(ticker), return_exceptions=True
    )
    stocktwits, reddit = [None if isinstance(r, BaseException) else r for r in results]
    return {"stocktwits": stocktwits, "reddit": reddit, "enabled": True}


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
