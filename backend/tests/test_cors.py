"""
The browser has to be allowed to send what the app serves.

A CORS allowlist that misses a verb does not fail like a bug. The endpoint
works from curl, passes every test that calls it directly, and is simply
unreachable from the browser — the preflight comes back 400 and the real
request is never sent, so the UI reports whatever its catch block says. That is
how `PATCH /admin/users/{id}` shipped able to change a plan from a terminal and
unable to from the Admin page.
"""
from app.main import app


def _cors_kwargs() -> dict:
    for middleware in app.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            return dict(middleware.kwargs)
    raise AssertionError("CORSMiddleware is not installed")


def _served_methods() -> set[str]:
    """Every verb the app's own route table answers, preflight aside."""
    methods: set[str] = set()
    for route in app.routes:
        methods |= (getattr(route, "methods", set()) or set())
    # HEAD is derived from GET and OPTIONS is what the middleware itself
    # answers; neither is something a client asks permission for.
    return methods - {"HEAD", "OPTIONS"}


def test_every_verb_the_app_serves_is_allowed_by_cors():
    """
    Enumerated from the app rather than hand-listed, so a route added with a
    new verb is covered the day it lands — which is exactly the case the
    hand-written list got wrong.
    """
    allowed = set(_cors_kwargs()["allow_methods"])
    if "*" in allowed:
        return  # a wildcard covers anything the table can grow

    missing = _served_methods() - allowed
    assert not missing, (
        f"{sorted(missing)} served but not in allow_methods — the browser "
        "preflight for those routes will be refused with a 400 and the real "
        "request never sent"
    )


def test_patch_is_allowed():
    """
    Named on its own because it is the one that broke, and because a regression
    here would silently take the whole Admin page's editing with it.
    """
    allowed = set(_cors_kwargs()["allow_methods"])
    assert "*" in allowed or "PATCH" in allowed


def test_credentials_are_allowed_so_the_bearer_token_survives_preflight():
    """
    Every authenticated request carries an Authorization header, which is not a
    simple header — so all of them are preflighted, not just the writes.
    """
    kwargs = _cors_kwargs()
    assert kwargs["allow_credentials"] is True
    assert "*" in kwargs["allow_headers"] or "authorization" in {
        h.lower() for h in kwargs["allow_headers"]
    }


# ── Exercised, not just read ──────────────────────────────────────────────────

def test_the_preflight_a_browser_actually_sends_is_accepted():
    """
    Reading `allow_methods` proves the config; sending the OPTIONS proves the
    middleware. This is the request that failed — a browser will not send the
    PATCH at all until this one comes back 200.
    """
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    for method, path in [
        ("PATCH", "/admin/users/000000000000000000000000"),
        ("POST", "/admin/users/000000000000000000000000/password"),
        ("PUT", "/auth/password"),
        ("POST", "/auth/forgot-password"),
        ("DELETE", "/settings/llm/keys/k1"),
    ]:
        res = client.options(path, headers={
            "Origin": "https://sta.samsbpm.com",
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        assert res.status_code == 200, f"{method} {path} preflight -> {res.status_code}"
        assert method in res.headers.get("access-control-allow-methods", "")
