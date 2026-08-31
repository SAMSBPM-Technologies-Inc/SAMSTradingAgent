"""
What each access tier may do — the one table, and a pure function over it.

Every gate in this system reads from `_TIER_CAPABILITIES` below. Four rules
hold it together, and all four are the reason the previous numeric tier system
became impossible to reason about:

**Routes name capabilities, never tiers.** No route module may contain the
string "PRO". A route that asks `may_trade` keeps working when the table
changes; a route that asks `tier == PRO` has quietly become a second, competing
copy of the policy. Same discipline `system_status.py` holds for its
capability/impact table and `explain_score` holds for the weights.

**Nothing compares tiers by order.** The three happen to form a ladder today —
BASIC ⊂ PRO ⊂ TRADER — and that is a fact about the current table, not a rule.
`tier >= X` is the numeric ladder coming back through the side door.

**`entitlements_for` never raises.** An unknown string, a missing field, a
`None` — all resolve to BASIC. This runs on every authenticated request through
`get_current_user`, so a `KeyError` here is a 500 on every route at once.

**Absence resolves to BASIC, not to the tier the account probably had.** That is
the opposite of what `db._migrate_access_tier` writes, and deliberately so: the
migration exists to give every *existing* account TRADER explicitly, because
they were all provisioned with every feature. A document still missing the field
after that has been hand-inserted or written by a bug, and the safe reading of a
bug is the smallest one.

Admin is orthogonal to tier: the configured admin address always resolves to
TRADER capabilities, whatever the document says.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import get_settings
from app.models.user import AccessTier, EntitlementsResponse


@dataclass(frozen=True)
class Entitlements:
    """
    The resolved answer for one user.

    `watchlist_cap` is `None` for unlimited. Zero is a real cap — an admin may
    set it — so "no cap" and "cap of nothing" must stay distinguishable, the
    same reason a commission the venue has not reported stays `None` rather
    than `0.0`.
    """

    tier: AccessTier
    may_trade: bool
    may_spend_tokens: bool
    may_bring_own_key: bool
    may_use_server_key: bool
    may_enrol_in_nightly_research: bool
    watchlist_cap: Optional[int]

    def has(self, capability: str) -> bool:
        """Read one boolean capability by name. Unknown names are False."""
        value = getattr(self, capability, False)
        return bool(value) if isinstance(value, bool) else False

    def to_response(self) -> EntitlementsResponse:
        return EntitlementsResponse(
            tier=self.tier,
            may_trade=self.may_trade,
            may_spend_tokens=self.may_spend_tokens,
            may_bring_own_key=self.may_bring_own_key,
            may_use_server_key=self.may_use_server_key,
            may_enrol_in_nightly_research=self.may_enrol_in_nightly_research,
            watchlist_cap=self.watchlist_cap,
        )


@dataclass(frozen=True)
class _Capabilities:
    """The static half of a tier. Caps and grants are layered on top."""

    may_trade: bool
    may_spend_tokens: bool
    may_bring_own_key: bool
    may_use_server_key: bool
    #: True  — always enrolable. False — never. None — only on an admin grant.
    nightly_research: Optional[bool]


#: The single source. A new member of `AccessTier` with no entry here fails a
#: test rather than silently resolving to whatever `.get` returned.
_TIER_CAPABILITIES: dict[AccessTier, _Capabilities] = {
    AccessTier.BASIC: _Capabilities(
        may_trade=False,
        may_spend_tokens=False,
        may_bring_own_key=False,
        may_use_server_key=False,
        nightly_research=False,
    ),
    AccessTier.PRO: _Capabilities(
        may_trade=False,
        may_spend_tokens=True,
        may_bring_own_key=True,
        # PRO spends its own key and only its own. `llm/resolver.build_chain`
        # otherwise appends the deployment's key to every chain, so a PRO user
        # who configured nothing — or whose key just failed — would silently
        # bill the owner for five to seven model calls per dossier.
        may_use_server_key=False,
        # Five to seven calls per ticker per day, unattended, is the one number
        # in this system that runs away. Enrolable only where the admin has
        # said so for that specific account.
        nightly_research=None,
    ),
    AccessTier.TRADER: _Capabilities(
        may_trade=True,
        may_spend_tokens=True,
        may_bring_own_key=True,
        may_use_server_key=True,
        nightly_research=True,
    ),
}

#: The tiers whose users the nightly research job may reach at all. Built from
#: the table so a Mongo query cannot drift from the policy — and used with
#: `$in` rather than `$ne`, because `$ne` also matches documents where the
#: field is *absent*, which is every account that predates the migration.
ENROLABLE_TIERS: list[str] = [
    tier.value
    for tier, caps in _TIER_CAPABILITIES.items()
    if caps.nightly_research is not False
]


def tier_of(user: Optional[dict]) -> AccessTier:
    """This user's tier. Anything unrecognised is BASIC, and never a raise."""
    raw = (user or {}).get("access_tier")
    if isinstance(raw, AccessTier):
        return raw
    try:
        return AccessTier(str(raw).strip().upper())
    except (ValueError, AttributeError, TypeError):
        return AccessTier.BASIC


