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
from app.db import COLL_SIGNAL_HISTORY, COLL_SIGNALS, COLL_USERS, COLL_WATCHED, get_db
from app.services.entitlements import ENROLABLE_TIERS, entitlements_for
from app.services import source_health
from app.services.benchmark import (
    alpha, benchmark_closes, benchmark_ticker, close_on_or_before,
)
from app.services.pipeline import run_pipeline_all
from app.utils.helpers import is_market_hours
from app.utils.logger import get_logger

logger = get_logger(__name__)

ET = ZoneInfo("America/New_York")
_scheduler: AsyncIOScheduler | None = None

# Approximate trading days elapsed (used to decide when to settle history)
_SETTLE_TRADING_DAYS = 20
_SETTLE_CALENDAR_DAYS = 28   # 28 calendar days reliably covers ≥20 trading days


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    """Return True if the NYSE is currently open (approximate)."""
    # Imported, not restated. The status page judges cycle staleness against
    # the same clock, and two copies of a market calendar is how they end up
    # disagreeing about whether a quiet Sunday is an outage.
    return is_market_hours()


def _is_reconcile_window() -> bool:
    """
    Market hours plus a tail past the close.

    The tail matters: an order working at 16:00 can still fill or cancel in the
    after-hours flush, and a stop that triggers near the bell prints after it.
    Stopping dead at the close would leave those trades looking open until the
    next session.
    """
    now = datetime.now(tz=ET)
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=9,  minute=25, second=0, microsecond=0)
    end   = now.replace(hour=16, minute=45, second=0, microsecond=0)
    return start <= now <= end


async def _get_all_tickers() -> list[str]:
    """
    Merge config DEFAULT_TICKERS with all users' watched tickers.

    Delegates to `cross_section.universe`, which needs the identical list: it
    is the cohort a percentile is measured in, and a ticker scored on this
    cycle but absent from that cohort would be ranked against a field it was
    not part of. Two copies of this query is precisely how that happens.
    """
    from app.services.cross_section import universe
    return await universe()


async def _research_users() -> list[tuple[str, list[str]]]:
    """
    Users who have opted into research, each with their own watchlist.

    Three properties matter and all three are cost controls. Research is five to
    seven model calls per ticker per day; multiplied across users it is the one
    number in this system that can run away, so the job reaches nobody who has
    not asked for it — `research_enabled` defaults false and stays false until
    a user turns it on, at which point they are spending their own key.

    And each user gets *their* watchlist rather than the union: building a
    dossier on a ticker somebody else watches spends one trader's key on
    another trader's name.

    The third is the plan. `research_enabled` may have been set *before* a
    downgrade — the route check only covers the moment of writing, and the admin
    route clears the flag on a downgrade, so this is the belt to that brace.

    **`$in` over the enrolable tiers, never `$ne: "BASIC"`.** `$ne` also matches
    documents where the field is *absent*, which is every account predating
    `db._migrate_access_tier` — so a failed migration plus a `$ne` filter would
    enrol everybody rather than nobody. One operator's worth of difference
    between cost contained and cost inverted.

    The tier gets us to the candidates; `entitlements_for` makes the final call,
    because a PRO account needs an explicit admin grant on top of its tier and
    that rule lives in the table, not here.
    """
    try:
        db = await get_db()
        users = await db[COLL_USERS].find(
            {
                "llm_settings.research_enabled": True,
                "access_tier": {"$in": ENROLABLE_TIERS},
            },
            {"_id": 1, "access_tier": 1, "email": 1, "research_daily_allowed": 1},
        ).to_list(length=1000)
    except Exception as exc:
        logger.warning("research_users_fetch_failed", error=str(exc))
        return []

    out: list[tuple[str, list[str]]] = []
    for user in users:
        if not entitlements_for(user).may_enrol_in_nightly_research:
            continue
        user_id = str(user["_id"])
        try:
            db = await get_db()
            watched = await db[COLL_WATCHED].find(
                {"user_id": user_id}, {"ticker": 1},
            ).to_list(length=2000)
        except Exception as exc:
            logger.warning("research_user_watchlist_failed",
                           user_id=user_id, error=str(exc))
            continue
        tickers = sorted({d["ticker"] for d in watched})
        if tickers:
            out.append((user_id, tickers))
    return out


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


