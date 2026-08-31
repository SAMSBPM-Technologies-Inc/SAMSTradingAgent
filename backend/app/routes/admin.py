"""
Provisioning, without SSH.

Accounts used to be created only by running `scripts/create_user.py` on the
VPS, which meant every new user, every tier change and every cap adjustment
needed a shell. These routes are the same operations over HTTP, for the one
address named in `ADMIN_EMAIL`.

Three things this module deliberately does not do:

**It never returns a credential.** `AdminUserRow` has no field capable of
holding a `password_hash` or a key ciphertext — a type-level guarantee rather
than a `del` before serialising, the same choice `models/llm.KeyStatus` makes.
A generated password is returned exactly once, from the call that generated it,
and no route can read it back.

**There is no `is_admin` field to grant.** Admin identity comes from config, so
the class of bug where a careless `$set` of a request body turns an editable
field into an admin-granting one cannot exist here at all. See
`services/entitlements.is_admin`.

**It does not delete accounts.** A user document is referenced by rows in
`watched_tickers`, `trades`, `research_dossiers` and the per-user signal series,
none of which cascade. Shipping half a cascade is worse than shipping none, so
this says so instead.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import COLL_ACCESS_REQUESTS, COLL_TRADES, COLL_USERS, COLL_WATCHED, get_db
from app.dependencies import require_admin
from app.models.trade import TradeStatus
from app.models.user import (
    AccessRequestRow,
    AccessTier,
    AdminUserCreateRequest,
    AdminUserCreateResponse,
    AdminUserRow,
    AdminUserUpdateRequest,
)
from app.services.auth import generate_password, new_user_document
from app.services.entitlements import entitlements_for, is_admin
from app.utils.logger import get_logger

# Gated at the router for the same reason `/trading` is: a per-route decorator
# is a list somebody extends without remembering, and the thing behind this one
# is every account on the system.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
logger = get_logger(__name__)


def _oid(user_id: str) -> ObjectId:
    try:
        return ObjectId(user_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="No such user")


async def _row(user: dict, watching: int) -> AdminUserRow:
    ent = entitlements_for(user)
    override = user.get("watchlist_cap")
    return AdminUserRow(
        id=str(user["_id"]),
        email=user["email"],
        display_name=user.get("display_name", ""),
        created_at=user.get("created_at"),
        access_tier=ent.tier,
        watchlist_cap_override=override if isinstance(override, int)
        and not isinstance(override, bool) else None,
        watchlist_cap=ent.watchlist_cap,
        watching=watching,
        research_enabled=bool((user.get("llm_settings") or {}).get("research_enabled")),
        research_daily_allowed=bool(user.get("research_daily_allowed")),
        llm_key_count=len((user.get("llm_settings") or {}).get("keys") or []),
        is_admin=is_admin(user),
    )


@router.get("/users", response_model=list[AdminUserRow], summary="Every account")
async def list_users() -> list[AdminUserRow]:
    """
    All accounts, with the tier they are on and how much of their cap they use.

    The watched count comes from one grouped aggregation rather than a query per
    user — this list is short today, but a per-row query is the shape that
    quietly becomes slow and nobody notices until it is the admin page that is
    slow.
    """
    db = await get_db()
    users = await db[COLL_USERS].find({}).sort("created_at", 1).to_list(length=1000)

    counts: dict[str, int] = {}
    try:
        async for row in db[COLL_WATCHED].aggregate(
            [{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}]
        ):
            counts[str(row["_id"])] = int(row.get("n") or 0)
    except Exception as exc:
        # A missing count is cosmetic; failing the whole page over it is not.
        logger.warning("admin_watch_counts_failed", error=str(exc))

    return [await _row(u, counts.get(str(u["_id"]), 0)) for u in users]


@router.post("/users", response_model=AdminUserCreateResponse, status_code=201,
             summary="Provision an account")
async def create_user(body: AdminUserCreateRequest) -> AdminUserCreateResponse:
    """
    Create an account and hand back its password once.

    The password is returned in this response and nowhere else: it is not
    stored in plaintext, not logged, and not readable from any other route. The
    operator emails it on.

    The document is built by `services/auth.new_user_document`, shared with
    `scripts/create_user.py`, so the two writers cannot produce different
    shapes — a field one of them forgets would show up as an account with
    silently less access than was granted.
    """
    db = await get_db()
    email = str(body.email).strip().lower()

    if await db[COLL_USERS].find_one({"email": email}, {"_id": 1}):
        raise HTTPException(status_code=409, detail=f"{email} already has an account")

    generated = body.password is None
    password = body.password or generate_password()
    doc = new_user_document(
        email=email,
        password=password,
        display_name=body.display_name,
        access_tier=body.access_tier,
        watchlist_cap=body.watchlist_cap,
        research_daily_allowed=body.research_daily_allowed,
    )

    try:
        result = await db[COLL_USERS].insert_one(doc)
    except Exception as exc:
        # The unique index on email is the real guard; the lookup above only
        # makes the common case a clean 409 rather than a 500.
        logger.warning("admin_user_create_failed", email=email, error=str(exc))
        raise HTTPException(status_code=409, detail=f"Could not create {email}")

    doc["_id"] = result.inserted_id
    logger.info("admin_user_created", email=email, tier=body.access_tier.value)
    return AdminUserCreateResponse(
        user=await _row(doc, 0),
        # Only when this call generated it. A password the operator chose is
        # already in their hands and echoing it back adds a copy for nothing.
        password=password if generated else None,
    )


@router.patch("/users/{user_id}", response_model=AdminUserRow,
              summary="Change a tier, a cap, or the nightly-research grant")
async def update_user(
    user_id: str,
    body: AdminUserUpdateRequest,
    force: bool = Query(
        False,
        description="Proceed with a downgrade that removes trading from an "
                    "account holding open positions.",
    ),
) -> AdminUserRow:
    """
    The one genuinely dangerous change here is TRADER → anything else for an
    account with open positions: it takes away the interface that closes them.

    So that case is a 409 naming the tickers unless `force=true`. On force it is
    logged at warning with the list. What is deliberately *not* done is
    rewriting `auto_trade_settings` to tidy up — `_prepare_entry` already
    refuses new entries for a downgraded account and `execute_exit` still works,
    so the positions stay closable by the agent and by reconcile. What is lost
    is the human's ability to close them by hand, which is worth stopping to
    say out loud rather than silently arranging around.
    """
    db = await get_db()
    oid = _oid(user_id)
    user = await db[COLL_USERS].find_one({"_id": oid})
    if not user:
        raise HTTPException(status_code=404, detail="No such user")

    before = entitlements_for(user)
    updates: dict = {}

    if body.access_tier is not None:
        updates["access_tier"] = body.access_tier.value
    if body.clear_watchlist_cap:
        # Distinct from `watchlist_cap: None`, which is indistinguishable from
        # "not supplied" in a PATCH body.
        updates["watchlist_cap"] = None
    elif body.watchlist_cap is not None:
        updates["watchlist_cap"] = max(0, body.watchlist_cap)
    if body.research_daily_allowed is not None:
        updates["research_daily_allowed"] = body.research_daily_allowed

    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to change")

    after = entitlements_for({**user, **{k: v for k, v in updates.items() if v is not None}})

    if before.may_trade and not after.may_trade:
        open_tickers = await _open_positions(db, user)
        if open_tickers and not force:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "open_positions",
                    "tickers": open_tickers,
                    "message": (
                        f"{user['email']} holds {len(open_tickers)} open "
                        f"position(s): {', '.join(open_tickers)}. Removing "
                        "trading takes away the interface that closes them. "
                        "Re-send with force=true to proceed."
                    ),
                },
            )
        if open_tickers:
            logger.warning("admin_downgrade_with_open_positions",
                           email=user["email"], tickers=open_tickers)

    unset: dict = {}
    if updates.get("watchlist_cap", "keep") is None:
        updates.pop("watchlist_cap")
        unset["watchlist_cap"] = ""

    if not after.may_enrol_in_nightly_research:
        # Belt to the scheduler's brace. `research_enabled` may have been set
        # before this downgrade, and the route check only covers the moment of
        # writing — so clear it in the same write rather than relying on the
        # cohort filter alone.
        if (user.get("llm_settings") or {}).get("research_enabled"):
            updates["llm_settings.research_enabled"] = False
            logger.info("admin_nightly_research_revoked", email=user["email"])

    write: dict = {}
    if updates:
        write["$set"] = updates
    if unset:
        write["$unset"] = unset
    await db[COLL_USERS].update_one({"_id": oid}, write)

    logger.info("admin_user_updated", email=user["email"],
                tier=after.tier.value, cap=after.watchlist_cap)

    fresh = await db[COLL_USERS].find_one({"_id": oid}) or {}
    watching = await db[COLL_WATCHED].count_documents({"user_id": str(oid)})
    return await _row(fresh, watching)


async def _open_positions(db, user: dict) -> list[str]:
    """
    Tickers this account is currently holding.

    `user_id` is stored as the stringified ObjectId on trades, the same
    convention `trade_manager` accounts for. A failure here returns nothing —
    it would turn the 409 into a false all-clear, so it is logged loudly.
    """
    try:
        rows = await db[COLL_TRADES].find(
            {"user_id": str(user["_id"]), "status": {"$in": list(TradeStatus.OPEN)}},
            {"ticker": 1},
        ).to_list(length=200)
    except Exception as exc:
        logger.error("admin_open_position_check_failed",
                     email=user.get("email"), error=str(exc),
                     impact="a downgrade may proceed without warning about open positions")
        return []
    return sorted({r["ticker"] for r in rows if r.get("ticker")})


@router.get("/access-requests", response_model=list[AccessRequestRow],
            summary="Who has asked for an account")
async def list_access_requests(
    limit: int = Query(100, ge=1, le=500),
) -> list[AccessRequestRow]:
    """
    The contact-form queue, newest first.

    Read-only on purpose: there is no status to mark off. Provisioning an
    account is the action, and `GET /admin/users` is where the result shows up —
    a second place to record "done" would be a second thing to keep true.
    Entries age out on their own via the TTL index in `db._ensure_indexes`.
    """
    db = await get_db()
    rows = await db[COLL_ACCESS_REQUESTS].find({}).sort("created_at", -1).to_list(length=limit)
    return [
        AccessRequestRow(
            id=str(r["_id"]),
            name=r.get("name", ""),
            email=r.get("email", ""),
            message=r.get("message", ""),
            interest=r.get("interest"),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]
