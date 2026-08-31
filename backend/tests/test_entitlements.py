"""
The capability table, and the four rules that keep it honest.

Pure — no app, no database, no event loop. `entitlements_for` runs on every
authenticated request, so the properties worth pinning are the total ones: it
answers for any input, it never raises, and an unclassified document gets the
smallest answer rather than the most convenient one.
"""
import pytest

from app.models.user import AccessTier
from app.services.entitlements import (
    ENROLABLE_TIERS,
    _TIER_CAPABILITIES,
    entitlements_for,
    is_admin,
    tier_of,
)

SPENDING = ("may_trade", "may_spend_tokens", "may_bring_own_key",
            "may_use_server_key", "may_enrol_in_nightly_research")


# ── The table is complete ─────────────────────────────────────────────────────

@pytest.mark.parametrize("tier", list(AccessTier))
def test_every_tier_has_capabilities(tier):
    """
    A new tier cannot be added without deciding what it may do.

    Parametrised over the enum rather than listing the three by hand, so adding
    a fourth member fails here instead of silently resolving to whatever a
    `.get` returned.
    """
    assert tier in _TIER_CAPABILITIES


@pytest.mark.parametrize("tier", list(AccessTier))
def test_entitlements_resolve_for_every_tier(tier):
    ent = entitlements_for({"access_tier": tier.value})
    assert ent.tier is tier


# ── Absence and nonsense resolve to the smallest answer ───────────────────────

def test_missing_tier_is_basic():
    """
    A document with no `access_tier` is read as BASIC, not as the tier it
    probably had. `db._migrate_access_tier` is what writes TRADER onto the
    accounts that predate the field; anything still missing it afterwards was
    hand-inserted or written by a bug, and the safe reading of a bug is small.
    """
    ent = entitlements_for({})
    assert ent.tier is AccessTier.BASIC
    for capability in SPENDING:
        assert getattr(ent, capability) is False


@pytest.mark.parametrize("raw", ["nonsense", "", None, 2, "trader ", "Pro"])
def test_unknown_tier_never_raises(raw):
    """
    This runs inside `get_current_user`'s path on every authenticated request.
    A raise here is a 500 on every route at once, so unrecognised input must
    resolve rather than fail — and resolve downward.
    """
    tier = tier_of({"access_tier": raw})
    assert isinstance(tier, AccessTier)
    if raw in ("trader ", "Pro"):
        # Whitespace and case are typing, not intent.
        assert tier in (AccessTier.TRADER, AccessTier.PRO)
    else:
        assert tier is AccessTier.BASIC


def test_entitlements_for_none_is_basic():
    assert entitlements_for(None).tier is AccessTier.BASIC


# ── Who may do what ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier", list(AccessTier))
def test_only_trader_may_trade(tier):
    """
    Asserted positively for every tier, so a table edit that hands trading to
    PRO fails a test rather than depending on someone noticing in review.
    Behind /trading is one shared brokerage account.
    """
    ent = entitlements_for({"access_tier": tier.value})
    assert ent.may_trade is (tier is AccessTier.TRADER)


def test_basic_cannot_spend_or_bring_a_key():
    ent = entitlements_for({"access_tier": "BASIC"})
    assert ent.may_spend_tokens is False
    assert ent.may_bring_own_key is False
    assert ent.may_use_server_key is False


def test_pro_spends_only_its_own_key():
    """
    The whole point of the PRO tier's economics. `build_chain` otherwise
    appends the deployment's key to every chain, so a PRO user who configured
    nothing would bill the operator for every dossier.
    """
    ent = entitlements_for({"access_tier": "PRO"})
    assert ent.may_spend_tokens is True
    assert ent.may_bring_own_key is True
    assert ent.may_use_server_key is False


def test_trader_may_use_the_server_key():
    assert entitlements_for({"access_tier": "TRADER"}).may_use_server_key is True


# ── The nightly-research grant ────────────────────────────────────────────────

def test_pro_needs_an_admin_grant_for_nightly_research():
    """Five to seven model calls per ticker per day, unattended — off by default."""
    assert entitlements_for({"access_tier": "PRO"}).may_enrol_in_nightly_research is False
    granted = entitlements_for({"access_tier": "PRO", "research_daily_allowed": True})
    assert granted.may_enrol_in_nightly_research is True


def test_a_grant_does_not_help_basic():
    """The grant unlocks a PRO capability; it is not a back door into one."""
    ent = entitlements_for({"access_tier": "BASIC", "research_daily_allowed": True})
    assert ent.may_enrol_in_nightly_research is False


def test_enrolable_tiers_excludes_basic():
    """
    The list the scheduler's Mongo filter is built from. It must be `$in` over
    these rather than `$ne: "BASIC"` — `$ne` also matches documents where the
    field is *absent*, which is every account predating the migration.
    """
    assert "BASIC" not in ENROLABLE_TIERS
    assert set(ENROLABLE_TIERS) == {"PRO", "TRADER"}


# ── The watchlist cap ─────────────────────────────────────────────────────────