async def _reconcile_trades_job() -> None:
    """
    Sync local trade records with the broker's view of orders and positions.

    Runs far more often than the pipeline: a fill or a triggered stop is a fact
    about money already committed, and until it is recorded the position count,
    the duplicate-entry guard, and the daily-loss kill switch are all working
    from stale data.
    """
    if not _is_reconcile_window():
        return
    try:
        from app.services.trade_manager import reconcile_trades
        await reconcile_trades()
    except Exception as exc:
        logger.error("reconcile_trades_job_failed", error=str(exc))


async def _fundamentals_refresh_job() -> None:
    """
    Repopulate the fundamentals cache.

    Runs pre-market and slowly: the providers allow ~5 requests a minute, so a
    30-ticker universe takes roughly 15 minutes of mostly waiting. That is why
    it is a separate job rather than part of the pipeline — the pipeline runs
    every 5 minutes and cannot block on this.

    Tickers with an open position are refreshed first, because Alpha Vantage's
    daily allowance (25) is smaller than the watchlist and runs out partway
    through; the ones that miss out still get Massive's statements, which cover
    most of the fundamental score's weight.
    """
    try:
        from app.services.fundamentals import refresh_all_fundamentals

        tickers = await _get_all_tickers()
        if not tickers:
            return

        # Prioritise held names — those are the ones carrying money.
        ordered = await _held_first(tickers)
        logger.info("fundamentals_refresh_start", tickers=len(ordered))
        await refresh_all_fundamentals(ordered)
    except Exception as exc:
        logger.error("fundamentals_refresh_job_failed", error=str(exc))


async def _research_refresh_job() -> None:
    """
    Rebuild research dossiers for the watchlist, once a day.

    Runs well after the fundamentals refresh, and that ordering is load-bearing
    rather than tidy: a dossier is assembled entirely from cached provider data,
    so building one before the cache is warm produces a report about yesterday.

    Sequential on purpose. Each dossier is five model calls that are themselves
    internally concurrent, and running several tickers at once would multiply
    that into a burst against the API for no benefit — nothing is waiting on
    this job. Held positions go first: if the run is cut short, the names
    carrying money are the ones already done.

    Every failure is swallowed per ticker. One symbol with no collected
    statements must not stop the rest of the universe from being researched.
    """
    settings = get_settings()
    if not settings.research_agents_enabled:
        return

    try:
        from app.services.research.dossier import build_dossier

        cohort = await _research_users()
        if not cohort:
            logger.info("research_refresh_no_opted_in_users")
            # Said on the row rather than left as silence. `llm_settings.
            # research_enabled` defaults false, so a server with
            # RESEARCH_AGENTS_ENABLED=true and nobody opted in builds nothing —
            # and the status page cannot tell that from an outage, because both
            # look like an absence of readings. It is a setting, not a fault.
            await source_health.record_attempt(
                "research", source_health.NOT_CONFIGURED,
                detail="Switched on for this server, but no account has enabled "
                       "research in its LLM settings, so no dossiers are built.",
            )
            return

        built = failed = 0
        for user_id, tickers in cohort:
            ordered = await _held_first(tickers)
            watchlist = await _watchlist_sectors(ordered)
            for ticker in ordered:
                try:
                    dossier = await build_dossier(
                        ticker, user_id=user_id, watchlist=watchlist,
                    )
                    if dossier:
                        built += 1
                    else:
                        failed += 1
                except Exception as exc:
                    failed += 1
                    logger.warning("research_refresh_ticker_failed",
                                   user_id=user_id, ticker=ticker, error=str(exc))

        logger.info("research_refresh_done", built=built, skipped=failed,
                    users=len(cohort))
        if not built and failed:
            # Every ticker was skipped. `build_dossier` records nothing for a
            # skip — each one on its own is a data condition — but a whole run
            # producing no dossier is a state a reader needs told, and it is not
            # the same as never having run.
            await source_health.record_attempt(
                "research", source_health.DEGRADED, succeeded=False,
                detail=f"The last run built no dossier for any of {failed} "
                       f"tickers — not enough collected evidence yet.",
            )
    except Exception as exc:
        logger.error("research_refresh_job_failed", error=str(exc))


