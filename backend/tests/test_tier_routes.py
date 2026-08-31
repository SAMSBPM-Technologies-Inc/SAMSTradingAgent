"""
What each tier can actually reach, asserted against the app's own route table.

The positive half matters as much as the negative one: a gate that refuses
everything is not a gate, it is an outage. So every "403 for BASIC" here has a
matching "not 403 for the tier that should have it".

`TestClient(app)` without a `with` block does not run the lifespan, so nothing
connects to Mongo — and the capability dependencies refuse before any handler
body runs, so a refused request never needs a database at all. The same trick
`tests/test_contact.py` already uses.
"""
import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user
from app.main import app

BASIC = {"_id": "u-basic", "email": "basic@example.com", "access_tier": "BASIC"}
PRO = {"_id": "u-pro", "email": "pro@example.com", "access_tier": "PRO"}
TRADER = {"_id": "u-trader", "email": "trader@example.com", "access_tier": "TRADER"}
#: A document written before `access_tier` existed. `db._migrate_access_tier`
#: gives these TRADER explicitly; until it runs they read as BASIC.
UNMIGRATED = {"_id": "u-old", "email": "old@example.com"}


@pytest.fixture
def client():
    """
    `raise_server_exceptions=False` so a handler that runs and then fails for
    its own reasons comes back as a 500 rather than propagating. That is the
    normal outcome for the allowed half of these tests: past the guard, most
    trading handlers want a database and a broker session, and neither exists
    here. A 500 is therefore evidence the request got *through* the plan check.
    """
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def as_user():
    """Sign in as an arbitrary user document, with no token and no database."""
    def _set(user: dict):
        app.dependency_overrides[get_current_user] = lambda: user
    yield _set
    app.dependency_overrides.pop(get_current_user, None)


def _trading_routes() -> list[tuple[str, str]]:
    """Every (method, path) the app actually serves under /trading."""
    out: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/trading"):
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            out.append((method, path))
    return sorted(out)


def _call(client: TestClient, method: str, path: str):
    """Fire a request at a route with placeholder path params and no body."""
    url = path.replace("{ticker}", "AAPL").replace("{proposal_id}", "000000000000000000000000")
    return client.request(method, url, json={})


# ── Trading: the whole surface, enumerated ────────────────────────────────────

def test_the_route_table_is_not_empty():
    """
    Guards the enumeration itself. Without this, a change that broke route
    collection would make every test below pass vacuously — and the thing they
    protect is the operator's single shared brokerage account.
    """
    routes = _trading_routes()
    assert len(routes) >= 15, f"only found {len(routes)} trading routes: {routes}"


@pytest.mark.parametrize("method,path", _trading_routes())
@pytest.mark.parametrize("user,label", [(BASIC, "basic"), (PRO, "pro"), (UNMIGRATED, "unmigrated")])
def test_no_trading_route_is_reachable_without_the_plan(client, as_user, method, path, user, label):
    """
    Enumerated from the app rather than hand-listed, so route sixteen is covered
    the day it is added. A hand-written list of fifteen paths is exactly what
    goes stale — and here staleness means a PRO account reading the operator's
    balances or restarting their IB Gateway container.
    """
    as_user(user)
    res = _call(client, method, path)
    assert res.status_code == 403, f"{method} {path} returned {res.status_code} for {label}"
    detail = res.json()["detail"]
    assert detail["capability"] == "may_trade"
    assert detail["error"] == "tier_required"


@pytest.mark.parametrize("method,path", _trading_routes())
def test_trading_routes_are_not_plan_refused_for_a_trader(client, as_user, method, path):
    """
    `!= 403`, not `== 200`: past the guard these want a database and a live
    broker session, so they 500 here. What is being asserted is only that the
    *plan* is not what stopped them — which is the half that would go missing
    if a gate were written as "refuse everyone".
    """
    as_user(TRADER)
    res = _call(client, method, path)
    assert res.status_code != 403, f"{method} {path} refused a TRADER"


# ── Every refusal is machine-readable ─────────────────────────────────────────

def test_refusals_carry_a_capability_and_a_sentence(client, as_user):
    """
    One shape, so all three clients parse one thing. This is a structured
    `detail` where every pre-existing route on this API raises a plain string,
    which is why the shared client helper has to read both.
    """
    as_user(BASIC)
    detail = client.get("/trading/settings").json()["detail"]
    assert set(detail) >= {"error", "capability", "tier", "message"}
    assert detail["tier"] == "BASIC"
    assert isinstance(detail["message"], str) and detail["message"].strip()


