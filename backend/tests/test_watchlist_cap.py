"""
The ticker cap, and the one thing a naive version of it gets wrong.

The cap is the real cost control in this system. Every watched ticker joins the
union that `market_pipeline` runs every five minutes on the deployment's own
key, and `stocks_signals` is one shared document per ticker — so that spend
cannot be attributed to whoever asked for it. Bounding the list at the point of
entry is what bounds the bill, which is why readers are capped too.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.db import COLL_SIGNALS, COLL_WATCHED
from app.routes import watchlist as route


def run(coro):
    """No pytest-asyncio in this suite; drive it directly, as the others do."""
    return asyncio.run(coro)


class FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = list(docs)
        self.counts = 0
        self.upserts: list[dict] = []

    async def find_one(self, query: dict, projection: dict | None = None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                return d
        return None

    async def count_documents(self, query: dict):
        self.counts += 1
        return sum(1 for d in self._docs if all(d.get(k) == v for k, v in query.items()))

    async def update_one(self, query: dict, update: dict, upsert: bool = False):
        self.upserts.append(query)
        if not await self.find_one(query):
            self._docs.append(dict(update.get("$set") or {}))


class FakeDB:
    def __init__(self, collections: dict[str, list[dict]]):
        self._c = {name: FakeCollection(docs) for name, docs in collections.items()}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self._c:
            self._c[name] = FakeCollection([])
        return self._c[name]


class FakeBackgroundTasks:
    def __init__(self):
        self.tasks: list[tuple] = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def watching(user_id: str, *tickers: str) -> list[dict]:
    return [{"user_id": user_id, "ticker": t} for t in tickers]


@pytest.fixture
def wiring(monkeypatch):
    state = {"db": FakeDB({})}

    async def fake_get_db():
        return state["db"]

    monkeypatch.setattr(route, "get_db", fake_get_db)
    return state


def add(ticker: str, user: dict, bg=None):
    return run(route.add_ticker(
        body=route.TickerAddRequest(ticker=ticker),
        background_tasks=bg or FakeBackgroundTasks(),
        current_user=user,
    ))


PRO = {"_id": "u1", "access_tier": "PRO", "watchlist_cap": 3}
TRADER = {"_id": "u1", "access_tier": "TRADER"}


# ── The property a naive check gets wrong ─────────────────────────────────────

def test_re_adding_a_watched_ticker_at_the_cap_still_works(wiring):
    """
    The question is "would this add a row", not "is the list full".

    Re-adding is a no-op upsert and the UI does it deliberately — the dashboard
    re-adds the selected ticker. A bare `count >= cap` refuses that, and only
    once a user is *exactly* at their limit, which is the worst possible moment
    to discover it.
    """
    wiring["db"] = FakeDB({COLL_WATCHED: watching("u1", "AAPL", "MSFT", "NVDA")})

    res = add("AAPL", PRO)

    assert res.status == "accepted"
    assert wiring["db"][COLL_WATCHED].upserts, "the upsert should still have run"


def test_a_new_ticker_at_the_cap_is_refused(wiring):
    wiring["db"] = FakeDB({COLL_WATCHED: watching("u1", "AAPL", "MSFT", "NVDA")})

    with pytest.raises(HTTPException) as exc:
        add("TSLA", PRO)

    assert exc.value.status_code == 403
    detail = exc.value.detail
    assert detail["error"] == "watchlist_cap"
    assert detail["cap"] == 3
    # Names the number and the way out. "Limit reached" leaves nothing to do.
    assert "3" in detail["message"] and "TSLA" in detail["message"]


def test_below_the_cap_a_new_ticker_is_accepted(wiring):
    wiring["db"] = FakeDB({COLL_WATCHED: watching("u1", "AAPL", "MSFT")})

    assert add("TSLA", PRO).status == "accepted"


def test_another_users_tickers_do_not_count_against_this_one(wiring):
    wiring["db"] = FakeDB({
        COLL_WATCHED: watching("u1", "AAPL") + watching("u2", "MSFT", "NVDA", "TSLA", "AMD"),
    })

    assert add("META", PRO).status == "accepted"


# ── Unlimited pays nothing ────────────────────────────────────────────────────

def test_an_unlimited_plan_never_counts(wiring):
    """
    `cap is None` short-circuits before either query, so a trader's add does not
    grow two round-trips to enforce a limit that does not exist.
    """
    wiring["db"] = FakeDB({COLL_WATCHED: watching("u1", *[f"T{i}" for i in range(50)])})

    assert add("AAPL", TRADER).status == "accepted"
    assert wiring["db"][COLL_WATCHED].counts == 0


def test_a_cap_of_zero_is_a_real_cap(wiring):
    """`None` is unlimited and zero is nothing; the two must not collapse."""
    wiring["db"] = FakeDB({COLL_WATCHED: []})

    with pytest.raises(HTTPException) as exc:
        add("AAPL", {"_id": "u1", "access_tier": "TRADER", "watchlist_cap": 0})

    assert exc.value.status_code == 403


# ── The background run ────────────────────────────────────────────────────────

def test_a_name_nobody_has_scored_kicks_the_pipeline(wiring):
    wiring["db"] = FakeDB({COLL_WATCHED: [], COLL_SIGNALS: []})
    bg = FakeBackgroundTasks()

    add("AAPL", PRO, bg)

    assert len(bg.tasks) == 1


def test_a_name_already_covered_costs_nothing(wiring):
    """
    Every watched ticker joins the 5-minute union anyway, so a name somebody
    else already watches needs no run here — and that spend is on the
    deployment's key, which is why readers are capped in the first place.
    """
    wiring["db"] = FakeDB({COLL_WATCHED: [], COLL_SIGNALS: [{"ticker": "AAPL"}]})
    bg = FakeBackgroundTasks()

    add("AAPL", PRO, bg)

    assert bg.tasks == []