async def _research_outcomes_job() -> None:
    """
    Grade dossiers old enough to have an outcome, once a day.

    This is the half of the loop that did not exist. Dossiers were written as a
    retained series and read one at a time, newest first — no reading was ever
    compared to a result, so no agent had been told it was wrong about a name
    and `RESEARCH_VETO_MIN_CONVICTION` sat at a guessed number with no evidence
    behind it.

    Runs *before* the refresh rather than after, and the ordering is
    load-bearing: a dossier built today should be able to cite the grade
    yesterday's dossier just received. Reversed, every reading would carry a
    record one day out of date, forever.

    Failures are per-dossier and swallowed inside `settle_dossiers`. An
    unsettled dossier is simply one the next pass picks up.
    """
    settings = get_settings()
    if not settings.research_agents_enabled:
        return
    try:
        from app.services.research.outcomes import settle_dossiers

        # Per user, for the same reason the refresh is: the reflection is a
        # model call on that user's key, grading that user's reading.
        for user_id, _tickers in await _research_users():
            try:
                await settle_dossiers(user_id=user_id)
            except Exception as exc:
                logger.warning("research_outcomes_user_failed",
                               user_id=user_id, error=str(exc))
    except Exception as exc:
        logger.error("research_outcomes_job_failed", error=str(exc))


async def _held_first(tickers: list[str]) -> list[str]:
    """Order a ticker list so open positions come first."""
    held: set[str] = set()
    try:
        db = await get_db()
        from app.models.trade import TradeStatus

        async for trade in db["trades"].find(
            {"status": {"$in": list(TradeStatus.OPEN)}, "closed_at": None},
            {"ticker": 1},
        ):
            held.add(str(trade.get("ticker", "")).upper())
    except Exception as exc:
        logger.warning("held_lookup_failed", error=str(exc))
    return [t for t in tickers if t in held] + [t for t in tickers if t not in held]


async def _watchlist_sectors(tickers: list[str]) -> list[dict]:
    """Sector and industry per ticker, for the dossier's peer set."""
    try:
        from app.db import COLL_FUNDAMENTALS_CACHE

        db = await get_db()
        return await db[COLL_FUNDAMENTALS_CACHE].find(
            {"ticker": {"$in": tickers}},
            {"ticker": 1, "sector": 1, "industry": 1, "_id": 0},
        ).to_list(length=500)
    except Exception as exc:
        logger.warning("watchlist_sector_lookup_failed", error=str(exc))
        return []


async def _premarket_sweep_job() -> None:
    """Pre-market sweep: full pipeline run before the open (refreshes news + macro)."""
    tickers = await _get_all_tickers()
    logger.info("premarket_sweep_start", tickers=tickers)
    results = await run_pipeline_all(tickers)
    logger.info("premarket_sweep_done", results=results)


# ── Broker connectivity watch ─────────────────────────────────────────────────
#
# A dead broker session is silent: scoring continues, the UI works, and orders
# are simply refused. You find out when you try to trade, which is the worst
# moment to discover it. This is the alert that would have caught the Monday
# morning outage before market open.

