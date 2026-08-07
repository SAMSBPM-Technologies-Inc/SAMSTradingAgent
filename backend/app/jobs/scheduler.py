"""
Background Job Scheduler
────────────────────────
Uses APScheduler to run the full analysis pipeline on a cron interval.

Schedule:
  - Every INGESTION_INTERVAL_MINUTES minutes → run pipeline for all DEFAULT_TICKERS

The scheduler is started/stopped alongside the FastAPI lifespan.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.services.pipeline import run_pipeline_all
from app.utils.logger import get_logger

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Return the singleton scheduler instance (creates it if needed)."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


async def _pipeline_job() -> None:
    """Async job: run the full pipeline for all configured tickers."""
    settings = get_settings()
    tickers = settings.ticker_list
    logger.info("scheduled_pipeline_start", tickers=tickers)
    results = await run_pipeline_all(tickers)
    logger.info("scheduled_pipeline_done", results=results)


def start_scheduler() -> None:
    """Register jobs and start the scheduler. Call once at app startup."""
    settings = get_settings()
    scheduler = get_scheduler()

    # Defer the first run by one interval so startup isn't hammered immediately
    first_run = datetime.now(tz=timezone.utc) + timedelta(minutes=settings.ingestion_interval_minutes)

    scheduler.add_job(
        _pipeline_job,
        trigger=IntervalTrigger(minutes=settings.ingestion_interval_minutes),
        id="full_pipeline",
        name="Full analysis pipeline",
        replace_existing=True,
        max_instances=1,          # prevent overlapping runs
        misfire_grace_time=60,    # allow 60s slip before skipping
        next_run_time=first_run,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        interval_minutes=settings.ingestion_interval_minutes,
        tickers=settings.ticker_list,
    )


def stop_scheduler() -> None:
    """Stop the scheduler gracefully. Call at app shutdown."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