def is_admin(user: Optional[dict]) -> bool:
    """
    Whether this account is the operator.

    Admin comes from `ADMIN_EMAIL` in config, not from a field on the document.
    A document field would create a privilege-escalation path *through the
    admin route itself* — one careless `$set` of a request body and an editable
    field becomes an admin-granting field. With no such field, that whole class
    of bug cannot exist, and the value cannot be changed by anything holding
    only database write access.

    An unset `ADMIN_EMAIL` makes nobody admin. A user's email is never empty
    (unique index, `EmailStr`), so the empty case fails closed rather than
    matching everyone. `main._check_admin_email` reports that state loudly on
    startup, because being *silently* locked out of provisioning is the failure
    worth engineering against.
    """
    configured = (get_settings().admin_email or "").strip().lower()
    if not configured:
        return False
    allowed = {part.strip() for part in configured.split(",") if part.strip()}
    email = str((user or {}).get("email") or "").strip().lower()
    return bool(email) and email in allowed


def _resolve_cap(user: dict, tier: AccessTier) -> Optional[int]:
    """
    The effective watchlist cap: per-user override, else the tier default.

    An integer override wins even on TRADER — an admin capping a trader is a
    feature, not a leak. Negatives clamp to zero rather than being ignored, so a
    typo cannot read as "unlimited".
    """
    override = user.get("watchlist_cap")
    if isinstance(override, bool):
        override = None  # bools are ints in Python; a True cap is a bug
    if isinstance(override, int):
        return max(0, override)

    settings = get_settings()
    if tier is AccessTier.BASIC:
        return max(0, settings.tier_watchlist_cap_basic)
    if tier is AccessTier.PRO:
        return max(0, settings.tier_watchlist_cap_pro)
    return None


def entitlements_for(user: Optional[dict]) -> Entitlements:
    """
    Resolve one user document to what it may do. Total, and never raises.

    The document is already in hand on every authenticated request —
    `get_current_user` loads it — which is why none of this is in the JWT. A
    token claim would save no query and would be stale for the token's whole
    24-hour life, so an admin downgrade would take effect whenever the user
    next happened to sign in. For a control whose entire purpose is to stop
    spending now, that is the wrong direction.
    """
    doc = user or {}
    tier = tier_of(doc)

    if is_admin(doc):
        # The operator's own capabilities do not depend on how their account
        # document happens to be provisioned.
        tier = AccessTier.TRADER

    caps = _TIER_CAPABILITIES[tier]

    nightly = caps.nightly_research
    if nightly is None:
        nightly = bool(doc.get("research_daily_allowed"))

    return Entitlements(
        tier=tier,
        may_trade=caps.may_trade,
        may_spend_tokens=caps.may_spend_tokens,
        may_bring_own_key=caps.may_bring_own_key,
        may_use_server_key=caps.may_use_server_key,
        may_enrol_in_nightly_research=nightly,
        watchlist_cap=_resolve_cap(doc, tier),
    )