#: When the session was first seen down, or None while it is healthy. Process
#: state deliberately — a restart re-arms the alert, which is the safe
#: direction: better a duplicate notification than a silent outage.
#:
#: The *observed* state is separately written to `system_health` so the status
#: page can still answer "is the broker up" after a deploy. Recording a fact
#: and arming an alert are different jobs, and only the second one wants to
#: forget on restart.
_broker_down_since: datetime | None = None
#: Set once per outage so a long one does not notify every five minutes.
_broker_alert_sent = False


async def _broker_watch_job() -> None:
    """Alert when the broker has been disconnected longer than the threshold."""
    global _broker_down_since, _broker_alert_sent

    try:
        settings = get_settings()
        if not settings.auto_trade_enabled:
            return  # No broker expected; nothing to watch.

        from app.services import broker as ibkr

        now = datetime.now(tz=timezone.utc)

        if ibkr.is_connected():
            if _broker_alert_sent and _broker_down_since is not None:
                minutes = int((now - _broker_down_since).total_seconds() // 60)
                await _notify_broker(down_minutes=minutes, recovered=True)
                logger.info("broker_recovered", down_minutes=minutes)
            _broker_down_since = None
            _broker_alert_sent = False
            await source_health.record_subsystem(
                "broker", source_health.OK, last_success_at=now, down_since=None,
            )
            return

        await source_health.record_subsystem(
            "broker", source_health.FAILED,
            down_since=_broker_down_since or now,
            last_error="Broker session not connected",
        )

        if _broker_down_since is None:
            _broker_down_since = now
            logger.warning("broker_disconnected_observed")
            return

        minutes = int((now - _broker_down_since).total_seconds() // 60)
        # Threshold sits above the reconnect loop's 300s ceiling, so a blip the
        # loop recovers from on its own never pages anyone.
        if minutes >= settings.broker_alert_after_minutes and not _broker_alert_sent:
            await _notify_broker(down_minutes=minutes, recovered=False)
            _broker_alert_sent = True
            logger.error("broker_down_alert_sent", down_minutes=minutes)

    except Exception as exc:
        logger.error("broker_watch_job_failed", error=str(exc))


async def _notify_broker(*, down_minutes: int, recovered: bool) -> None:
    """Fan a broker alert out to every user with a channel configured."""
    from app.services.notifier import send_broker_alert

    settings = get_settings()
    db = await get_db()
    users = await db[COLL_USERS].find(
        {"$or": [
            {"alert_settings.slack_webhook_url": {"$exists": True, "$ne": None}},
            {"alert_settings.whatsapp_phone": {"$exists": True, "$ne": None}},
        ]},
    ).to_list(length=2000)

    mode = "live" if settings.is_live_trading else "paper"
    for user in users:
        prefs = user.get("alert_settings") or {}
        try:
            await send_broker_alert(
                prefs.get("slack_webhook_url"),
                down_minutes=down_minutes,
                recovered=recovered,
                trading_mode=mode,
                whatsapp_phone=prefs.get("whatsapp_phone"),
                whatsapp_apikey=prefs.get("whatsapp_apikey"),
            )
        except Exception as exc:
            logger.warning("broker_alert_send_failed", user_id=str(user.get("_id")), error=str(exc))


# ── Capability watch ──────────────────────────────────────────────────────────
#
# The same idea as the broker watch, applied to the data sources. A dead FRED is
# quieter than a dead broker: the broker at least refuses orders, while a failed
# macro fetch simply pins one factor to 0.50 and lets every verdict publish
# looking exactly as it always did.

#: The last state each capability was *reported* in, so only a change is news.
#: Process state, like the broker watch above and for the same reason: a restart
#: re-arms, which risks one duplicate notification rather than a silent outage.
_capability_states: dict[str, str] = {}

#: How many consecutive cycles a capability must stay down before it is worth
#: waking someone for. The pipeline runs every 5 minutes, so two readings is
#: roughly ten minutes — long enough that a single transient 429 on one cycle,
#: which the next cycle recovers from, never reaches a phone.
_DEGRADED_CONFIRMATIONS = 2


async def _capability_watch_job() -> None:
    """
    Notify when a data source degrades or recovers. Transitions only.

    Three rules keep this from becoming noise:

      * **Only changes are sent.** A source that has been failing for six hours
        is not news six hours later; it was news once.
      * **Only confirmed failures.** A capability must be down for
        `_DEGRADED_CONFIRMATIONS` consecutive readings, the same instinct as the
        signal stability layer — one bad cycle is not a condition.
      * **Never about configuration.** A key you chose not to set is settled
        fact, not an event, and a channel that pages about it gets muted.
    """
    try:
        from app.services import source_health, system_status

        settings = get_settings()
        health = await source_health.read_all()
        status = system_status.build_status(settings, health)

        degraded: list[tuple[str, str]] = []
        recovered: list[str] = []

        for row in status["capabilities"]:
            state = row["state"]
            # Configuration is not an event. Neither is a source nothing has
            # reached yet — that is a fresh deployment, not a failure.
            if state in ("not_configured", "never_run"):
                _capability_states.pop(row["id"], None)
                continue

            # Neither is a failure that cannot change a number. Options and
            # insider flow is unkeyed best-effort scraping feeding an additive
            # modifier centred on neutral, so a notification about it asks the
            # reader to act on something with no consequence — and a channel
            # that does that gets muted before the one that matters arrives.
            # Same judgement as the banner; see `Capability.alters_scores`.
            if not system_status.alters_scores(row["id"]):
                _capability_states.pop(row["id"], None)
                continue

            unhealthy = state in ("failed", "degraded")
            confirmed = (
                row["consecutive_failures"] >= _DEGRADED_CONFIRMATIONS
                if state == "failed" else unhealthy
            )
            previous = _capability_states.get(row["id"], "ok")

            if confirmed and previous == "ok":
                degraded.append((row["label"], row["impact"]))
                _capability_states[row["id"]] = state
            elif not unhealthy and previous != "ok":
                recovered.append(row["label"])
                _capability_states[row["id"]] = "ok"

        if not degraded and not recovered:
            return

        await _notify_capabilities(
            degraded=degraded, recovered=recovered, summary=status["summary"],
        )
        logger.warning(
            "capability_alert_sent",
            degraded=[label for label, _impact in degraded], recovered=recovered,
        )
    except Exception as exc:
        logger.error("capability_watch_job_failed", error=str(exc))


async def _notify_capabilities(
    *, degraded: list[tuple[str, str]], recovered: list[str], summary: str,
) -> None:
    """Fan a capability alert out to every user who wants one."""
    from app.services.notifier import send_capability_alert

    db = await get_db()
    users = await db[COLL_USERS].find(
        {"$or": [
            {"alert_settings.slack_webhook_url": {"$exists": True, "$ne": None}},
            {"alert_settings.whatsapp_phone": {"$exists": True, "$ne": None}},
        ]},
    ).to_list(length=2000)

    for user in users:
        prefs = user.get("alert_settings") or {}
        if not prefs.get("notify_on_degraded", True):
            continue
        try:
            await send_capability_alert(
                prefs.get("slack_webhook_url"),
                degraded=degraded, recovered=recovered, summary=summary,
                whatsapp_phone=prefs.get("whatsapp_phone"),
                whatsapp_apikey=prefs.get("whatsapp_apikey"),
            )
        except Exception as exc:
            logger.warning(
                "capability_alert_send_failed",
                user_id=str(user.get("_id")), error=str(exc),
            )


async def _daily_digest_job() -> None:
    """
    Send a morning watchlist digest to all users who have opted in and configured a Slack webhook.
    Runs at 09:00 ET on weekdays (just before market open).
    """
    try:
        db = await get_db()
        users = await db[COLL_USERS].find(
            {"alert_settings.daily_digest": True, "$or": [
                {"alert_settings.slack_webhook_url": {"$exists": True, "$ne": None}},
                {"alert_settings.whatsapp_phone": {"$exists": True, "$ne": None}},
            ]},
        ).to_list(length=2000)

        if not users:
            logger.debug("daily_digest_no_recipients")
            return

        logger.info("daily_digest_start", recipients=len(users))
        from bson import ObjectId
        from app.services.notifier import send_daily_digest

        for user in users:
            try:
                prefs = user.get("alert_settings") or {}
                webhook = prefs.get("slack_webhook_url")
                wa_phone = prefs.get("whatsapp_phone")
                wa_apikey = prefs.get("whatsapp_apikey")
                if not webhook and not (wa_phone and wa_apikey):
                    continue

                user_id = str(user["_id"])
                watched = await db[COLL_WATCHED].find({"user_id": user_id}, {"ticker": 1}).to_list(length=2000)
                tickers = [d["ticker"] for d in watched]
                if not tickers:
                    continue

                signal_docs = await db[COLL_SIGNALS].find(
                    {"ticker": {"$in": tickers}},
                    {"ticker": 1, "signal": 1, "score": 1, "analyst_output": 1},
                ).to_list(length=2000)

                signals = []
                for doc in signal_docs:
                    ao = doc.get("analyst_output") or {}
                    signals.append({
                        "ticker": doc["ticker"],
                        "signal": doc.get("signal", "HOLD"),
                        "score": doc.get("score", 0.0),
                        "conviction": ao.get("conviction"),
                    })
                signals.sort(key=lambda x: x.get("score", 0), reverse=True)

                await send_daily_digest(
                    webhook_url=webhook,
                    display_name=user.get("display_name", ""),
                    signals=signals,
                    whatsapp_phone=wa_phone,
                    whatsapp_apikey=wa_apikey,
                )
            except Exception as exc:
                logger.warning("daily_digest_user_failed", user_id=str(user.get("_id")), error=str(exc))

        logger.info("daily_digest_done", recipients=len(users))
    except Exception as exc:
        logger.error("daily_digest_error", error=str(exc))


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
        }).to_list(length=2000)

        if not unsettled:
            logger.debug("perf_tracker_nothing_to_settle")
            return

        logger.info("perf_tracker_start", records=len(unsettled))

        # Batch by ticker to minimise fetch calls
        from collections import defaultdict
        by_ticker: dict[str, list] = defaultdict(list)
        for rec in unsettled:
            by_ticker[rec["ticker"]].append(rec)

        # One series for the whole pass. Every record below is settled to *now*,
        # so they all share the closing end of the window and differ only in
        # where it opened — which is a lookup, not a fetch.
        settled_at = datetime.now(tz=timezone.utc)
        bench_series = await benchmark_closes()
        bench_close_now = (
            close_on_or_before(bench_series, settled_at) if bench_series is not None else None
        )

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

                    # The benchmark over this record's own window. Both stay
                    # None when the series could not be read: a zero here would
                    # report the signal's full return as alpha, and would do it
                    # in the flattering direction every time the market rose.
                    bench_ret: float | None = None
                    if bench_close_now is not None and bench_series is not None:
                        opened = rec.get("generated_at")
                        bench_open = (
                            close_on_or_before(bench_series, opened)
                            if isinstance(opened, datetime) else None
                        )
                        if bench_open:
                            bench_ret = (bench_close_now - bench_open) / bench_open
                    excess = alpha(ret, bench_ret)

                    await db[COLL_SIGNAL_HISTORY].update_one(
                        {"_id": rec["_id"]},
                        {"$set": {
                            "price_20d_later": round(current_price, 4),
                            "return_20d":      round(ret, 6),
                            "was_correct":     was_correct,
                            "benchmark_ticker":     benchmark_ticker(),
                            "benchmark_return_20d": (
                                round(bench_ret, 6) if bench_ret is not None else None
                            ),
                            "alpha_20d": round(excess, 6) if excess is not None else None,
                        }},
                    )
            except Exception as exc:
                logger.warning("perf_tracker_ticker_failed", ticker=ticker, error=str(exc))

        logger.info("perf_tracker_done", settled=len(unsettled))
    except Exception as exc:
        logger.error("perf_tracker_error", error=str(exc))


