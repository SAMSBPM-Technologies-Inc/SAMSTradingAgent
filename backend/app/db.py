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
COLL_WATCHED        = "watched_tickers"          # user-added tickers via POST /ticker
