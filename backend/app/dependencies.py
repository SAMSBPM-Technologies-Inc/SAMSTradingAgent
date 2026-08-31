"""
FastAPI dependencies — injected into protected routes via Depends().

Two layers. `get_current_user` answers "who is this"; the capability
requirements below answer "may they". Both are cheap to compose because
FastAPI caches a sub-dependency within one request, so a route that depends on
`require_trading` still reads the user document exactly once.

**Routes name capabilities, never tiers.** See `services/entitlements.py` for
why. A route that asks for `may_trade` keeps working when the table changes; a
route that asks whether the tier is PRO has become a second copy of the policy.
"""
from typing import Callable

from bson import ObjectId
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import COLL_USERS, get_db
from app.services.auth import decode_token, token_predates_password_change
from app.services.entitlements import Entitlements, entitlements_for, is_admin

_bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Validate the Bearer JWT and return the user document.
    Raises 401 if the token is missing, invalid, or expired.
    """
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    db = await get_db()
    user = await db[COLL_USERS].find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # A password change ends every session issued before it. Without this a
    # reset would rotate the credential and leave any stolen token working for
    # the rest of its 24 hours, which is most of what resetting is for.
    #
    # The caller who *made* the change is not signed out: `PUT /auth/password`
    # hands back a freshly minted token in the same response.
    if token_predates_password_change(payload, user):
        raise HTTPException(
            status_code=401,
            detail="Your password changed. Sign in again.",
        )

    return user


async def get_entitlements(
    current_user: dict = Depends(get_current_user),
) -> Entitlements:
    """What the caller may do. Resolved from the document, never from the token."""
    return entitlements_for(current_user)


#: One sentence per capability, addressed to the person who hit the wall. Each
#: says what is missing rather than what they are — "you are BASIC" tells a user
#: nothing they can act on.
_REFUSALS: dict[str, str] = {
    "may_trade":
        "Trading and broker access are not part of your plan.",
    "may_spend_tokens":
        "Running a new analysis is not part of your plan. "
        "Stored readings are still available.",
    "may_bring_own_key":
        "Configuring your own model provider keys is not part of your plan.",
    "may_enrol_in_nightly_research":
        "Automatic daily research is not enabled on your account.",
}


def tier_refusal(capability: str, ent: Entitlements) -> HTTPException:
    """
    The one refusal shape, so all three clients parse one thing.

    403 rather than 402 or 404. 402 Payment Required implies a self-serve
    upgrade that does not exist here and is not planned. 404 hides the feature
    but also lies to a confused legitimate user and makes support impossible.
    403 with a machine-readable `capability` says what happened and gives the
    clients something stable to key off.

    Note this is a *structured* detail, where every pre-existing route on this
    API raises a plain string. The shared client helper reads both.
    """
    return HTTPException(
        status_code=403,
        detail={
            "error": "tier_required",
            "capability": capability,
            "tier": ent.tier.value,
            "message": _REFUSALS.get(capability, "That is not part of your plan.")
            + " Contact the desk to change your plan.",
        },
    )


def require_capability(capability: str) -> Callable:
    """
    Build a dependency that refuses anyone without `capability`.

    Used at router level where a whole surface is gated — `routes/trading.py`
    does this — because a per-route list is a list somebody extends without
    remembering, and behind /trading is one shared brokerage account.
    """

    async def _dependency(ent: Entitlements = Depends(get_entitlements)) -> Entitlements:
        if not ent.has(capability):
            raise tier_refusal(capability, ent)
        return ent

    _dependency.__name__ = f"require_{capability}"
    return _dependency


require_trading = require_capability("may_trade")
require_token_spend = require_capability("may_spend_tokens")
require_own_keys = require_capability("may_bring_own_key")


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    The operator only.

    Being TRADER is not being admin — the highest tier is a customer, not the
    person who provisions them, and there is a test asserting exactly that.
    Identity comes from `ADMIN_EMAIL` in config rather than a field on the
    document; `services/entitlements.is_admin` records why.
    """
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "admin_required",
                "capability": "admin",
                "tier": entitlements_for(current_user).tier.value,
                "message": "This area is limited to the account operator.",
            },
        )
    return current_user