def test_tier_defaults():
    assert entitlements_for({"access_tier": "BASIC"}).watchlist_cap == 5
    assert entitlements_for({"access_tier": "PRO"}).watchlist_cap == 15
    assert entitlements_for({"access_tier": "TRADER"}).watchlist_cap is None


def test_per_user_override_wins_including_on_trader():
    """An admin capping a trader is a feature, not a leak."""
    assert entitlements_for({"access_tier": "PRO", "watchlist_cap": 3}).watchlist_cap == 3
    assert entitlements_for({"access_tier": "TRADER", "watchlist_cap": 2}).watchlist_cap == 2


def test_absent_override_falls_back_to_the_tier_default():
    assert entitlements_for({"access_tier": "PRO", "watchlist_cap": None}).watchlist_cap == 15


def test_zero_is_a_real_cap_not_an_absence():
    """`None` means unlimited; zero means nothing. They must stay distinct."""
    assert entitlements_for({"access_tier": "TRADER", "watchlist_cap": 0}).watchlist_cap == 0


def test_a_negative_override_clamps_rather_than_reading_as_unlimited():
    assert entitlements_for({"access_tier": "PRO", "watchlist_cap": -4}).watchlist_cap == 0


def test_a_boolean_override_is_ignored():
    """`True` is an `int` in Python; a boolean here is a bug, not a cap of one."""
    assert entitlements_for({"access_tier": "PRO", "watchlist_cap": True}).watchlist_cap == 15


# ── Admin ─────────────────────────────────────────────────────────────────────

def test_admin_is_matched_case_insensitively(monkeypatch):
    import app.services.entitlements as ents

    class _S:
        admin_email = "  Owner@Example.com "
        tier_watchlist_cap_basic = 5
        tier_watchlist_cap_pro = 15

    monkeypatch.setattr(ents, "get_settings", lambda: _S())
    assert is_admin({"email": "owner@example.com"}) is True
    assert is_admin({"email": "OWNER@EXAMPLE.COM"}) is True
    assert is_admin({"email": "someone@example.com"}) is False


def test_admin_gets_trader_capabilities_whatever_the_document_says(monkeypatch):
    import app.services.entitlements as ents

    class _S:
        admin_email = "owner@example.com"
        tier_watchlist_cap_basic = 5
        tier_watchlist_cap_pro = 15

    monkeypatch.setattr(ents, "get_settings", lambda: _S())
    ent = entitlements_for({"email": "owner@example.com", "access_tier": "BASIC"})
    assert ent.tier is AccessTier.TRADER
    assert ent.may_trade is True
    assert ent.watchlist_cap is None


def test_an_unset_admin_email_makes_nobody_admin(monkeypatch):
    """
    Fails closed. A user's email is never empty — unique index, `EmailStr` — so
    an empty configured value must not match everyone. `main._check_admin_email`
    is what makes this state loud rather than silent.
    """
    import app.services.entitlements as ents

    class _S:
        admin_email = ""
        tier_watchlist_cap_basic = 5
        tier_watchlist_cap_pro = 15

    monkeypatch.setattr(ents, "get_settings", lambda: _S())
    assert is_admin({"email": "anyone@example.com"}) is False
    assert is_admin({"email": ""}) is False


def test_has_reads_booleans_by_name_and_ignores_the_cap():
    """`has()` is the dependency factory's reader; a cap is not a capability."""
    ent = entitlements_for({"access_tier": "TRADER"})
    assert ent.has("may_trade") is True
    assert ent.has("watchlist_cap") is False
    assert ent.has("no_such_capability") is False


# ── The chain a tier resolves to ──────────────────────────────────────────────

def test_withholding_the_server_key_leaves_only_the_users_own():
    """
    What makes the PRO tier's economics real. Without this the deployment's key
    is appended to every chain, so an account that pays for its own tokens
    silently bills the operator whenever it has configured nothing — or
    whenever its own key rate-limits partway through a dossier.
    """
    from app.services.llm.resolver import build_chain

    settings = {
        "keys": [{"id": "k1", "provider": "anthropic", "ciphertext": ""}],
        "roles": {"specialist": [{"key_id": "k1", "model": "claude-sonnet-5"}]},
    }
    withheld = build_chain(settings, "specialist", allow_server_key=False)
    assert all(c.key_id is not None for c in withheld)


def test_the_default_still_appends_the_server_key():
    """
    Every caller with no user behind it keeps the old behaviour — in particular
    the pipeline's analyst call, which writes one shared document per ticker and
    belongs to the deployment however it was triggered.
    """
    import app.services.llm.resolver as resolver
    from app.services.llm.base import Candidate

    original = resolver.server_candidate
    resolver.server_candidate = lambda role: Candidate(
        provider="anthropic", model="m", api_key="server", key_id=None)
    try:
        chain = resolver.build_chain(None, "specialist")
        assert [c.key_id for c in chain] == [None]
        assert resolver.build_chain(None, "specialist", allow_server_key=False) == []
    finally:
        resolver.server_candidate = original