async def _fetch_current_price(ticker: str) -> float | None:
    """Fetch the latest close price from Yahoo Finance (async, non-blocking)."""
    import httpx
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
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

    # 1b. Trade reconciliation — every 2 min inside the reconcile window.
    #     Deliberately independent of the pipeline interval: fills need to be
    #     observed promptly, and the pipeline is far too slow and too expensive
    #     to run at this cadence.
    scheduler.add_job(
        _reconcile_trades_job,
        trigger=IntervalTrigger(minutes=2),
        id="reconcile_trades",
        name="Broker trade reconciliation",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    # 1c. Fundamentals refresh — 07:00 ET Mon–Fri, an hour before the sweep so
    #     the cache is warm before signals are computed against it. Deliberately
    #     daily: these figures change quarterly, and the providers' rate limits
    #     make anything more frequent impossible anyway.
    scheduler.add_job(
        _fundamentals_refresh_job,
        trigger=CronTrigger(hour=7, minute=0, day_of_week="mon-fri", timezone=ET),
        id="fundamentals_refresh",
        name="Fundamentals cache refresh",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
    )

    # 1d. Research dossiers — daily, after the fundamentals cache is warm.
    #     Ordering matters: a dossier is built from cached provider data, so
    #     running it before the refresh produces a report about yesterday.
    #     Gated off by default — five model calls per ticker is a real bill,
    #     and nothing in the fast path depends on the output.
    if settings.research_agents_enabled:
        scheduler.add_job(
            _research_refresh_job,
            trigger=CronTrigger(hour=settings.research_daily_refresh_hour, minute=30,
                                day_of_week="mon-fri", timezone=ET),
            id="research_refresh",
            name="Deep research dossier refresh",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
        )

    # 1e. Research outcome settlement — 30 minutes before the refresh, so a
    #     dossier written today can cite the grade the previous one just
    #     received. The other order would leave every reading working from a
    #     record one day stale, permanently.
    if settings.research_agents_enabled:
        scheduler.add_job(
            _research_outcomes_job,
            trigger=CronTrigger(hour=settings.research_daily_refresh_hour, minute=0,
                                day_of_week="mon-fri", timezone=ET),
            id="research_outcomes",
            name="Deep research outcome settlement",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
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

    # 4. Daily digest — 09:00 ET Mon–Fri
    scheduler.add_job(
        _daily_digest_job,
        trigger=CronTrigger(hour=9, minute=0, day_of_week="mon-fri", timezone=ET),
        id="daily_digest",
        name="Daily watchlist digest",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # 5. Broker connectivity watch — every 5 min, always on.
    #    Cheap (an in-process boolean), and the failure it catches is otherwise
    #    silent until someone tries to place an order.
    scheduler.add_job(
        _broker_watch_job,
        trigger=IntervalTrigger(minutes=5),
        id="broker_watch",
        name="Broker connectivity watch",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )

    # 9. Capability watch — the same job for the data sources.
    #    Runs on a longer interval than the pipeline that feeds it: it reads
    #    records rather than providers, and a source that just degraded is
    #    equally degraded ten minutes later. Nothing is fetched here.
    scheduler.add_job(
        _capability_watch_job,
        trigger=IntervalTrigger(minutes=10),
        id="capability_watch",
        name="Data source health watch",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info(
        "scheduler_started",
        interval_minutes=settings.ingestion_interval_minutes,
        tickers=settings.ticker_list,
        jobs=["market_pipeline", "premarket_sweep (08:00 ET)", "perf_tracker (06:00 UTC)", "daily_digest (09:00 ET)"],
    )


def stop_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("scheduler_stopped")
