"""
POST /auth/login            — get JWT token
GET  /auth/me               — current user profile
PUT  /auth/me               — update display name and/or scoring weights
PUT  /auth/password         — change your own password
POST /auth/forgot-password  — ask for a reset link (public)
POST /auth/reset-password   — redeem one (public)

The last two are the only unauthenticated writes here, and they are shaped by
one rule: **neither may reveal whether an account exists.** `POST /contact`
already documents why an endpoint a stranger can reach needs care; these two
add account enumeration to the list of things that must not leak.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, model_validator

from app.db import COLL_USERS, get_db
from app.dependencies import get_current_user
from app.models.user import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.config import get_settings
from app.services import password_reset, rate_limit
from app.services.notifier import send_password_reset
from app.services.auth import (
    MIN_PASSWORD_LENGTH,
    create_access_token,
    password_update,
    verify_password,
)
from app.services.entitlements import entitlements_for, is_admin
from app.utils.net import client_ip as _client_ip
from app.utils.logger import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


# ── Request / response models ─────────────────────────────────────────────────

class ScoringWeights(BaseModel):
    """Per-user scoring weights. The 6 base weights must sum to 1.0.
    alternative_data is an additive modifier (not part of the sum constraint)."""
    technical: float = 0.25
    fundamental: float = 0.15
    sentiment: float = 0.20
    macro: float = 0.15
    volatility: float = 0.10
    catalyst: float = 0.15
    alternative_data: float = 0.10

    @model_validator(mode="after")
    def validate_sum(self) -> "ScoringWeights":
        total = self.technical + self.fundamental + self.sentiment + self.macro + self.volatility + self.catalyst
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Base scoring weights (technical + fundamental + sentiment + macro + volatility + catalyst) "
                f"must sum to 1.0, got {total:.4f}"
            )
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UpdateMeRequest(BaseModel):
    display_name: Optional[str] = None
    scoring_weights: Optional[ScoringWeights] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    """
    Authenticate and return an access token.

    Rate limited per email and per client address. This endpoint previously had
    no limit of any kind, so a known email could be guessed against at whatever
    rate the network allowed.
    """
    client_ip = _client_ip(request)

    decision = rate_limit.check_login_allowed(body.email, client_ip)
    if not decision.allowed:
        logger.warning("login_rate_limited", email=body.email, client=client_ip)
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-in attempts. Try again shortly.",
            headers={"Retry-After": str(decision.retry_after)},
        )

    db = await get_db()
    user = await db[COLL_USERS].find_one({"email": body.email})
    if not user or not verify_password(body.password, user["password_hash"]):
        rate_limit.record_login_failure(body.email, client_ip)
        # Deliberately identical for "no such user" and "wrong password" — a
        # distinguishable response enumerates accounts.
        raise HTTPException(status_code=401, detail="Invalid email or password")

    rate_limit.record_login_success(body.email, client_ip)
    logger.info("user_login", email=body.email)
    return TokenResponse(access_token=create_access_token(str(user["_id"]), user["email"]))


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Return the current user's profile, including what they may do.

    `entitlements` is the whole resolved object, so **no client ever derives
    policy from a tier name**. Both clients read these booleans; neither maps a
    tier to a feature or restates a cap. It is the rule `/analyze` already
    follows by returning `breakdown` and `gate` from the engine rather than
    letting the UI keep its own copy of the weights — and it means a fourth
    tier, or a retuned cap, needs no client change at all.

    Also why there is no tier claim in the JWT: this is read on every request
    anyway, and a claim would be stale for the token's whole 24-hour life, so a
    downgrade would take effect whenever the user next signed in. For a control
    whose purpose is to stop spending now, that is the wrong direction.
    """
    ent = entitlements_for(current_user)
    return {
        "id": str(current_user["_id"]),
        "email": current_user["email"],
        "display_name": current_user.get("display_name", ""),
        "created_at": current_user.get("created_at"),
        "scoring_weights": current_user.get("scoring_weights"),
        "access_tier": ent.tier.value,
        "is_admin": is_admin(current_user),
        "entitlements": ent.to_response().model_dump(),
    }


