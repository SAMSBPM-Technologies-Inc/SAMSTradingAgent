"""
Which login the broker session is running as.

`GET /trading/broker/status` answers "which account did that order reach" — the
first question any surprising fill raises, and previously answerable only by
opening a shell on the VPS and reading `.env.production`.

The property worth pinning is not that the username is echoed back. It is the
distinction between *blank* and *unknown*: a bare-metal gateway logged in by
hand sets no environment variable, and "this server cannot tell you" is a
different fact from an empty username. Reported as `None`, the client can say
so; reported as `""`, the panel renders a gap that reads like a bug. The same
absent-is-not-blank rule `source_health` draws between `not_configured` and
`failed`.
"""
import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user
from app.main import app
import app.routes.trading as trading

TRADER = {"_id": "u-trader", "email": "trader@example.com", "access_tier": "TRADER"}


class _Env:
    """Only the fields `broker_status` reads, so the stub cannot drift silently."""

    ibkr_host = "127.0.0.1"
    ibkr_port = 4004
    is_live_trading = False

    def __init__(self, tws_userid: str):
        self.tws_userid = tws_userid


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def as_trader():
    """The route is behind the plan check; this is a user entitled to pass it."""
    app.dependency_overrides[get_current_user] = lambda: TRADER
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _status(client, monkeypatch, userid: str) -> dict:
    monkeypatch.setattr(trading, "get_env_settings", lambda: _Env(userid))
    response = client.get("/trading/broker/status")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_login_behind_the_session_is_reported(client, monkeypatch):
    assert _status(client, monkeypatch, "samsbpm123")["gateway_username"] == "samsbpm123"


@pytest.mark.parametrize("unset", ["", "   "])
def test_an_unknown_login_is_absent_rather_than_blank(client, monkeypatch, unset):
    """
    The whole point of the field. An unset variable and a whitespace-only one
    both mean this process cannot know, and both must read as `None` so the UI
    labels it instead of rendering an empty line.
    """
    assert _status(client, monkeypatch, unset)["gateway_username"] is None


def test_the_password_has_no_field_anywhere_in_the_api_process(client, monkeypatch):
    """
    Nothing here reads TWS_PASSWORD — the gateway does. If a field for it is
    ever added to Settings, this route becomes a way to leak it, so the absence
    is asserted rather than assumed.
    """
    from app.config import Settings

    assert "tws_password" not in Settings.model_fields
    assert "password" not in " ".join(_status(client, monkeypatch, "u1")).lower()
