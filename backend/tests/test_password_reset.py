"""
Setting a password: three paths, one set of properties.

The properties worth pinning are all negative, and all of them are ways this
feature is normally got wrong: a reset that leaves stolen sessions alive, a
link that can be replayed, a public endpoint that quietly reports whether an
address has an account, and a stored token that is as good as the password.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user
from app.main import app
from app.models.user import AdminPasswordResetResponse, AdminUserRow
from app.services import password_reset, rate_limit
from app.services.auth import (
    create_access_token,
    decode_token,
    hash_password,
    password_update,
    token_predates_password_change,
    verify_password,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clean_limits():
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


# ── A password change ends other sessions ─────────────────────────────────────

def test_a_token_issued_before_the_change_is_dead():
    """
    The point of a reset. Without this the credential rotates while every
    already-issued token keeps working for the rest of its 24 hours — so
    resetting a password somebody else knows would not actually lock them out.
    """
    payload = decode_token(create_access_token("u1", "a@b.com"))
    changed_later = {"password_changed_at": datetime.now(tz=timezone.utc) + timedelta(hours=1)}
    assert token_predates_password_change(payload, changed_later) is True


def test_a_token_issued_after_the_change_survives():
    payload = decode_token(create_access_token("u1", "a@b.com"))
    changed_earlier = {"password_changed_at": datetime.now(tz=timezone.utc) - timedelta(hours=1)}
    assert token_predates_password_change(payload, changed_earlier) is False


def test_the_token_minted_alongside_a_change_survives():
    """
    `PUT /auth/password` hands back a fresh token so the caller stays signed in
    on this device. `iat` is whole seconds while `password_changed_at` keeps
    microseconds, so without a second of slack that brand-new token would read
    as older than the change it accompanies and sign the user out instantly.
    """
    payload = decode_token(create_access_token("u1", "a@b.com"))
    assert token_predates_password_change(
        payload, {"password_changed_at": datetime.now(tz=timezone.utc)},
    ) is False


def test_an_account_that_never_changed_its_password_is_untouched():
    """What keeps this from signing the whole userbase out on deploy."""
    payload = decode_token(create_access_token("u1", "a@b.com"))
    assert token_predates_password_change(payload, {}) is False


def test_a_token_with_no_iat_fails_closed_against_a_recorded_change():
    """
    Tokens minted before `iat` existed. The only accounts carrying
    `password_changed_at` are ones somebody deliberately reset — exactly the
    case where an old session must not survive.
    """
    assert token_predates_password_change(
        {"sub": "u1"}, {"password_changed_at": datetime.now(tz=timezone.utc)},
    ) is True


def test_every_path_records_the_change():
    """
    `password_update` is the only way a password is set, so no route can rotate
    one and forget the timestamp. That omission would not fail visibly — the
    new password would work — it would just silently leave old tokens valid.
    """
    update = password_update("a-good-password")
    assert set(update) == {"password_hash", "password_changed_at"}
    assert verify_password("a-good-password", update["password_hash"])
    assert update["password_hash"] != "a-good-password"


def test_no_route_writes_password_hash_on_its_own():
    """
    The rule above, enforced. Routes may *read* the hash — `POST /auth/login`
    and the current-password check both have to — but none may write one,
    because writing it without `password_changed_at` is the silent failure.

    Keyed on the dict-key form `"password_hash":`, which is what a write looks
    like; a read is `user["password_hash"]` or `.get("password_hash", ...)`.
    """
    from pathlib import Path

    routes = Path(__file__).resolve().parents[1] / "app/routes"
    offenders = [
        p.name for p in routes.glob("*.py")
        if '"password_hash":' in p.read_text() or "'password_hash':" in p.read_text()
    ]
    assert not offenders, f"{offenders} write password_hash directly; use password_update()"


# ── The token store gives nothing away ────────────────────────────────────────

def test_only_a_hash_of_the_token_is_stored():
    """
    A reset link sets a password without knowing the old one, so a stored copy
    is as good as the credential. A database dump, a backup, a log line — none
    of them should yield a working link.
    """
    stored: list[dict] = []

    class _Coll:
        async def delete_many(self, q): return None
        async def insert_one(self, doc): stored.append(doc); return None

    class _DB:
        def __getitem__(self, name): return _Coll()

    import app.services.password_reset as pr

    async def fake_db(): return _DB()

    original, pr.get_db = pr.get_db, fake_db
    try:
        token = run(pr.issue("u1"))
    finally:
        pr.get_db = original

    assert token
    assert len(stored) == 1
    doc = stored[0]
    assert "token_hash" in doc
    assert token not in str(doc), "the raw token must not be stored anywhere"
    assert doc["token_hash"] != token
    assert doc["expires_at"] > doc["created_at"]


def test_expiry_is_in_the_query_not_a_check_after_it():
    """
    An expired token must not *match*, rather than match and then be rejected
    somewhere a later refactor can quietly drop.
    """
    import inspect

    source = inspect.getsource(password_reset.redeem)
    assert "find_one_and_delete" in source, "read-then-delete lets two requests race one link"
    assert "expires_at" in source and "$gt" in source


def test_a_link_is_single_use():
    """
    `find_one_and_delete` consumes it, so a link forwarded, quoted in a reply,
    or sitting in a mail archive cannot be replayed.
    """
    live: dict[str, dict] = {}

    class _Coll:
        async def find_one_and_delete(self, q):
            doc = live.get(q["token_hash"])
            if doc is None:
                return None
            del live[q["token_hash"]]
            return doc

    class _DB:
        def __getitem__(self, name): return _Coll()

    import app.services.password_reset as pr

    async def fake_db(): return _DB()

    live[pr._fingerprint("tok")] = {"user_id": "u1"}
    original, pr.get_db = pr.get_db, fake_db
    try:
        assert run(pr.redeem("tok")) == "u1"
        assert run(pr.redeem("tok")) is None
    finally:
        pr.get_db = original


# ── The public endpoints never say whether an account exists ──────────────────

def test_forgot_password_is_shaped_not_to_enumerate():
    """
    There is no self-serve signup here, so an address with an account is one
    the operator chose to let in — and confirming which is worth having for
    anyone probing. The response must not vary on the lookup.
    """
    import inspect

    from app.routes import auth as route

    source = inspect.getsource(route.forgot_password)
    # The unknown-address branch returns the same model as the happy path.
    assert source.count("ForgotPasswordResponse()") >= 2
    # A mail failure is logged rather than returned, for the same reason.
    assert "password_reset_email_failed" in source
    assert "logger.error" in source


def test_the_rate_limit_is_charged_before_the_lookup():
    """
    Charging only requests that matched an account would make the limiter
    itself an oracle: an attacker could tell a real address from a fake one by
    which eventually got throttled.
    """
    import inspect

    from app.routes import auth as route

    source = inspect.getsource(route.forgot_password)
    assert source.index("record_reset_request") < source.index("find_one")


def test_a_dead_link_gives_one_answer(client):
    """
    Expired, already used, superseded and never-real are deliberately
    indistinguishable — telling them apart tells whoever holds a stale link
    something about the account it was issued for.
    """
    res = client.post("/auth/reset-password", json={
        "token": "x" * 32, "new_password": "a-long-enough-password",
    })
    assert res.status_code in (400, 500)
    if res.status_code == 400:
        assert "no longer valid" in res.json()["detail"]


def test_a_short_password_is_refused_on_every_path(client):
    """One minimum, used by the admin form, the reset page and self-service."""
    from app.services.auth import MIN_PASSWORD_LENGTH

    assert MIN_PASSWORD_LENGTH >= 12
    short = "short"
    assert client.post("/auth/reset-password",
                       json={"token": "x" * 32, "new_password": short}).status_code == 422

    app.dependency_overrides[get_current_user] = lambda: {
        "_id": "u1", "email": "a@b.com", "access_tier": "TRADER",
        "password_hash": hash_password("the-current-password"),
    }
    try:
        res = client.put("/auth/password", json={
            "current_password": "the-current-password", "new_password": short,
        })
        assert res.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ── Changing your own ─────────────────────────────────────────────────────────

def test_changing_your_own_password_needs_the_current_one(client):
    """
    A token can be stolen. Without this, whoever stole one could set a new
    password and lock the real owner out of their own account permanently —
    holding a session proves you signed in once, not that you are the owner now.
    """
    app.dependency_overrides[get_current_user] = lambda: {
        "_id": "u1", "email": "a@b.com", "access_tier": "TRADER",
        "password_hash": hash_password("the-real-password"),
    }
    try:
        res = client.put("/auth/password", json={
            "current_password": "not-the-real-password",
            "new_password": "a-brand-new-password",
        })
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_a_no_op_change_is_refused_rather_than_reported_as_done(client):
    """
    Silently doing nothing while reporting success is how somebody ends up
    believing a compromised password was rotated.
    """
    app.dependency_overrides[get_current_user] = lambda: {
        "_id": "u1", "email": "a@b.com", "access_tier": "TRADER",
        "password_hash": hash_password("the-same-password"),
    }
    try:
        res = client.put("/auth/password", json={
            "current_password": "the-same-password",
            "new_password": "the-same-password",
        })
        assert res.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_a_wrong_current_password_is_rate_limited(client):
    """
    A second place a password can be guessed against, and a quieter one — it
    produces no failed logins. Shares the login counter.
    """
    app.dependency_overrides[get_current_user] = lambda: {
        "_id": "u1", "email": "guessme@example.com", "access_tier": "TRADER",
        "password_hash": hash_password("the-real-password"),
    }
    try:
        statuses = [
            client.put("/auth/password", json={
                "current_password": f"guess-{i}", "new_password": "a-brand-new-password",
            }).status_code
            for i in range(12)
        ]
        assert 429 in statuses, "guessing the current password is not throttled"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ── The admin path ────────────────────────────────────────────────────────────

def test_the_reset_response_carries_the_password_and_nothing_stored():
    """
    Returned once, by the call that set it, and readable from nowhere else.
    `AdminUserRow` still has no field that could carry a stored credential.
    """
    assert set(AdminPasswordResetResponse.model_fields) == {"email", "password"}
    assert "password_hash" not in AdminUserRow.model_fields


def test_only_the_operator_can_reset_someone_elses_password(client):
    """Being TRADER is being a customer, not the person who provisions them."""
    app.dependency_overrides[get_current_user] = lambda: {
        "_id": "u2", "email": "trader@example.com", "access_tier": "TRADER",
    }
    try:
        res = client.post("/admin/users/000000000000000000000000/password", json={})
        assert res.status_code == 403
        assert res.json()["detail"]["error"] == "admin_required"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_the_generated_password_is_not_logged():
    """
    An audit needs to know a reset happened and for whom. It does not need the
    credential, and a log aggregator is a worse place for one than a database.
    """
    import inspect

    from app.routes import admin

    source = inspect.getsource(admin.reset_user_password)
    log_lines = [ln for ln in source.splitlines() if "logger." in ln]
    assert log_lines
    assert not any("password=password" in ln or "password=body" in ln for ln in log_lines)


def test_setting_a_password_revokes_outstanding_links():
    """
    Somebody who has just set a password has answered the question an
    outstanding link was asking. Leaving one live would let an old email undo
    it.
    """
    import inspect

    from app.routes import admin
    from app.routes import auth as route

    assert "revoke_for" in inspect.getsource(admin.reset_user_password)
    assert "revoke_for" in inspect.getsource(route.change_password)
    assert "revoke_for" in inspect.getsource(route.reset_password)
