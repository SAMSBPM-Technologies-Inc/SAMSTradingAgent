"""
Fundamentals Service
────────────────────
Cache-first fundamentals, sourced from Massive (Polygon.io) and Alpha Vantage.

yfinance is deliberately not in the chain any more: it 429s consistently from
this host, so keeping it as a fallback only added latency before returning the
same nothing. One field is lost with it — `next_earnings_date`, which neither
replacement carries in these endpoints and which fed the analyst prompt.

**Reads never call an API.** Every provider here is limited to roughly 5
requests a minute, and Alpha Vantage to 25 a day, while the pipeline runs every
5 minutes across ~29 tickers. Fetching inline would either rate-limit instantly
or stall the pipeline; it is what produced the constant 429s under yfinance.
So `fetch_fundamentals` serves whatever is cached and `refresh_fundamentals`
repopulates it slowly in the background (see the daily scheduler job).

The consequence of getting this wrong is not an outage but a silent one: a
missing fundamentals doc scores 0.5 rather than raising, which is exactly how
fundamental_score came to be a flat 0.5 across every ticker while looking
healthy from the outside.

Fields returned (superset; any may be absent):
    Valuation  : pe_ratio, pb_ratio, ps_ratio, peg_ratio
    Size       : market_cap
    Earnings   : eps_ttm, revenue_growth_yoy, earnings_growth_yoy
    Health     : debt_to_equity, free_cash_flow, profit_margin, return_on_equity
    Analyst    : analyst_target_price, analyst_recommendation, analyst_count
    Context    : sector, industry
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import get_settings
from app.db import get_db
from app.services.fundamentals_providers import (
    fetch_alpha_vantage,
    fetch_massive,
    merge_fundamentals,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Cache of provider results, one document per ticker.
COLL_FUNDAMENTALS = "stocks_fundamentals"


async def fetch_fundamentals(ticker: str) -> dict:
    """
    Return the cached fundamentals for *ticker*, or a stub when none exists yet.

    Never performs a network call: the pipeline calls this every 5 minutes per
    ticker and the providers cannot sustain that. A cold cache returns a stub
    with `source: "pending"`, which scores as neutral until the background
    refresh fills it in.
    """
    ticker = ticker.upper()
    try:
        db = await get_db()
        doc = await db[COLL_FUNDAMENTALS].find_one({"ticker": ticker}, {"_id": 0})
    except Exception as exc:
        logger.warning("fundamentals_cache_read_failed", ticker=ticker, error=str(exc))
        return {"ticker": ticker, "source": "unavailable", "error": str(exc)}

    if not doc:
        return {"ticker": ticker, "source": "pending"}

    # Served past its TTL rather than withheld. Quarterly figures a few days old
    # still carry real signal, and the alternative is the flat 0.5 that made the
    # BUY threshold unreachable in the first place.
    doc["stale"] = _age_hours(doc) > get_settings().fundamentals_cache_hours
    return doc


async def refresh_fundamentals(ticker: str, price: float | None = None,
                               use_alpha: bool = True) -> dict:
    """
    Fetch from the providers and write the cache. Slow by design — paced by the
    rate limiters in `fundamentals_providers`, so expect ~13s per provider call.

    `use_alpha=False` skips Alpha Vantage, for when its daily budget is spent.
    Returns the merged document, or the existing cached one if every provider
    failed.
    """
    ticker = ticker.upper()
    massive = await fetch_massive(ticker)
    alpha = await fetch_alpha_vantage(ticker) if use_alpha else {}

    merged = merge_fundamentals(ticker, alpha, massive, price=price)

    if merged.get("source") == "none":
        # Every provider failed. Overwriting a good cached document with an
        # empty one would silently degrade the score, so keep what we have.
        existing = await fetch_fundamentals(ticker)
        if existing.get("source") not in ("pending", "unavailable"):
            logger.warning("fundamentals_refresh_failed_keeping_cache", ticker=ticker)
            return existing
        logger.warning("fundamentals_refresh_failed_no_cache", ticker=ticker)
        return merged

    try:
        db = await get_db()
        await db[COLL_FUNDAMENTALS].replace_one({"ticker": ticker}, merged, upsert=True)
    except Exception as exc:
        logger.warning("fundamentals_cache_write_failed", ticker=ticker, error=str(exc))

    logger.info(
        "fundamentals_refreshed",
        ticker=ticker, source=merged.get("source"),
        pe=merged.get("pe_ratio"), rev_growth=merged.get("revenue_growth_yoy"),
        rec=merged.get("analyst_recommendation"), de=merged.get("debt_to_equity"),
    )
    return merged


async def refresh_all_fundamentals(tickers: list[str]) -> dict:
    """
    Refresh a whole universe, respecting both rate limits.

    Alpha Vantage's daily allowance is smaller than the watchlist, so it is
    spent on the tickers listed first and the rest fall back to Massive alone —
    which still covers revenue growth, debt/equity and free cash flow, i.e. 70%
    of the fundamental score's weight. Callers should therefore pass the
    tickers that matter most (held positions, watchlist) at the front.
    """
    settings = get_settings()
    budget = settings.alphavantage_daily_budget
    summary = {"refreshed": 0, "with_alpha": 0, "failed": 0}

    for i, ticker in enumerate(tickers):
        use_alpha = i < budget
        try:
            doc = await refresh_fundamentals(ticker, use_alpha=use_alpha)
            if doc.get("source") in ("none", "pending"):
                summary["failed"] += 1
                continue
            summary["refreshed"] += 1
            if "alphavantage" in (doc.get("source") or ""):
                summary["with_alpha"] += 1
        except Exception as exc:
            logger.warning("fundamentals_refresh_error", ticker=ticker, error=str(exc))
            summary["failed"] += 1

    logger.info("fundamentals_refresh_all_done", **summary, tickers=len(tickers))
    return summary


def _age_hours(doc: dict) -> float:
    raw = doc.get("fetched_at")
    if not raw:
        return 1e9
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 1e9
    return (datetime.now(tz=timezone.utc) - ts).total_seconds() / 3600.0
