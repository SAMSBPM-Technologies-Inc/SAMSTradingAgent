"""
MongoDB connection management via Motor (async driver).

Usage:
    from app.db import get_db
    db = await get_db()
    await db["stocks_raw"].insert_one(doc)
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_client: AsyncIOMotorClient | None = None


async def connect_db() -> None:
    """Open the MongoDB connection pool. Called at app startup."""
    global _client
    settings = get_settings()
    logger.info("connecting_to_mongodb", url=settings.mongodb_url[:40] + "…")
    _client = AsyncIOMotorClient(settings.mongodb_url)
    # Trigger a lightweight command to confirm connectivity
    await _client.admin.command("ping")
    logger.info("mongodb_connected", db=settings.mongodb_db_name)
    # Neither of these may abort startup. Connecting to Mongo is the only step
    # here that is genuinely load-bearing for serving requests; index creation
    # and data migration are maintenance, and maintenance failing should
    # degrade the service, not delete it.
    await _ensure_indexes_safely()
    await _migrate_trading_mode_safely()


async def _ensure_indexes_safely() -> None:
    """
    Create indexes, but never let one take the API down.

    This used to be a bare `await _ensure_indexes()`. A malformed unique index
    threw during creation, `connect_db` propagated it out of the lifespan
    startup, and the process died — so a defect in a *trades* index stopped
    people logging in. That blast radius is wrong: indexes are a performance
    and integrity concern, and the right failure mode is a loud degraded start,
    not a dead service.

    Logged at error level with the exception attached, because a missing unique
    index silently weakens a guarantee something else is relying on — the
    idempotency index in particular is the real defence against a
    double-submitted order.
    """
    try:
        await _ensure_indexes()
    except Exception as exc:
        logger.error(
            "mongodb_index_creation_failed_continuing",
            error=str(exc),
            error_type=type(exc).__name__,
            impact="the API is serving, but an index is missing — uniqueness "
                   "guarantees backed by it are not being enforced",
        )


async def _migrate_trading_mode_safely() -> None:
    """
    Run the migration, but never let it take the API down.

    Same reasoning as `_ensure_indexes_safely`. If this fails, accounts that
    were trading unattended load as MANUAL and start queueing proposals instead
    of placing orders — visible and recoverable, unlike a dead service.
    """
    try:
        await _migrate_trading_mode()
    except Exception as exc:
        logger.error(
            "trading_mode_migration_failed_continuing",
            error=str(exc),
            error_type=type(exc).__name__,
            impact="accounts already trading unattended may load as MANUAL and "
                   "queue proposals rather than placing orders",
        )


async def _migrate_trading_mode() -> None:
    """
    Preserve existing autonomy when `mode` was introduced.

    `AutoTradeSettings.mode` defaults to MANUAL, which is the right default for
    a new account but the wrong outcome for an existing one: anybody already
    running with `enabled=True` was running unattended, and letting them load as
    MANUAL would stop their trading silently — the worst way for a live system
    to change behaviour.

    Writing AUTO explicitly for those accounts keeps them exactly as they were
    and leaves the safe default in place for everyone new. Idempotent: the
    filter only matches documents that have no `mode` yet.
    """
    db = await get_db()
    result = await db[COLL_USERS].update_many(
        {
            "auto_trade_settings.enabled": True,
            "auto_trade_settings.mode": {"$exists": False},
        },
        {"$set": {"auto_trade_settings.mode": "AUTO"}},
    )
    if result.modified_count:
        logger.info(
            "trading_mode_migrated",
            accounts=result.modified_count,
            mode="AUTO",
            reason="preserved pre-existing unattended trading",
        )


async def _ensure_indexes() -> None:
    """
    Create indexes idempotently on startup. Safe to call on every restart.

    Wrapped by `_ensure_indexes_safely`, which is what actually runs — see the
    note there on why an index failure must not be fatal.
    """
    db = await get_db()
    await db[COLL_SIGNALS].create_index("ticker", unique=True, background=True)
    await db[COLL_SIGNAL_HISTORY].create_index("ticker", background=True)
    await db[COLL_SIGNAL_HISTORY].create_index("generated_at", background=True)
    await db[COLL_SIGNAL_HISTORY].create_index(
        [("generated_at", 1), ("return_20d", 1)], background=True
    )
    await db[COLL_SIGNAL_HISTORY].create_index(
        [("ticker", 1), ("hour_bucket", 1)],
        unique=True,
        partialFilterExpression={"hour_bucket": {"$type": "date"}},
        background=True,
    )
    # Drop legacy global-unique ticker index if it still exists from pre-auth deployment
    try:
        await db[COLL_WATCHED].drop_index("ticker_1")
        logger.info("dropped_legacy_ticker_1_index")
    except Exception:
        pass  # already gone — safe to ignore

    # watched_tickers: unique per (user_id, ticker) — one entry per user per ticker
    await db[COLL_WATCHED].create_index(
        [("user_id", 1), ("ticker", 1)], unique=True, background=True
    )
    await db[COLL_USERS].create_index("email", unique=True, background=True)
    # trades: index by user + ticker for fast position lookups
    await db[COLL_TRADES].create_index([("user_id", 1), ("ticker", 1)], background=True)
    await db[COLL_TRADES].create_index("opened_at", background=True)
    await db[COLL_TRADES].create_index("status", background=True)
    # Idempotency for user-initiated orders. This index — not the lookup in the
    # route — is what actually prevents a double-clicked Buy from buying twice:
    # two concurrent requests can both read "no prior order" before either
    # writes.
    #
    # partialFilterExpression, NOT sparse. A compound sparse index only skips a
    # document when *every* indexed field is missing, and every trade has a
    # user_id — so `sparse=True` indexed the whole existing collection with
    # idempotency_key: null, and the second such document collided against
    # unique=True. That threw inside _ensure_indexes, which is awaited
    # unguarded at startup, and took the entire API down.
    await db[COLL_TRADES].create_index(
        [("user_id", 1), ("idempotency_key", 1)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
        background=True,
    )
    # financial_statements: one document per (ticker, period, timeframe).
    # Unique so a re-fetch of an already-seen filing updates that period rather
    # than accumulating a duplicate — the collection only ever gains rows, so
    # without this a daily job would pile up a copy of the same decade a day.
    #
    # partialFilterExpression for the same reason it is on the trades index
    # above: a compound unique index over documents missing one of the fields
    # collides on the second such document and throws at startup. Every row we
    # write has a string period_end; anything that does not is out of scope for
    # the constraint rather than a reason to fail the whole index pass.
    await db[COLL_STATEMENTS].create_index(
        [("ticker", 1), ("timeframe", 1), ("period_end", -1)],
        unique=True,
        partialFilterExpression={"period_end": {"$type": "string"}},
        background=True,
    )
    # earnings_history: one document per ticker, refreshed weekly.
    await db[COLL_EARNINGS].create_index("ticker", unique=True, background=True)
    # research_dossiers: newest-first lookup per ticker. Deliberately NOT
    # unique — dossiers are a retained series and two runs on the same day are
    # a thing that should be allowed to happen, not an error that takes the API
    # down at startup.
    await db[COLL_DOSSIERS].create_index(
        [("ticker", 1), ("as_of", -1)], background=True
    )
    logger.info("mongodb_indexes_ensured")


async def close_db() -> None:
    """Close the MongoDB connection pool. Called at app shutdown."""
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("mongodb_disconnected")


async def get_db() -> AsyncIOMotorDatabase:
    """Return the application database. Raises if not connected."""
    if _client is None:
        raise RuntimeError("Database not connected – call connect_db() first.")
    return _client[get_settings().mongodb_db_name]


# ── Collection name constants ─────────────────────────────────────────────────
COLL_RAW            = "stocks_raw"
COLL_FEATURES       = "stocks_features"
COLL_SIGNALS        = "stocks_signals"
COLL_SIGNAL_HISTORY = "stocks_signal_history"   # append-only historical signals
COLL_WATCHED        = "watched_tickers"          # per-user watched tickers
COLL_USERS          = "users"                    # registered users
COLL_TRADES         = "trades"                   # automated trade execution log
COLL_FUNDAMENTALS_CACHE = "stocks_fundamentals"  # per-ticker provider snapshot
COLL_STATEMENTS     = "financial_statements"     # accumulated statement history
COLL_EARNINGS       = "earnings_history"         # estimate vs actual, per ticker
COLL_DOSSIERS       = "research_dossiers"        # deep-research output per ticker
