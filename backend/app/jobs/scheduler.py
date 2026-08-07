"""
Background Job Scheduler
────────────────────────
Three scheduled jobs:

  1. market_pipeline  — runs the full analysis pipeline every N minutes,
                        but ONLY during US market hours (9:30–16:00 ET, Mon-Fri).
                        Covers all DEFAULT_TICKERS + any user-added watched tickers.

  2. premarket_sweep  — runs at 08:00 ET every weekday (before market open)
                        to refresh news sentiment and macro data so signals
                        are fresh at the open.

  3. perf_tracker     — runs at 06:00 UTC daily. Finds historical signal records
                        that are ≥20 trading days old and have no realized return,
                        fetches the current price, and records the outcome so the
                        /performance endpoint can compute signal accuracy.

The scheduler is started/stopped with the FastAPI lifespan.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db import COLL_SIGNAL_HISTORY, COLL_WATCHED, get_db
from app.services.pipeline import run_pipeline_all
from app.utils.logger import get_logger

logger = get_logger(__name__)

ET = ZoneInfo("America/New_York")
_scheduler: AsyncIOScheduler | None = None

# Approximate trading days elapsed (used to decide when to settle history)
_SETTLE_TRADING_DAYS = 20
_SETTLE_CALENDAR_DAYS = 30   # ~20 trading days ≈ 30 calendar days


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    """Return True if the NYSE is currently open (approximate)."""
    now = datetime.now(tz=ET)
    if now.weekday() >= 5:   # Saturday=5, Sunday=6
        return False
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now <= market_close


async def _get_all_tickers() -> list[str]:
    """Merge config DEFAULT_TICKERS with user-added watched tickers."""
    settings = get_settings()
    tickers = set(settings.ticker_list)
    try:
        db = await get_db()
        watched = await db[COLL_WATCHED].find({}, {"ticker": 1}).to_list(length=500)
        tickers.update(d["ticker"] for d in watched)
    except Exception as exc:
        logger.warning("watched_tickers_fetch_failed", error=str(exc))
    return sorted(tickers)


# ── Job functions ─────────────────────────────────────────────────────────────

async def _market_pipeline_job() -> None:
    """Full pipeline — only runs during market hours."""
    if not _is_market_hours():
        logger.debug("pipeline_skipped_outside_market_hours")
        return
    tickers = await _get_all_tickers()
    logger.info("scheduled_pipeline_start", tickers=tickers)
    results = await run_pipeline_all(tickers)
    logger.info("scheduled_pipeline_done", results=results)


async def _premarket_sweep_job() -> None:
    """Pre-market sweep: full pipeline run before the open (refreshes news + macro)."""
    tickers = await _get_all_tickers()
    logger.info("premarket_sweep_start", tickers=tickers)
    results = await run_pipeline_all(tickers)
    logger.info("premarket_sweep_done", results=results)


async def _performance_tracker_job() -> None:
    """
    Settle historical signal records that are ≥20 trading days old.
    Fetches latest price from Yahoo Finance and records the realized return.
    """
    try:
        db = await get_db()
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_SETTLE_CALENDAR_DAYS)

        unsettled = await db[COLL_SIGNAL_HISTORY].find({
            "generated_at": {"$lte": cutoff},
            "return_20d": None,
            "price_at_signal": {"$ne": None},
        }).to_list(length=500)

        if not unsettled:
            logger.debug("perf_tracker_nothing_to_settle")
            return

        logger.info("perf_tracker_start", records=len(unsettled))

        # Batch by ticker to minimise fetch calls
        from collections import defaultdict
        by_ticker: dict[str, list] = defaultdict(list)
        for rec in unsettled:
            by_ticker[rec["ticker"]].append(rec)

        for ticker, records in by_ticker.items():
            try:
                current_price = await _fetch_current_price(ticker)
                if current_price is None:
                    continue
                for rec in records:
                    entry_price = rec["price_at_signal"]
                    ret = (current_price - entry_price) / entry_price
                    signal = rec.get("signal", "HOLD")
                    # "correct" = direction of return matches signal
                    was_correct: bool | None = None
                    if signal == "BUY":
                        was_correct = ret > 0
                    elif signal == "SELL":
                        was_correct = ret < 0
                    # HOLD is not directional — leave None

                    await db[COLL_SIGNAL_HISTORY].update_one(
                        {"_id": rec["_id"]},
                        {"$set": {
                            "price_20d_later": round(current_price, 4),
                            "return_20d":      round(ret, 6),
                            "was_correct":     was_correct,
                        }},
                    )
            except Exception as exc:
                logger.warning("perf_tracker_ticker_failed", ticker=ticker, error=str(exc))

        logger.info("perf_tracker_done", settled=len(unsettled))
    except Exception as exc:
        logger.error("perf_tracker_error", error=str(exc))


async def _fetch_current_price(ticker: str) -> float | None:
    """Fetch the latest close price from Yahoo Finance."""
    import requests
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        result = resp.json().get("chart", {}).get("result", [])
        if not result:
            return None
        adj = result[0].get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
        closes = [c for c in adj if c is not None]
        return float(closes[-1]) if closes else None
    except Exception:
        return None


# ── Startup / shutdown ────────────────────────────────────────────────────────

def start_scheduler() -> None:
    settings = get_settings()
    scheduler = get_scheduler()

    # 1. Market-hours pipeline (interval, conditional on market hours)
    first_run = datetime.now(tz=timezone.utc) + timedelta(minutes=settings.ingestion_interval_minutes)
    scheduler.add_job(
        _market_pipeline_job,
        trigger=IntervalTrigger(minutes=settings.ingestion_interval_minutes),
        id="market_pipeline",
        name="Full analysis pipeline (market hours only)",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
        next_run_time=first_run,
    )

    # 2. Pre-market sweep — 08:00 ET Mon–Fri
    scheduler.add_job(
        _premarket_sweep_job,
        trigger=CronTrigger(hour=8, minute=0, day_of_week="mon-fri", timezone=ET),
        id="premarket_sweep",
        name="Pre-market news & macro sweep",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # 3. Performance tracker — 06:00 UTC daily
    scheduler.add_job(
        _performance_tracker_job,
        trigger=CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="perf_tracker",
        name="Signal performance tracker",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        interval_minutes=settings.ingestion_interval_minutes,
        tickers=settings.ticker_list,
        jobs=["market_pipeline", "premarket_sweep (08:00 ET)", "perf_tracker (06:00 UTC)"],
    )


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
