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
    await _ensure_indexes()
    await _migrate_trading_mode()


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
    """Create indexes idempotently on startup. Safe to call on every restart."""
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
    # writes. Sparse so the automated path, which carries no key, is unaffected.
    await db[COLL_TRADES].create_index(
        [("user_id", 1), ("idempotency_key", 1)],
        unique=True, sparse=True, background=True,
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
