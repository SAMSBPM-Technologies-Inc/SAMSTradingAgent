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

One exception, and only one: a ticker with a *completely empty* cache schedules
a detached background fetch (`_schedule_cold_start_backfill`). It still returns
the neutral stub to its caller — nothing is awaited — so the read stays
non-blocking. This fires once per ticker rather than once per read, and is
cooldown-guarded, so it cannot become the per-read fetching described above.

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
from app.db import (
    COLL_EARNINGS,
    COLL_FUNDAMENTALS_CACHE,
    COLL_STATEMENTS,
    get_db,
)
from app.services.fundamentals_providers import (
    fetch_alpha_earnings,
    fetch_alpha_vantage,
    fetch_massive,
    merge_fundamentals,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Cache of provider results, one document per ticker. Aliased from `app.db`
#: so the collection name lives in one place — the research route reads the
#: same collection for peer sector lookups.
COLL_FUNDAMENTALS = COLL_FUNDAMENTALS_CACHE

# `COLL_STATEMENTS` is imported from `app.db` rather than redeclared: the index
# that enforces one document per (ticker, period, timeframe) is created there,
# and a second copy of the name is how the two drift apart. That collection is
# separate from the snapshot above on purpose — the snapshot is replaced
# wholesale on every refresh, which is why no trend could ever be computed from
# it, while this one only ever gains rows, so a filing seen once stays seen.


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
        # Cold cache. Schedule a one-off background fetch so the *next* pipeline
        # run has real data, instead of waiting up to 24h for the daily job.
        # This run still scores neutral — the fetch is far too slow to block on.
        _schedule_cold_start_backfill(ticker)
        return {"ticker": ticker, "source": "pending"}

    # Served past its TTL rather than withheld. Quarterly figures a few days old
    # still carry real signal, and the alternative is the flat 0.5 that made the
    # BUY threshold unreachable in the first place.
    doc["stale"] = _age_hours(doc) > get_settings().fundamentals_cache_hours
    return doc


async def refresh_fundamentals(ticker: str, price: float | None = None,
                               use_alpha: bool = True,
                               use_alpha_earnings: bool = False) -> dict:
    """
    Fetch from the providers and write the cache. Slow by design — paced by the
    rate limiters in `fundamentals_providers`, so expect ~13s per provider call.

    `use_alpha=False` skips the OVERVIEW call and `use_alpha_earnings=False`
    skips the EARNINGS one, for when the shared daily budget is spent. Both
    default conservatively: the caller decides what a ticker is worth, because
    only the caller knows what the rest of the universe still needs.

    Returns the merged document, or the existing cached one if every provider
    failed.
    """
    ticker = ticker.upper()
    massive = await fetch_massive(ticker)
    alpha = await fetch_alpha_vantage(ticker) if use_alpha else {}
    if use_alpha_earnings:
        await refresh_earnings(ticker)

    statements = massive.pop("statements", None) or {}
    merged = merge_fundamentals(ticker, alpha, massive, price=price)
    # Folded in whether or not we just refreshed it — a week-old cached history
    # still carries the next report date, and that is the field the catalyst
    # score and the analyst prompt have been missing.
    await _merge_earnings_summary(ticker, merged)

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

    await _persist_statements(ticker, statements)

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
    summary = {"refreshed": 0, "with_alpha": 0, "with_earnings": 0, "failed": 0}
    spent = 0

    for ticker in tickers:
        # One shared budget across both Alpha Vantage call types, spent in
        # order rather than sliced up front. Counting actual calls beats the
        # old `i < budget` positional rule now that a ticker can cost one call
        # or two: earnings are only due about one day in seven, so a fixed
        # reservation would either starve the OVERVIEW pass or leave the
        # reservation unused on six days out of every seven.
        use_alpha = spent < budget
        if use_alpha:
            spent += 1
        do_earnings = False
        if spent < budget:
            do_earnings = await earnings_refresh_due(ticker)
            if do_earnings:
                spent += 1

        try:
            doc = await refresh_fundamentals(
                ticker, use_alpha=use_alpha, use_alpha_earnings=do_earnings
            )
            if do_earnings:
                summary["with_earnings"] += 1
            if doc.get("source") in ("none", "pending"):
                summary["failed"] += 1
                continue
            summary["refreshed"] += 1
            if "alphavantage" in (doc.get("source") or ""):
                summary["with_alpha"] += 1
        except Exception as exc:
            logger.warning("fundamentals_refresh_error", ticker=ticker, error=str(exc))
            summary["failed"] += 1

    logger.info("fundamentals_refresh_all_done", **summary,
                tickers=len(tickers), alpha_calls=spent, alpha_budget=budget)
    return summary


async def earnings_refresh_due(ticker: str) -> bool:
    """Whether *ticker*'s cached earnings history has earned an API call today."""
    return _earnings_refresh_due(await fetch_earnings(ticker))


#: Summary fields lifted out of the earnings document and folded into the
#: fundamentals snapshot, so the scorer and the analyst prompt see them without
#: a second collection read. `next_earnings_date` is the one that matters most:
#: it has been read by the prompt and rendered as N/A on every run since
#: yfinance was dropped, because nothing wrote it.
_EARNINGS_SUMMARY_FIELDS = (
    "next_earnings_date", "last_earnings_date", "last_reported_eps",
    "last_estimated_eps", "last_surprise_pct", "earnings_beat_rate",
    "earnings_beat_count", "earnings_quarters_scored", "avg_surprise_pct",
)


async def fetch_earnings(ticker: str) -> dict:
    """
    Return the cached earnings history for *ticker*, or {} when none exists.

    Cache-only, for the same reason `fetch_fundamentals` is: this costs an
    Alpha Vantage call against a daily cap the watchlist already exceeds, and a
    read path that fetches would spend the whole budget on the first pipeline
    cycle of the day.
    """
    ticker = ticker.upper()
    try:
        db = await get_db()
        return await db[COLL_EARNINGS].find_one({"ticker": ticker}, {"_id": 0}) or {}
    except Exception as exc:
        logger.warning("earnings_cache_read_failed", ticker=ticker, error=str(exc))
        return {}


def _earnings_refresh_due(doc: dict) -> bool:
    """
    Whether a cached earnings document has earned another API call.

    Two triggers, and the second is the interesting one. Age alone would spend
    a call on a company that is nowhere near reporting; the report-proximity
    trigger spends it exactly when the numbers are about to change, which is
    when a stale history is actually misleading rather than merely old.
    """
    if not doc:
        return True

    settings = get_settings()
    age_days = _age_hours(doc) / 24.0
    if age_days >= settings.alphavantage_earnings_cache_days:
        return True

    next_date = doc.get("next_earnings_date")
    if not next_date:
        return False
    try:
        due = datetime.fromisoformat(str(next_date)[:10]).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    days_out = (due - datetime.now(tz=timezone.utc)).total_seconds() / 86400.0
    # Includes dates already past: a report that has happened but is not yet in
    # our copy is the staleness worth paying to fix.
    return days_out <= settings.alphavantage_earnings_eager_days


async def refresh_earnings(ticker: str, force: bool = False) -> dict:
    """
    Refresh the earnings history if it is due, and return whatever we now hold.

    Returns the cached document untouched when not due, so a caller can call
    this per ticker per day without thinking about the budget. `force=True` is
    for the on-demand research path, where the user has explicitly asked.
    """
    ticker = ticker.upper()
    cached = await fetch_earnings(ticker)
    if not force and not _earnings_refresh_due(cached):
        return cached

    fetched = await fetch_alpha_earnings(ticker)
    if not fetched or fetched.get("alphavantage_rate_limited"):
        # Rate-limited or empty. Keep what we have — an earnings history that
        # is a week old beats none at all, and overwriting it with a gap would
        # take `next_earnings_date` back to the N/A this exists to fix.
        return cached

    try:
        db = await get_db()
        await db[COLL_EARNINGS].replace_one({"ticker": ticker}, fetched, upsert=True)
    except Exception as exc:
        logger.warning("earnings_cache_write_failed", ticker=ticker, error=str(exc))

    logger.info(
        "earnings_refreshed",
        ticker=ticker,
        next_report=fetched.get("next_earnings_date"),
        beat_rate=fetched.get("earnings_beat_rate"),
        quarters=len(fetched.get("quarterly_earnings") or []),
    )
    return fetched


async def _merge_earnings_summary(ticker: str, merged: dict) -> None:
    """Fold the cached earnings summary into the fundamentals snapshot, in place."""
    earnings = await fetch_earnings(ticker)
    for field in _EARNINGS_SUMMARY_FIELDS:
        value = earnings.get(field)
        if value is not None:
            merged[field] = value


async def _persist_statements(ticker: str, statements: dict) -> None:
    """
    Upsert each reporting period into `financial_statements`.

    Upsert per period rather than replace-the-ticker: restatements should
    update the period they belong to, and a provider that returns a shorter
    window one day must not delete history it simply did not mention. That is
    the failure the snapshot collection has — every refresh destroys the prior
    value, so ten years of filings can pass through the process and leave
    nothing behind.
    """
    rows = list(statements.get("annual") or []) + list(statements.get("quarterly") or [])
    if not rows:
        return

    try:
        db = await get_db()
        written = 0
        for row in rows:
            period_end = row.get("period_end")
            if not period_end:
                continue
            doc = dict(row)
            doc["ticker"] = ticker
            await db[COLL_STATEMENTS].replace_one(
                {
                    "ticker": ticker,
                    "period_end": period_end,
                    "timeframe": row.get("timeframe"),
                },
                doc,
                upsert=True,
            )
            written += 1
        logger.info("statements_persisted", ticker=ticker, periods=written)
    except Exception as exc:
        logger.warning("statements_write_failed", ticker=ticker, error=str(exc))


async def fetch_statements(ticker: str, timeframe: str = "annual",
                           limit: int = 12) -> list[dict]:
    """
    Read the accumulated statement series, newest period first.

    Cache-only, like `fetch_fundamentals` — the providers cannot take a read
    path and the research layer runs against whatever the daily job has built
    up. An empty list means "not collected yet", which callers must render as
    absent rather than as a company with no history.
    """
    ticker = ticker.upper()
    try:
        db = await get_db()
        cursor = (
            db[COLL_STATEMENTS]
            .find({"ticker": ticker, "timeframe": timeframe}, {"_id": 0})
            .sort("period_end", -1)
            .limit(limit)
        )
        return [row async for row in cursor]
    except Exception as exc:
        logger.warning("statements_read_failed", ticker=ticker, error=str(exc))
        return []


#: Tickers with a cold-start backfill currently running. Guards against the
#: 5-minute pipeline stacking a second fetch on top of one already in flight.
_backfill_inflight: set[str] = set()
#: Last attempt per ticker, so a symbol the providers simply do not cover is not
#: retried on every pipeline run for ever.
_backfill_attempted: dict[str, datetime] = {}
#: Strong references to running tasks. asyncio only holds weak ones, so a task
#: that is not referenced anywhere can be garbage-collected mid-flight.
_backfill_tasks: set = set()


def _schedule_cold_start_backfill(ticker: str) -> None:
    """
    Fire a one-off background fundamentals fetch for a ticker with no cache.

    Deliberately fire-and-forget. `refresh_fundamentals` takes ~13s per provider
    because of the rate limiters, and `fetch_fundamentals` is called inside the
    5-minute pipeline for every ticker — awaiting here would stall the whole
    cycle and is precisely the inline-fetch pattern that 429'd under yfinance.
    The caller still gets the neutral stub; the benefit lands on the next run.
    """
    settings = get_settings()
    if not settings.fundamentals_cold_start_backfill:
        return

    ticker = ticker.upper()
    if ticker in _backfill_inflight:
        return

    last = _backfill_attempted.get(ticker)
    cooldown = timedelta(minutes=settings.fundamentals_cold_start_retry_minutes)
    if last is not None and datetime.now(tz=timezone.utc) - last < cooldown:
        return

    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop (e.g. a synchronous unit test). Nothing to schedule onto.
        return

    _backfill_inflight.add(ticker)
    _backfill_attempted[ticker] = datetime.now(tz=timezone.utc)

    async def _run() -> None:
        try:
            logger.info("fundamentals_cold_start_backfill", ticker=ticker)
            await refresh_fundamentals(ticker)
        except Exception as exc:
            # Never propagate: this runs detached from any request.
            logger.warning(
                "fundamentals_cold_start_backfill_failed", ticker=ticker, error=str(exc)
            )
        finally:
            _backfill_inflight.discard(ticker)

    task = loop.create_task(_run())
    _backfill_tasks.add(task)
    task.add_done_callback(_backfill_tasks.discard)


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
