"""
Reading is not analysing.

Opening a ticker used to call `/analyze`, which serves a stored verdict only if
it is under thirty minutes old and otherwise runs the whole pipeline — yfinance,
Finnhub, FRED, fundamentals and an LLM call — before answering. Someone glancing
at a name paid for an analysis they never asked for.

`stored_only` is the fix, and the property worth a test is a negative one: on
that path `run_pipeline` must not be reachable at any age of stored document,
and must not be reached when there is no document at all. A regression here does
not fail loudly — it just makes the app slow again, quietly, in production.

`/quote` carries the other half: the price has to be current even when the
verdict is not, and it must never fail in a way that blanks the page.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.routes import analysis as route
from app.db import COLL_FEATURES, COLL_RAW, COLL_SIGNALS


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    async def find_one(self, query: dict, projection: dict | None = None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                return d
        return None


class FakeDB:
    def __init__(self, collections: dict[str, list[dict]]):
        self._c = {name: FakeCollection(docs) for name, docs in collections.items()}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._c.get(name) or FakeCollection([])


#: TRADER, because these tests are about *when* `/analyze` rebuilds, and a
#: caller who may not spend tokens never rebuilds at all — plain `/analyze`
#: degrades to a stored read for them, which is a different property, pinned in
#: `test_tier_routes.py`. Leaving the tier off here would have made these tests
#: quietly assert the reader's behaviour instead of the trader's.
USER = {"_id": "u1", "scoring_weights": None, "access_tier": "TRADER"}


def run(coro):
    """There is no pytest-asyncio here and no other async test; drive it directly."""
    return asyncio.run(coro)


def signal_doc(*, age_minutes: float, ticker: str = "AAPL") -> dict:
    return {
        "ticker": ticker,
        "score": 0.62,
        "signal": "HOLD",
        "confidence": 0.5,
        "risk": {"risk_score": 4.0, "risk_level": "MEDIUM", "explanation": "Fixture."},
        "current_price": 190.0,
        "day_change_pct": 1.2,
        "generated_at": datetime.now(tz=timezone.utc) - timedelta(minutes=age_minutes),
    }


@pytest.fixture
def wiring(monkeypatch):
    """Patch the module's own `get_db` and `run_pipeline`, and count the runs."""
    state = {"pipeline_calls": 0, "db": FakeDB({})}

    async def fake_get_db():
        return state["db"]

    async def fake_run_pipeline(ticker: str):
        state["pipeline_calls"] += 1
        return signal_doc(age_minutes=0, ticker=ticker)

    monkeypatch.setattr(route, "get_db", fake_get_db)
    monkeypatch.setattr(route, "run_pipeline", fake_run_pipeline)
    return state


# ── stored_only ───────────────────────────────────────────────────────────────

def test_stored_only_serves_an_ancient_analysis_without_running_anything(wiring):
    """
    Four hours old is well past the rebuild window, and that is the point: the
    reader asked what the engine last concluded, not for it to conclude again.
    """
    wiring["db"] = FakeDB({
        COLL_SIGNALS: [signal_doc(age_minutes=240)],
        COLL_FEATURES: [],
    })

    res = run(route.analyze(ticker="AAPL", force_refresh=False, stored_only=True, current_user=USER))

    assert res.ticker == "AAPL"
    assert res.score == pytest.approx(0.62)
    assert wiring["pipeline_calls"] == 0


def test_stored_only_404s_rather_than_analysing_a_ticker_it_has_never_seen(wiring):
    """
    The empty state is a fact about the account, not a failure. Answering it by
    starting a pipeline run would put the wait back exactly where a ticker
    reached from search feels it most.
    """
    wiring["db"] = FakeDB({COLL_SIGNALS: [], COLL_FEATURES: []})

    with pytest.raises(HTTPException) as exc:
        run(route.analyze(ticker="ZZZZ", force_refresh=False, stored_only=True, current_user=USER))

    assert exc.value.status_code == 404
    assert "ZZZZ" in exc.value.detail
    assert wiring["pipeline_calls"] == 0


def test_stored_only_and_force_refresh_together_are_refused(wiring):
    """They ask for opposite things; silently picking one would hide a client bug."""
    wiring["db"] = FakeDB({COLL_SIGNALS: [signal_doc(age_minutes=1)]})

    with pytest.raises(HTTPException) as exc:
        run(route.analyze(ticker="AAPL", force_refresh=True, stored_only=True, current_user=USER))

    assert exc.value.status_code == 400
    assert wiring["pipeline_calls"] == 0


# ── the unchanged paths ───────────────────────────────────────────────────────

def test_force_refresh_still_runs_the_pipeline(wiring):
    wiring["db"] = FakeDB({COLL_SIGNALS: [signal_doc(age_minutes=1)], COLL_FEATURES: []})

    run(route.analyze(ticker="AAPL", force_refresh=True, stored_only=False, current_user=USER))

    assert wiring["pipeline_calls"] == 1


def test_plain_analyze_still_rebuilds_a_stale_document(wiring):
    """
    The default is deliberately unchanged: the report export and the watchlist
    warm-up still want "fresh if you can".
    """
    wiring["db"] = FakeDB({COLL_SIGNALS: [signal_doc(age_minutes=240)], COLL_FEATURES: []})

    run(route.analyze(ticker="AAPL", force_refresh=False, stored_only=False, current_user=USER))

    assert wiring["pipeline_calls"] == 1


def test_plain_analyze_still_serves_a_fresh_document(wiring):
    wiring["db"] = FakeDB({COLL_SIGNALS: [signal_doc(age_minutes=2)], COLL_FEATURES: []})

    run(route.analyze(ticker="AAPL", force_refresh=False, stored_only=False, current_user=USER))

    assert wiring["pipeline_calls"] == 0


