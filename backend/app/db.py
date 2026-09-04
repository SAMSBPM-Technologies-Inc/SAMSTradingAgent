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

#: The value `AutoTradeSettings.min_signal_score` shipped with, before it was
#: tied to `BUY_THRESHOLD`. Kept here rather than in the model so the model
#: carries only what it means now — see `_migrate_min_signal_score`.
_LEGACY_MIN_SIGNAL_SCORE = 0.75


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
    await _migrate_access_tier_safely()
    await _migrate_min_signal_score_safely()


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


async def _migrate_access_tier_safely() -> None:
    """
    Run the tier migration, but never let it take the API down.

    Same reasoning as the two wrappers above, and the impact is worth stating
    precisely: `entitlements_for` reads a missing `access_tier` as BASIC, so if
    this never runs, every existing account loads without trading, without its
    own provider keys, and with a five-ticker cap. That is loud, visible and
    reversible by restarting — unlike the alternative reading, where a failed
    migration would hand full access to accounts nobody has classified.
    """
    try:
        await _migrate_access_tier()
    except Exception as exc:
        logger.error(
            "access_tier_migration_failed_continuing",
            error=str(exc),
            error_type=type(exc).__name__,
            impact="accounts without an explicit access_tier load as BASIC — "
                   "no trading, no provider keys, and a watchlist cap",
        )


async def _migrate_min_signal_score_safely() -> None:
    """
    Run the threshold migration, but never let it take the API down.

    Same reasoning as the wrappers above. If this fails, affected accounts keep
    refusing BUYs in the [0.70, 0.75) band exactly as they have been — the
    status quo, not a new failure — and the gate panel now reports the
    threshold, so the cause is visible without the migration having run.
    """
    try:
        await _migrate_min_signal_score()
    except Exception as exc:
        logger.error(
            "min_signal_score_migration_failed_continuing",
            error=str(exc),
            error_type=type(exc).__name__,
            impact="accounts left on the old 0.75 default keep skipping BUYs "
                   "between the verdict threshold and 0.75",
        )