# ── Research: the free verb and the expensive one ─────────────────────────────

def test_building_a_dossier_is_refused_without_the_plan(client, as_user):
    as_user(BASIC)
    res = client.post("/research/AAPL")
    assert res.status_code == 403
    assert res.json()["detail"]["capability"] == "may_spend_tokens"


def test_the_plan_is_reported_before_the_deployment_flag(client, as_user, monkeypatch):
    """
    A reader on a deployment with `RESEARCH_AGENTS_ENABLED=false` must be told
    about their plan, not about an environment variable. The flag is not their
    problem and naming it leaks configuration to somebody who could not act on
    it. This falls out of the dependency running before the handler body, so
    the test is really pinning that ordering.
    """
    import app.routes.research as research

    class _S:
        research_agents_enabled = False

    monkeypatch.setattr(research, "get_settings", lambda: _S())
    as_user(BASIC)
    assert client.post("/research/AAPL").status_code == 403


@pytest.mark.parametrize("user", [BASIC, PRO, TRADER])
def test_reading_a_dossier_is_never_plan_refused(client, as_user, user):
    """
    Free stored reads. `/veto` in particular must never refuse — a client that
    has to treat a missing or refused veto as a failure is the opposite of how
    the guard itself behaves.
    """
    as_user(user)
    assert client.get("/research/AAPL").status_code != 403
    assert client.get("/research/AAPL/veto").status_code != 403


def test_pro_without_a_key_is_told_before_the_ledger_is_built(client, as_user):
    """
    PRO runs on its own key and has no fallback to the deployment's. With no
    key configured the chain is empty, which `complete_with_chain` reports
    honestly — but only after most of a dossier has been assembled, and as a
    model failure rather than the configuration problem it is.
    """
    as_user(PRO)
    res = client.post("/research/AAPL")
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "no_provider_key"


def test_pro_with_a_key_gets_past_the_plan_checks(client, as_user):
    as_user({**PRO, "llm_settings": {"keys": [{"id": "k1", "ciphertext": "x"}]}})
    assert client.post("/research/AAPL").status_code not in (400, 403)


# ── Analysis: three modes, three different costs ──────────────────────────────

def test_the_explicit_run_is_refused_without_the_plan(client, as_user):
    as_user(BASIC)
    res = client.get("/analyze", params={"ticker": "AAPL", "force_refresh": True})
    assert res.status_code == 403
    assert res.json()["detail"]["capability"] == "may_spend_tokens"


@pytest.mark.parametrize("user", [BASIC, PRO, TRADER])
def test_stored_only_is_never_plan_refused(client, as_user, user):
    as_user(user)
    res = client.get("/analyze", params={"ticker": "AAPL", "stored_only": True})
    assert res.status_code != 403


def test_plain_analyze_degrades_rather_than_refusing(client, as_user, monkeypatch):
    """
    The quiet one. Plain `/analyze` rebuilds a stale signal, which is a full
    pipeline run plus an analyst call on the deployment's key. For a reader it
    must return the stored document instead — not a 403, because the report
    export and the watchlist warm-up both call this route.

    Asserted by making `run_pipeline` raise: reaching it at all is the
    regression. Removing the degradation does not fail loudly on its own, which
    is exactly why it is pinned here, in the style of `test_stored_analysis.py`.
    """
    import app.routes.analysis as analysis

    async def _never(*a, **kw):
        raise AssertionError("run_pipeline reached for a caller who may not spend tokens")

    monkeypatch.setattr(analysis, "run_pipeline", _never)
    as_user(BASIC)
    res = client.get("/analyze", params={"ticker": "AAPL"})
    assert res.status_code != 403


# ── LLM keys: gated to add, never gated to remove ─────────────────────────────

def test_adding_a_key_is_refused_without_the_plan(client, as_user):
    as_user(BASIC)
    res = client.post("/settings/llm/keys", json={"provider": "anthropic", "api_key": "sk-x"})
    assert res.status_code == 403
    assert res.json()["detail"]["capability"] == "may_bring_own_key"


def test_testing_a_key_is_refused_without_the_plan(client, as_user):
    as_user(BASIC)
    assert client.post("/settings/llm/keys/k1/test").status_code == 403


@pytest.mark.parametrize("user", [BASIC, PRO, TRADER])
def test_removing_a_key_is_never_refused(client, as_user, user):
    """
    An account downgraded out of `may_bring_own_key` still owns its keys and
    must be able to take them back. Never gate the direction that reduces
    exposure — the same rule that keeps `execute_exit` out of the guard chain.
    """
    as_user(user)
    assert client.delete("/settings/llm/keys/k1").status_code != 403


