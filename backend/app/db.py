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
    await db[COLL_USERS].create_index("ibkr_host", sparse=True, background=True)
    # trades: index by user + ticker for fast position lookups
    await db[COLL_TRADES].create_index([("user_id", 1), ("ticker", 1)], background=True)
    await db[COLL_TRADES].create_index("opened_at", background=True)
    await db[COLL_TRADES].create_index("status", background=True)
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