async def _migrate_min_signal_score() -> None:
    """
    Undo a default that was quietly refusing every BUY the engine produced.

    `min_signal_score` shipped at 0.75 while `BUY_THRESHOLD` is 0.70, and
    nothing tied the two together. The composite's realistic ceiling is about
    0.75, so in practice *every* published BUY landed in the band between them
    and was refused at `execute_entry` — recorded as a SKIPPED row reading
    "Score 0.71 below threshold 0.75", underneath a ticker page whose gate
    panel showed the BUY gate passing.

    The filter is deliberately narrow: **exactly** the old default, and only
    where it is above the new one. A value of 0.75 that the user chose by hand
    is indistinguishable from one they never touched — that is a real
    limitation of not having recorded the difference — but 0.75 was the
    shipped default for the entire life of the field, and the failure mode of
    leaving it is an agent that never trades and cannot say why. Any other
    value is somebody's decision and is left alone.

    Idempotent: after this runs the filter matches nothing, so a restart is a
    no-op, and a user who sets 0.75 back deliberately keeps it — the next
    startup will lower it once more, which is the one case worth knowing about
    and the reason this logs at info with the count.
    """
    # Local import: `signal_generator` imports this module, so taking the
    # constant at module level here would close a cycle.
    from app.services.signal_generator import BUY_THRESHOLD

    if _LEGACY_MIN_SIGNAL_SCORE <= BUY_THRESHOLD:
        # Somebody raised BUY_THRESHOLD past the old default. There is nothing
        # to undo, and lowering to it would be a raise.
        return

    db = await get_db()
    result = await db[COLL_USERS].update_many(
        {
            "auto_trade_settings.min_signal_score": _LEGACY_MIN_SIGNAL_SCORE,
        },
        {"$set": {"auto_trade_settings.min_signal_score": BUY_THRESHOLD}},
    )
    if result.modified_count:
        logger.info(
            "min_signal_score_migrated",
            accounts=result.modified_count,
            was=_LEGACY_MIN_SIGNAL_SCORE,
            now=BUY_THRESHOLD,
            reason="order-path threshold sat above the verdict threshold, so "
                   "every published BUY was skipped",
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


async def _migrate_access_tier() -> None:
    """
    Preserve existing access when `access_tier` was introduced.

    Every account that exists at this point was provisioned by hand by the
    operator and had every feature — there was no tier system to put them in.
    Letting them load as BASIC would strip a live trader's broker access and
    cap their watchlist without anyone asking for it, which is the same failure
    `_migrate_trading_mode` exists to prevent: the worst way for a running
    system to change is silently.

    So existing documents are written TRADER *explicitly*, and everything
    created from here on carries a tier chosen at creation — `create_user.py`
    and `POST /admin/users` both default to BASIC.

    Idempotent: the filter only matches documents that have no `access_tier`
    yet, so a restart is a no-op and a hand-set tier is never overwritten.
    """
    db = await get_db()
    result = await db[COLL_USERS].update_many(
        {"access_tier": {"$exists": False}},
        {"$set": {"access_tier": "TRADER"}},
    )
    if result.modified_count:
        logger.info(
            "access_tier_migrated",
            accounts=result.modified_count,
            tier="TRADER",
            reason="preserved pre-existing full access",
        )


async def _ensure_indexes() -> None:
    """
    Create indexes idempotently on startup. Safe to call on every restart.

    Wrapped by `_ensure_indexes_safely`, which is what actually runs — see the
    note there on why an index failure must not be fatal.
    """
    db = await get_db()
    await db[COLL_SOURCE_HEALTH].create_index("source", unique=True, background=True)
    await db[COLL_SIGNALS].create_index("ticker", unique=True, background=True)
    await db[COLL_SIGNAL_HISTORY].create_index("ticker", background=True)
    await db[COLL_SIGNAL_HISTORY].create_index("generated_at", background=True)
    await db[COLL_SIGNAL_HISTORY].create_index(
        [("generated_at", 1), ("return_20d", 1)], background=True
    )
    # One row per published verdict per hour — the verdict is part of the key.
    #
    # This was `(ticker, hour_bucket)`, which combined with `$setOnInsert` in
    # `pipeline._append_history` meant only the FIRST evaluation of each
    # clock-hour was ever retained. Trades execute every five minutes and SELL
    # publishes immediately, so a SELL at :35 closed a real position and left
    # the :05 HOLD as the hour's record. `stocks_signal_history` is the only
    # retained series and every counterfactual is computed from it.
    await db[COLL_SIGNAL_HISTORY].create_index(
        [("ticker", 1), ("hour_bucket", 1), ("signal", 1)],
        unique=True,
        partialFilterExpression={"hour_bucket": {"$type": "date"}},
        background=True,
    )
    # Drop the superseded two-key unique index. It is *unique*, so leaving it
    # in place would reject the second verdict of an hour — the exact row the
    # new key exists to admit — and the insert would fail silently inside
    # `_append_history`'s try/except. Same pattern as the legacy ticker_1 drop
    # below: named, guarded, safe to run on a database that never had it.
    try:
        await db[COLL_SIGNAL_HISTORY].drop_index("ticker_1_hour_bucket_1")
        logger.info("dropped_superseded_signal_history_index")
    except Exception:
        pass  # already gone, or this database was created after the change
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
    # access_requests: the contact-form queue. Newest-first listing, plus a TTL
    # so the collection is bounded in *time* as well as in rate. The form is
    # the only unauthenticated insert on this API; the per-address limit bounds
    # how fast it can grow, and this bounds how large it can ever get.
    await db[COLL_ACCESS_REQUESTS].create_index([("created_at", -1)], background=True)
    await db[COLL_ACCESS_REQUESTS].create_index(
        "created_at", expireAfterSeconds=180 * 24 * 3600, background=True,
        name="created_at_ttl",
    )
    # password_resets: looked up by token hash on every redemption, so that
    # index is load-bearing rather than an optimisation. Unique because two
    # documents sharing a hash would mean two live links for one token.
    #
    # The TTL is set on `expires_at` with expireAfterSeconds=0, so Mongo deletes
    # each document at its own deadline rather than at a fixed age. It is a
    # sweeper, not the enforcement: `redeem` puts the expiry in its filter, so a
    # token is dead the second it lapses whether or not the collection has been
    # swept yet.
    await db[COLL_PASSWORD_RESETS].create_index(
        "token_hash", unique=True, background=True,
    )
    await db[COLL_PASSWORD_RESETS].create_index("user_id", background=True)
    await db[COLL_PASSWORD_RESETS].create_index(
        "expires_at", expireAfterSeconds=0, background=True, name="expires_at_ttl",
    )
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
    # Dossiers are per-user now, and every read is "the newest one this reader
    # has for this ticker". The legacy shared series carries no `user_id`, so
    # those documents index under a null and are still found by the fallback
    # query in `latest_dossier`.
    await db[COLL_DOSSIERS].create_index(
        [("user_id", 1), ("ticker", 1), ("as_of", -1)], background=True
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
#: Contact-form submissions, retained so provisioning is a queue rather than an
#: inbox search. Bounded by a TTL index as well as by the per-address rate
#: limit — the form is unauthenticated, so time is the second bound.
COLL_ACCESS_REQUESTS = "access_requests"         # who asked for an account
#: Outstanding password-reset links, stored as a hash of the token and never
#: the token itself. Single-use and short-lived; the TTL index is a backstop
#: for the ones nobody ever clicks.
COLL_PASSWORD_RESETS = "password_resets"         # one-time reset links
#: One document per data source plus one per subsystem — never per ticker, so it
#: is bounded at a handful of rows forever and does not grow with the watchlist,
#: the user count or time. Current state only; this is deliberately not a time
#: series, because an uptime history is a different feature with a retention
#: policy attached.
COLL_SOURCE_HEALTH  = "system_health"            # last known state per source
