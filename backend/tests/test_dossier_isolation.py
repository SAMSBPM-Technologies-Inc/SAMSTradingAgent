"""
Tests for per-user dossiers.

Dossiers used to be one shared series: one per ticker, built by a server-side
job on a server key. They are now built with a user's own credential and their
own chosen models, which makes them that user's reading rather than the
system's — and creates two ways to leak.

**A reading must not cross users.** Two traders on different models genuinely
disagree about the same company; handing one person the other's dossier
misattributes a judgement they never made and, through the veto, refuses their
order on it.

**A graded lesson must not cross users either, and this one is worse.** The
prior record is rendered into the ledger as citable `O` evidence describing how
"this desk" read a name and what happened. The moment the desk is a different
person that sentence is false — and unlike the dossier, which a user at least
sees, the lesson is injected silently into a prompt.

The legacy shared series — documents written before any of this, carrying no
`user_id` — stays readable by everyone. That is the one deliberate exception,
and it is not cross-user visibility: nobody owns those.

Run with:  pytest backend/tests -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.research import dossier as D  # noqa: E402
from app.services.research import prior_record as PR  # noqa: E402


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_a, **_k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        return list(self._docs)


class _Coll:
    """Records every query it is asked, and filters on the fields we care about."""

    def __init__(self, docs):
        self.docs = docs
        self.queries: list[dict] = []

    def find(self, query, _projection=None):
        self.queries.append(query)
        matched = [
            d for d in self.docs
            if all(_matches(d.get(k), v) for k, v in query.items())
        ]
        return _Cursor(matched)


def _matches(value, expected):
    if isinstance(expected, dict) and "$ne" in expected:
        return value != expected["$ne"]
    return value == expected


class _Db:
    def __init__(self, coll):
        self._coll = coll

    def __getitem__(self, _name):
        return self._coll


def _dossier(ticker="EXMP", user_id=None, as_of="2026-08-28T06:00:00+00:00",
             outcome=None):
    doc = {"ticker": ticker, "user_id": user_id, "as_of": as_of,
           "report": {"assessment": "BULLISH"}, "research_conviction": 70.0}
    if outcome is not None:
        doc["outcome"] = outcome
    return doc


# ── A dossier belongs to its owner ────────────────────────────────────────────

def test_a_user_gets_their_own_reading(monkeypatch):
    coll = _Coll([
        _dossier(user_id="alice", as_of="2026-08-28T06:00:00+00:00"),
        _dossier(user_id="bob", as_of="2026-08-28T07:00:00+00:00"),
    ])
    monkeypatch.setattr(D, "get_db", lambda: _async(_Db(coll)))

    got = asyncio.run(D.latest_dossier("EXMP", "alice"))
    assert got["user_id"] == "alice"


def test_a_newer_reading_by_another_user_is_not_returned(monkeypatch):
    """
    The failure this exists to prevent: sorting by recency across the whole
    collection would hand Alice Bob's dossier simply because his ran later.
    """
    coll = _Coll([
        _dossier(user_id="alice", as_of="2026-08-20T06:00:00+00:00"),
        _dossier(user_id="bob", as_of="2026-08-28T07:00:00+00:00"),
    ])
    monkeypatch.setattr(D, "get_db", lambda: _async(_Db(coll)))

    got = asyncio.run(D.latest_dossier("EXMP", "alice"))
    assert got["user_id"] == "alice"


def test_a_user_with_no_reading_of_their_own_falls_back_to_the_legacy_series(monkeypatch):
    """
    Documents written before dossiers were per-user carry no owner. Keeping
    them readable is what stops this change blanking every existing dossier.
    """
    coll = _Coll([_dossier(user_id=None)])
    monkeypatch.setattr(D, "get_db", lambda: _async(_Db(coll)))

    got = asyncio.run(D.latest_dossier("EXMP", "alice"))
    assert got is not None
    assert got["user_id"] is None


def test_the_fallback_is_the_legacy_series_and_never_another_user(monkeypatch):
    """
    The narrowness is the point. Falling back to "whatever is newest" would
    reintroduce exactly the cross-user leak the scoping removes.
    """
    coll = _Coll([_dossier(user_id="bob")])
    monkeypatch.setattr(D, "get_db", lambda: _async(_Db(coll)))

    assert asyncio.run(D.latest_dossier("EXMP", "alice")) is None
    # Both queries ran, and neither of them could have matched Bob.
    assert coll.queries[0]["user_id"] == "alice"
    assert coll.queries[1]["user_id"] is None


def test_a_read_failure_still_fails_open(monkeypatch):
    """Unchanged from before scoping: the veto must never halt trading on a
    database problem."""
    def boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(D, "get_db", boom)
    assert asyncio.run(D.latest_dossier("EXMP", "alice")) is None


# ── A lesson belongs to its owner ─────────────────────────────────────────────

def test_the_prior_record_is_scoped_to_one_reader(monkeypatch):
    """
    The worse of the two leaks: this content is injected into a prompt as
    citable evidence about "this desk", not merely displayed.
    """
    graded = {"assessment": "BULLISH", "return": 0.04, "alpha": -0.05,
              "assessment_correct": False, "horizon_days": 21}
    coll = _Coll([
        _dossier(user_id="alice", outcome=graded),
        _dossier(user_id="bob", outcome=graded),
    ])
    monkeypatch.setattr(PR, "get_db", lambda: _async(_Db(coll)))

    asyncio.run(PR.load_resolved("EXMP", "alice"))
    assert all(q.get("user_id") == "alice" for q in coll.queries)


def test_an_unscoped_prior_record_reads_the_legacy_series_only(monkeypatch):
    graded = {"assessment": "BULLISH", "return": 0.04, "alpha": -0.05,
              "assessment_correct": False, "horizon_days": 21}
    coll = _Coll([_dossier(user_id=None, outcome=graded)])
    monkeypatch.setattr(PR, "get_db", lambda: _async(_Db(coll)))

    asyncio.run(PR.load_resolved("EXMP", None))
    assert all(q.get("user_id") is None for q in coll.queries)


def test_a_prior_record_read_failure_degrades_to_no_record(monkeypatch):
    def boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(PR, "get_db", boom)
    assert asyncio.run(PR.load_resolved("EXMP", "alice")) == []


# ── The owner is recorded on the way in ───────────────────────────────────────

def test_the_veto_reads_the_ordering_users_dossier():
    """
    `_prepare_entry` already knows whose order it is. Refusing on a shared
    reading would refuse a trade on an opinion its owner never held.
    """
    import inspect

    from app.services import trade_manager as TM

    assert "user_id" in inspect.signature(TM._research_veto).parameters
    source = inspect.getsource(TM)
    assert "await _research_veto(ticker, user_id)" in source


def test_the_dossier_index_leads_with_the_owner():
    """
    Every read is "the newest one this reader has for this ticker". An index
    that led with the ticker would scan every user's history for each lookup.
    """
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "app/db.py").read_text()
    assert '[("user_id", 1), ("ticker", 1), ("as_of", -1)]' in text


def test_research_reaches_nobody_who_has_not_opted_in():
    """
    Five to seven calls per ticker per day, times users, is the one number here
    that can run away. The cohort query is the bound.
    """
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "app/jobs/scheduler.py").read_text()
    assert '{"llm_settings.research_enabled": True}' in text


async def _async(value):
    return value
