"""
Who a user is allowed to be, as a shape.

Three named tiers — BASIC, PRO, TRADER — stored on `users.access_tier`. This
file carries the *shape*: the enum, and the models the API returns.
`services/entitlements.py` carries the *behaviour*: what each tier may do.

**The field is `access_tier`, not `tier`.** `models/system.py` already has
`CapabilityStatus.tier` for capability severity ("stops" / "behaviour" /
"quiet"), and two unrelated `tier`s in one codebase is how a grep stops being
trustworthy.

**The values are strings, not integers.** A numeric 0-3 ladder was removed from
this project once already; a number invites `tier >= 2`, which reads as policy
while actually depending on declaration order, and is why the old one could not
be reasoned about. Named tiers force every check to name a capability instead.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class AccessTier(str, Enum):
    """
    What an account is provisioned as.

    BASIC  — the portal as a reader. Cannot initiate a spend of money or tokens.
    PRO    — deep research, full analysis runs, and their own provider keys.
             No trading or broker surface at all.
    TRADER — everything, which is what every account was before tiers existed.
    """

    BASIC = "BASIC"
    PRO = "PRO"
    TRADER = "TRADER"


class EntitlementsResponse(BaseModel):
    """
    What the caller may do, as the server computed it.

    Returned whole by `GET /auth/me` so **no client ever derives policy from a
    tier name**. Both clients read these booleans; neither restates a threshold
    or maps a tier to a feature. It is the same rule `/analyze` follows by
    returning `breakdown` and `gate` from the engine rather than letting the UI
    restate the weights — and it means a fourth tier needs no client change.
    """

    tier: AccessTier
    may_trade: bool
    may_spend_tokens: bool
    may_bring_own_key: bool
    may_use_server_key: bool
    may_enrol_in_nightly_research: bool
    #: None means unlimited. Zero is a real cap, not an absence.
    watchlist_cap: Optional[int] = None


class AdminUserRow(BaseModel):
    """
    One account as the admin page sees it.

    **This model has no field capable of holding a `password_hash` or a key
    ciphertext**, which is a type-level guarantee rather than a `del` before
    serialising. `models/llm.KeyStatus` makes the same choice for the same
    reason: the alternative is one forgotten line away from leaking every
    credential on the system.
    """

    id: str
    email: EmailStr
    display_name: str = ""
    created_at: Optional[datetime] = None
    access_tier: AccessTier
    #: The admin's per-user override, or None when the tier default applies.
    watchlist_cap_override: Optional[int] = None
    #: What the override resolves to. None means unlimited.
    watchlist_cap: Optional[int] = None
    watching: int = 0
    research_enabled: bool = False
    research_daily_allowed: bool = False
    llm_key_count: int = 0
    is_admin: bool = False


class AdminUserCreateRequest(BaseModel):
    """
    Provision an account. The route that removes the SSH step.

    A password may be supplied or generated. When generated it is returned
    exactly once, in the response, and never stored in plaintext or logged —
    the owner emails it on.
    """

    email: EmailStr
    display_name: str = Field(default="", max_length=120)
    access_tier: AccessTier = AccessTier.BASIC
    #: None leaves the field off the document entirely, so the tier default
    #: applies and keeps applying if the default is ever retuned.
    watchlist_cap: Optional[int] = Field(default=None, ge=0, le=2000)
    research_daily_allowed: bool = False
    #: Omit to have one generated. Twelve characters because the admin picks it
    #: and sends it over email, where it will live in two inboxes.
    password: Optional[str] = Field(default=None, min_length=12, max_length=200)


class AdminUserUpdateRequest(BaseModel):
    """Change a tier, a cap, or the nightly-research grant. All optional."""

    access_tier: Optional[AccessTier] = None
    watchlist_cap: Optional[int] = Field(default=None, ge=0, le=2000)
    #: True clears any per-user cap so the tier default applies again. Needed
    #: because `watchlist_cap: None` is indistinguishable from "not supplied".
    clear_watchlist_cap: bool = False
    research_daily_allowed: Optional[bool] = None


class AdminUserCreateResponse(BaseModel):
    """
    The created account, plus the password if this call generated one.

    `password` is populated only when the caller did not supply one, and only
    on this single response. There is no route that can read it back.
    """

    user: AdminUserRow
    password: Optional[str] = None


class AccessRequestRow(BaseModel):
    """One contact-form submission, as the admin queue shows it."""

    id: str
    name: str
    email: EmailStr
    message: str
    interest: Optional[str] = None
    created_at: Optional[datetime] = None


class AdminPasswordResetRequest(BaseModel):
    """
    Reset an account's password on the operator's say-so.

    No current password: the whole point is that nobody has it. Omit
    `password` to have one generated — which is the normal case, since the
    operator is about to email it.
    """

    password: Optional[str] = Field(default=None, min_length=12, max_length=200)


class AdminPasswordResetResponse(BaseModel):
    """
    The new password, returned once.

    Shown by the call that set it and readable from nowhere else. Every session
    that account had is already dead by the time this returns.
    """

    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    """
    A signed-in user changing their own password.

    `current_password` is required even though the caller already holds a valid
    token: a token can be stolen, and without this a stolen one could lock the
    real owner out of their own account permanently.
    """

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class ForgotPasswordRequest(BaseModel):
    """Ask for a reset link. The response never says whether the account exists."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Redeem a reset link. The token is single-use and short-lived."""

    token: str = Field(min_length=16, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)