def test_reading_model_settings_is_never_refused(client, as_user):
    as_user(BASIC)
    assert client.get("/settings/llm").status_code != 403


def test_enrolling_in_nightly_research_needs_the_grant(client, as_user):
    """PRO gets deep research on demand; the unattended daily job is a grant."""
    body = {"roles": {"orchestrator": [], "specialist": [], "analyst": []},
            "research_enabled": True}
    as_user(PRO)
    res = client.put("/settings/llm", json=body)
    assert res.status_code == 403
    assert res.json()["detail"]["capability"] == "may_enrol_in_nightly_research"

    as_user({**PRO, "research_daily_allowed": True})
    assert client.put("/settings/llm", json=body).status_code != 403


@pytest.mark.parametrize("user", [BASIC, PRO, TRADER])
def test_turning_nightly_research_off_is_never_refused(client, as_user, user):
    """
    Whatever the plan says, stopping a recurring spend must work — including
    for an account downgraded while it was still enrolled.
    """
    as_user(user)
    res = client.put("/settings/llm", json={
        "roles": {"orchestrator": [], "specialist": [], "analyst": []},
        "research_enabled": False,
    })
    assert res.status_code != 403


# ── Admin is not a tier ───────────────────────────────────────────────────────

def test_the_highest_tier_is_not_the_operator(client, as_user):
    """Being TRADER is being a customer, not the person who provisions them."""
    as_user(TRADER)
    res = client.get("/admin/users")
    assert res.status_code in (403, 404)
    if res.status_code == 403:
        assert res.json()["detail"]["error"] == "admin_required"


# ── The half a route gate cannot cover ────────────────────────────────────────

def test_the_automated_path_checks_the_plan_too():
    """
    `pipeline._execute_trades` runs on the 5-minute cycle, loads every watcher
    of a ticker, and calls `execute_entry` directly — no request, no dependency.
    Without a guard in `_prepare_entry`, an account downgraded out of trading
    while `mode=AUTO` keeps placing orders on the operator's brokerage account
    indefinitely, with its own UI hidden and every `/trading` route returning
    403. The router gate alone looks finished and is not.
    """
    import inspect

    from app.services import trade_manager

    source = inspect.getsource(trade_manager._prepare_entry)
    assert "_may_trade" in source

    # First guard, above CIRO — it answers "may this account trade at all"
    # rather than "is this particular trade sound".
    assert source.index("_may_trade") < source.index("_is_canadian_listed")


def test_the_exit_path_does_not_check_the_plan():
    """
    A downgraded account's open positions must stay closable. Same asymmetry
    that exempts SELL from every other delay here: refusing to buy costs an
    opportunity, refusing to sell costs money.
    """
    import inspect

    from app.services import trade_manager

    assert "_may_trade" not in inspect.getsource(trade_manager.execute_exit)


def test_both_entry_paths_run_the_guard_chain():
    """A manual order is a different decision, not a different set of guards."""
    import inspect

    from app.services import trade_manager

    for fn in (trade_manager.execute_entry, trade_manager.execute_manual_entry):
        assert "_prepare_entry" in inspect.getsource(fn)


# ── The rule that keeps the table the only source ─────────────────────────────

def test_no_route_module_names_a_tier():
    """
    Routes name *capabilities*, never tiers.

    A route asking `may_trade` keeps working when the table changes; a route
    asking whether the tier is PRO has quietly become a second, competing copy
    of the policy — which is how the numeric ladder this replaced became
    impossible to reason about.

    `routes/admin.py` is the one exception and is excluded: setting an
    account's tier is its entire job, and it does that through the enum rather
    than a literal.
    """
    from pathlib import Path

    routes = Path(__file__).resolve().parents[1] / "app/routes"
    offenders = []
    for path in sorted(routes.glob("*.py")):
        if path.name == "admin.py":
            continue
        text = path.read_text()
        for tier in ('"BASIC"', "'BASIC'", '"PRO"', "'PRO'", '"TRADER"', "'TRADER'"):
            if tier in text:
                offenders.append(f"{path.name} contains {tier}")
    assert not offenders, offenders


def test_the_admin_router_uses_the_enum_rather_than_literals():
    """Even where naming a tier is the job, the value comes from `AccessTier`."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "app/routes/admin.py").read_text()
    for tier in ('"BASIC"', '"PRO"', '"TRADER"'):
        assert tier not in text