@router.put("/me")
async def update_me(
    body: UpdateMeRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update display name and/or personal scoring weights."""
    if body.display_name is None and body.scoring_weights is None:
        raise HTTPException(status_code=400, detail="Provide display_name and/or scoring_weights")

    updates: dict = {}
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.scoring_weights is not None:
        updates["scoring_weights"] = body.scoring_weights.model_dump()

    db = await get_db()
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": updates},
    )
    return {"status": "updated", **updates}


@router.put("/password", response_model=TokenResponse)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> TokenResponse:
    """
    Change your own password, and get a fresh token back.

    **The current password is required even though the caller already holds a
    valid token.** A token can be stolen; without this check whoever stole it
    could set a new password and lock the real owner out of their own account
    permanently. Holding a session proves you were signed in once, not that you
    are the owner now.

    Rate limited on the same counter as sign-in, and for the same reason: this
    is a second place a password can be guessed against, and a slower one to
    notice because it needs no failed logins.

    **The response carries a new token, and that is not a convenience.**
    `password_update` records `password_changed_at`, which invalidates every
    token issued before it — including the one this request arrived on. Handing
    back a freshly minted one is what lets the caller stay signed in on *this*
    device while every other session ends, which is exactly the behaviour
    somebody changing a password they think is known elsewhere wants.
    """
    email = str(current_user.get("email") or "")
    client_ip = _client_ip(request)

    decision = rate_limit.check_login_allowed(email, client_ip)
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Try again shortly.",
            headers={"Retry-After": str(decision.retry_after)},
        )

    if not verify_password(body.current_password, current_user.get("password_hash", "")):
        rate_limit.record_login_failure(email, client_ip)
        logger.warning("password_change_rejected", email=email, client=client_ip)
        raise HTTPException(status_code=403, detail="That is not your current password.")

    if body.new_password == body.current_password:
        # Not a security property — it just does nothing, and silently doing
        # nothing while reporting success is how somebody ends up believing a
        # compromised password was rotated.
        raise HTTPException(
            status_code=400,
            detail="The new password is the same as the current one.",
        )

    rate_limit.record_login_success(email, client_ip)

    db = await get_db()
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": password_update(body.new_password)},
    )
    # Somebody who has just set a password has answered the question any
    # outstanding reset link was asking. Leaving one live would let an old
    # email undo what they just did.
    await password_reset.revoke_for(str(current_user["_id"]))
    logger.info("password_changed", email=email)

    return TokenResponse(
        access_token=create_access_token(str(current_user["_id"]), email),
    )


class ForgotPasswordResponse(BaseModel):
    """
    Deliberately says nothing about the account.

    One field, always the same value. Anything conditional here — a different
    message, a different status, even a different response time worth
    measuring — turns this endpoint into a way to test whether an address has
    an account on the system.
    """

    sent: bool = True


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
) -> ForgotPasswordResponse:
    """
    Send a one-time reset link, if that address has an account.

    **The response is identical either way.** There is no self-serve signup
    here, so an address that has an account is an address the operator chose to
    let in — and confirming which addresses those are is a fact worth having
    for anyone probing the system. So: same body, same status, whether the
    lookup matched, whether the mail sent, and whether the account was
    suspended or is one nobody has used in a year.

    The one thing that *is* reported is a deployment with no mail configured at
    all. That is not enumeration — the answer does not depend on the address —
    and staying silent would leave somebody waiting for a message that was
    never going to arrive, with no other way back into their account.
    """
    settings = get_settings()
    client_ip = _client_ip(request)
    email = str(body.email).strip().lower()

    if not settings.email_enabled:
        raise HTTPException(
            status_code=503,
            detail="Password reset by email is not available on this deployment. "
                   "Contact the desk to have your password reset.",
        )

    decision = rate_limit.check_reset_allowed(email, client_ip)
    if not decision.allowed:
        logger.warning("password_reset_rate_limited", email=email, client=client_ip)
        raise HTTPException(
            status_code=429,
            detail="Too many reset requests. Try again later.",
            headers={"Retry-After": str(decision.retry_after)},
        )
    # Charged before the lookup, so a real address and a fake one cost the
    # same. Charging only on a match would make the limiter itself an oracle.
    rate_limit.record_reset_request(email, client_ip)

    db = await get_db()
    user = await db[COLL_USERS].find_one({"email": email}, {"_id": 1})
    if not user:
        logger.info("password_reset_unknown_address", client=client_ip)
        return ForgotPasswordResponse()

    token = await password_reset.issue(str(user["_id"]))
    if token is None:
        # The token could not be stored, so no link exists to send. Reported as
        # an outage rather than a silent success: this failure is about the
        # server, not about the address, so saying so leaks nothing.
        raise HTTPException(
            status_code=503,
            detail="Could not start a password reset just now. Please try again shortly.",
        )

    link = f"{settings.public_base_url.rstrip('/')}/reset-password?token={token}"
    failure = await send_password_reset(email, link, password_reset.TOKEN_TTL_MINUTES)
    if failure:
        # Logged, not returned. A mail failure here is real and worth chasing,
        # but reporting it would distinguish an address that has an account
        # from one that does not — which is the whole thing this endpoint is
        # shaped to avoid.
        logger.error("password_reset_email_failed", email=email, error=failure)

    logger.info("password_reset_requested", email=email, client=client_ip)
    return ForgotPasswordResponse()


@router.post("/reset-password", response_model=TokenResponse)
async def reset_password(body: ResetPasswordRequest, request: Request) -> TokenResponse:
    """
    Redeem a reset link and sign in.

    A single 400 covers expired, already used, superseded and never-real. They
    are one answer on purpose: telling them apart tells whoever holds a stale
    link something about the account it was issued for.

    Returning a token means the person who just proved they control the mailbox
    lands signed in rather than on a login form typing the password they set
    ten seconds ago. Every *other* session for that account is already dead —
    `password_update` records `password_changed_at` — which is what makes this
    a recovery rather than a second way in alongside whoever locked them out.
    """
    client_ip = _client_ip(request)

    user_id = await password_reset.redeem(body.token)
    if user_id is None:
        logger.warning("password_reset_token_rejected", client=client_ip)
        raise HTTPException(
            status_code=400,
            detail="That reset link is no longer valid. Request a new one.",
        )

    db = await get_db()
    try:
        oid = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="That reset link is no longer valid.")

    user = await db[COLL_USERS].find_one({"_id": oid})
    if not user:
        # The account went away between issuing and redeeming. The token is
        # already consumed, so there is nothing to clean up.
        raise HTTPException(status_code=400, detail="That reset link is no longer valid.")

    await db[COLL_USERS].update_one(
        {"_id": oid}, {"$set": password_update(body.new_password)},
    )
    # Belt to `issue`'s braces: that supersedes on issue, this clears anything
    # left after a successful change, so an older email cannot undo it.
    await password_reset.revoke_for(user_id)

    email = str(user.get("email") or "")
    rate_limit.record_login_success(email, client_ip)
    logger.info("password_reset_completed", email=email, client=client_ip)

    return TokenResponse(access_token=create_access_token(user_id, email))
