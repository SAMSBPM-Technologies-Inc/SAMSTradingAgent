"""
The provisioning surface.

Two properties carry most of the weight here: admin is not a tier, and no
response on this router can carry a credential.
"""
import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user
from app.main import app
from app.models.user import AdminUserCreateResponse, AdminUserRow
from app.services.auth import new_user_document
from app.models.user import AccessTier

ADMIN = {"_id": "u-admin", "email": "sudheer.samudrala@samspm.com", "access_tier": "BASIC"}
TRADER = {"_id": "u-trader", "email": "trader@example.com", "access_tier": "TRADER"}


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def as_user():
    def _set(user: dict):
        app.dependency_overrides[get_current_user] = lambda: user
    yield _set
    app.dependency_overrides.pop(get_current_user, None)


# ── Admin is not a tier ───────────────────────────────────────────────────────

def test_the_highest_tier_is_refused(client, as_user):
    """
    Being TRADER is being a customer, not the person who provisions them. If
    this ever passes, every paying user can change every other user's plan.
    """
    as_user(TRADER)
    for method, path in [("GET", "/admin/users"),
                         ("POST", "/admin/users"),
                         ("PATCH", "/admin/users/000000000000000000000000"),
                         ("GET", "/admin/access-requests")]:
        res = client.request(method, path, json={})
        assert res.status_code == 403, f"{method} {path}"
        assert res.json()["detail"]["error"] == "admin_required"


def test_the_configured_address_is_not_refused(client, as_user):
    """`!= 403` — past the guard these want a database, which is not running."""
    as_user(ADMIN)
    assert client.get("/admin/users").status_code != 403


def test_a_case_different_address_still_matches(client, as_user):
    as_user({**ADMIN, "email": "SUDHEER.SAMUDRALA@SAMSPM.COM"})
    assert client.get("/admin/users").status_code != 403


# ── No response here can carry a credential ───────────────────────────────────

def test_no_admin_response_model_can_hold_a_secret():
    """
    A type-level guarantee, not a `del` before serialising. The latter is one
    forgotten line away from leaking every credential on the system, and this
    codebase has already had a field silently dropped by Pydantic and go
    unnoticed for a release — the same mechanism, in the other direction.

    `AdminUserCreateResponse.password` is the single deliberate exception: it
    carries a password this call just generated, once, and no route can read it
    back.
    """
    forbidden = {"password_hash", "ciphertext", "api_key", "llm_settings"}
    assert not (set(AdminUserRow.model_fields) & forbidden)
    assert not (set(AdminUserCreateResponse.model_fields) & forbidden)
    assert set(AdminUserCreateResponse.model_fields) == {"user", "password"}


# ── The two account writers agree ─────────────────────────────────────────────

def test_a_new_account_defaults_to_the_smallest_plan():
    doc = new_user_document(email="a@b.com", password="x" * 12)
    assert doc["access_tier"] == AccessTier.BASIC.value
    assert doc["research_daily_allowed"] is False


def test_an_omitted_cap_is_not_written_as_null():
    """
    The tier default must keep applying — including if it is ever retuned. A
    stored copy of today's number would freeze it per account, silently.
    """
    assert "watchlist_cap" not in new_user_document(email="a@b.com", password="x" * 12)
    doc = new_user_document(email="a@b.com", password="x" * 12, watchlist_cap=7)
    assert doc["watchlist_cap"] == 7


def test_the_cli_and_the_api_build_the_same_shape():
    """
    Both writers go through one builder, so a field added to one cannot be
    missed by the other — and a missing `access_tier` would read as BASIC,
    making the drift look like an account granted less than it was.
    """
    import inspect
    from pathlib import Path

    from app.routes import admin

    script = (Path(__file__).resolve().parents[1] / "scripts/create_user.py").read_text()
    assert "new_user_document" in script
    assert "new_user_document" in inspect.getsource(admin.create_user)


def test_the_password_alphabet_avoids_ambiguous_characters():
    """It gets read off a screen and typed by hand at least once."""
    from app.services.auth import generate_password

    assert not (set(generate_password(200)) & set("l1IO0"))