# ── /quote ────────────────────────────────────────────────────────────────────

def test_quote_falls_back_to_the_stored_price_when_there_is_no_key(wiring, monkeypatch):
    """
    A missing key is a configuration choice, not a fault. It must produce a
    labelled stored price rather than an error — this endpoint feeds the one
    number on the ticker page a reader would act on.
    """
    ingested = datetime.now(tz=timezone.utc) - timedelta(minutes=7)
    wiring["db"] = FakeDB({
        COLL_RAW: [{"ticker": "AAPL", "current_price": 188.5, "day_change_pct": -0.4,
                    "ingested_at": ingested}],
    })
    monkeypatch.setattr(route.get_settings(), "finnhub_api_key", "", raising=False)

    res = run(route.quote(ticker="aapl", current_user=USER))

    assert res.ticker == "AAPL"
    assert res.source == "stored"
    assert res.price == pytest.approx(188.5)
    assert res.note and "key" in res.note.lower()


def test_quote_reports_unavailable_rather_than_raising(wiring, monkeypatch):
    """No key and no stored price is still a 200 — a quote outage must not blank the page."""
    wiring["db"] = FakeDB({COLL_RAW: []})
    monkeypatch.setattr(route.get_settings(), "finnhub_api_key", "", raising=False)

    res = run(route.quote(ticker="ZZZZ", current_user=USER))

    assert res.source == "unavailable"
    assert res.price is None


def test_a_zero_price_is_not_a_price():
    """
    Finnhub answers an unknown symbol with a 200 and a body of zeros. Read
    literally that is a stock worth nothing, which is how a bad ticker would
    have rendered as $0.00 beside a real verdict.
    """
    assert route._positive(0) is None
    assert route._positive(None) is None
    assert route._positive("nonsense") is None
    assert route._positive(12.5) == pytest.approx(12.5)


# ── the per-ticker audit trail ────────────────────────────────────────────────

class FakeCursor:
    """Just enough of Motor's chainable cursor to record what was asked for."""

    def __init__(self, docs: list[dict], seen: dict):
        self._docs = docs
        self._seen = seen

    def sort(self, *_args):
        return self

    def limit(self, n: int):
        self._seen["limit"] = n
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        return self._docs


def test_orders_can_be_scoped_to_one_ticker(monkeypatch):
    """
    A per-symbol audit trail must not depend on the global 200-row cap happening
    to reach far enough back — an active desk fills that across all names long
    before it fills it on one.
    """
    from app.routes import trading

    docs = [
        {"_id": "1", "user_id": "u1", "ticker": "AAPL", "action": "BUY", "status": "FILLED"},
        {"_id": "2", "user_id": "u1", "ticker": "MSFT", "action": "BUY", "status": "FILLED"},
    ]
    seen: dict = {}

    class Coll:
        def find(self, query):
            seen["query"] = query
            matched = [d for d in docs if all(d.get(k) == v for k, v in query.items())]
            return FakeCursor(matched, seen)

    class DB:
        def __getitem__(self, _name):
            return Coll()

    async def fake_get_db():
        return DB()

    monkeypatch.setattr(trading, "get_db", fake_get_db)

    rows = run(trading.get_orders(ticker="aapl", limit=50, current_user={"_id": "u1"}))

    assert seen["query"] == {"user_id": "u1", "ticker": "AAPL"}
    assert seen["limit"] == 50
    assert [r.ticker for r in rows] == ["AAPL"]


def test_orders_unscoped_is_unchanged(monkeypatch):
    from app.routes import trading

    seen: dict = {}

    class Coll:
        def find(self, query):
            seen["query"] = query
            return FakeCursor([], seen)

    class DB:
        def __getitem__(self, _name):
            return Coll()

    async def fake_get_db():
        return DB()

    monkeypatch.setattr(trading, "get_db", fake_get_db)

    run(trading.get_orders(ticker=None, limit=200, current_user={"_id": "u1"}))

    assert seen["query"] == {"user_id": "u1"}
    assert seen["limit"] == 200


def test_a_proposal_read_through_orders_keeps_its_conviction():
    """
    `ProposalResponse` has always carried it and `TradeResponse` did not, so the
    same proposal lost the field that says how strongly the agent felt about it
    the moment it was read from the activity list rather than the queue.
    """
    from app.routes.trading import _trade_to_response

    res = _trade_to_response({
        "_id": "abc", "user_id": "u1", "ticker": "NVDA", "action": "BUY",
        "qty": 4, "limit_price": 120.0, "status": "PROPOSED",
        "signal_type": "BUY", "conviction": "HIGH", "is_paper": True,
        "opened_at": datetime.now(tz=timezone.utc),
    })

    assert res.conviction == "HIGH"


# ── credentials must not reach the log ────────────────────────────────────────

def test_a_failed_provider_call_does_not_log_the_api_key():
    """
    httpx renders the full request URL into `HTTPStatusError`, and ours carries
    the API token as a query parameter — so a plain `str(exc)` writes the key
    into a log line, where it outlives the process and gets shipped off the box.
    Caught the first time `/quote` was pointed at an unknown symbol.
    """
    import httpx

    url = "https://finnhub.io/api/v1/quote?symbol=ZZ&token=SUPERSECRET"
    req = httpx.Request("GET", url)
    exc = httpx.HTTPStatusError(
        f"Client error '403 Forbidden' for url '{url}'",
        request=req,
        response=httpx.Response(403, request=req),
    )

    out = route._safe_error(exc)

    assert "SUPERSECRET" not in out
    assert "token=***" in out
    # Masked, not discarded — the status code is the part worth keeping.
    assert "403" in out


def test_an_ordinary_error_message_survives_untouched():
    assert route._safe_error(ValueError("No data for ZZZZ")) == "No data for ZZZZ"
