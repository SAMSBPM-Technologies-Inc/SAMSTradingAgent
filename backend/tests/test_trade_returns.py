"""
Return on capital, and the fourth bucket the dashboard's head-to-head reads.

`/performance/trades` reported dollars only. A dollar figure cannot be compared
between two sets of trades that committed different amounts of money — $400 on
$40,000 and $400 on $4,000 are not the same result — and comparing the agent's
picks with the trader's is exactly that comparison, so the percentage is what
makes the question answerable at all.

Two things are easy to get wrong here and both are tested below: the
denominator must cover the same trades as the numerator, and it must be
described as turnover rather than as the size of the account.

Run with:  pytest backend/tests/test_trade_returns.py -q
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.db import COLL_TRADES  # noqa: E402
from app.models.trade import TradeStatus  # noqa: E402
from app.routes import performance as route  # noqa: E402


def run(coro):
    """No pytest-asyncio in this suite; drive it directly, as the others do."""
    return asyncio.run(coro)


class FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    async def to_list(self, length: int):
        return list(self._docs[:length])


class FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = list(docs)

    def find(self, query: dict, projection: dict | None = None):
        return FakeCursor([
            d for d in self._docs if all(d.get(k) == v for k, v in query.items())
        ])


class FakeDB:
    def __init__(self, docs: list[dict]):
        self._c = {COLL_TRADES: FakeCollection(docs)}

    def __getitem__(self, name: str):
        return self._c.get(name, FakeCollection([]))


USER = "u1"


@pytest.fixture
def report(monkeypatch):
    """Call the route against a fixed set of trade documents."""
    def _run(docs: list[dict]) -> dict:
        async def fake_db():
            return FakeDB(docs)
        monkeypatch.setattr(route, "get_db", fake_db)
        return run(route.get_trade_performance(current_user={"_id": USER}))
    return _run


def closed_trade(**over) -> dict:
    """
    A closed, priced, fully-netted trade — the shape the rates count.

    The timestamps are not decoration: the route sorts `recent_closed` on
    `closed_at or opened_at`, and a record carrying neither would raise there
    before any of this arithmetic was reached. Every real trade is written with
    an `opened_at`, so the fixture carries one too.
    """
    base = {
        "user_id": USER,
        "ticker": "AAA",
        "status": TradeStatus.CLOSED,
        "signal_type": "BUY",
        "entry_price": 100.0,
        "filled_qty": 10,
        "pnl": 50.0,
        "pnl_net": 45.0,
        "commission_paid": 5.0,
        "commission_complete": True,
        "opened_at": "2026-08-01T14:30:00Z",
        "closed_at": "2026-08-12T18:00:00Z",
    }
    base.update(over)
    return base


# ── The rate ──────────────────────────────────────────────────────────────────

def test_return_is_pnl_over_the_capital_that_produced_it(report):
    """$1,000 of stock that made $45 net returned 4.5%, not some other number."""
    r = report([closed_trade()])
    assert r["all"]["capital_deployed_net"] == 1000.0
    assert r["all"]["return_on_capital_net"] == pytest.approx(0.045)
    # Gross keeps its own pair, over its own (here identical) set.
    assert r["all"]["return_on_capital"] == pytest.approx(0.05)


def test_the_basis_is_the_blended_cost_so_scale_ins_are_counted(report):
    """
    `entry_price` is the blended cost after every add and `filled_qty` the
    total held, which is also what `pnl` is computed against. A basis taken
    from the first leg alone would divide a three-leg position's P&L by a
    third of its cost and report triple the return.
    """
    scaled = closed_trade(entry_price=110.0, filled_qty=30, pnl=300.0,
                          pnl_net=290.0, scale_ins=2)
    r = report([scaled])
    assert r["all"]["capital_deployed_net"] == pytest.approx(3300.0)
    assert r["all"]["return_on_capital_net"] == pytest.approx(290.0 / 3300.0, abs=5e-5)


def test_capital_deployed_is_turnover_not_account_size(report):
    """
    Ten sequential trades of $1,000 deploy $10,000. This is the right base for
    "did these trades earn their keep" and the wrong one for "how big is the
    account" — the tile that shows it says so, and this pins the arithmetic
    that makes the caveat necessary.
    """
    r = report([closed_trade() for _ in range(10)])
    assert r["all"]["capital_deployed_net"] == 10_000.0
    # The rate is unchanged by repetition: ten identical trades still returned 4.5%.
    assert r["all"]["return_on_capital_net"] == pytest.approx(0.045)


def test_a_trade_with_no_basis_leaves_both_sides_of_the_ratio(report):
    """
    The failure worth guarding: keeping a trade's P&L in the numerator while
    its unknowable cost is missing from the denominator. That inflates the
    return by an amount nobody can see, in one direction, every time.
    """
    priced_only = closed_trade(
        ticker="BBB", entry_price=None, limit_price=None,
        filled_qty=None, qty=None,
        pnl=9999.0, pnl_net=9999.0, commission_paid=1.0,
    )
    r = report([closed_trade(), priced_only])["all"]
    # The headline totals still carry it — it is a real result.
    assert r["realised_pnl_net"] == pytest.approx(45.0 + 9999.0)
    # The rate does not, on either side.
    assert r["capital_deployed_net"] == 1000.0
    assert r["return_on_capital_net"] == pytest.approx(0.045)


def test_no_closed_trades_gives_none_and_never_zero(report):
    """
    A 0% return reads as "traded and made nothing", which is a claim. Absence
    is not a result — the same rule `commission_paid` and `alpha` follow.
    """
    r = report([])["all"]
    assert r["capital_deployed"] is None
    assert r["return_on_capital"] is None
    assert r["capital_deployed_net"] is None
    assert r["return_on_capital_net"] is None


def test_an_open_position_is_not_in_the_realised_rate(report):
    """An unrealised gain has not been earned; it must not enter the record."""
    holding = closed_trade(status=TradeStatus.FILLED, pnl=None, pnl_net=None)
    r = report([closed_trade(), holding])["all"]
    assert r["open"] == 1
    assert r["capital_deployed_net"] == 1000.0


# ── The fourth bucket ─────────────────────────────────────────────────────────

def test_agent_originated_pools_auto_and_semi_and_nothing_else(report):
    """
    Every trade the *tool* picked, however it reached the venue. This is the
    one legitimate pooling: it answers "whose ideas were better", where who
    pressed the button is not part of the question.
    """
    docs = [
        closed_trade(signal_type="BUY"),                 # agent, unattended
        closed_trade(signal_type="EXIT_ALERT"),          # agent, unattended
        closed_trade(signal_type="PROPOSAL_APPROVED"),   # agent's pick, you approved
        closed_trade(signal_type="MANUAL"),              # yours
    ]
    r = report(docs)
    assert r["signal_driven"]["closed"] == 2
    assert r["approved"]["closed"] == 1
    assert r["manual"]["closed"] == 1
    assert r["agent_originated"]["closed"] == 3
    # It pools the two agent buckets and stops there — the manual trade's
    # capital is not in it.
    assert r["agent_originated"]["capital_deployed_net"] == 3000.0


def test_pooling_leaves_the_three_original_buckets_untouched(report):
    """
    `signal_driven` is the only clean read of the engine and the head-to-head
    must not cost anybody that reading. The fourth bucket is additive.
    """
    docs = [closed_trade(signal_type="BUY"),
            closed_trade(signal_type="PROPOSAL_APPROVED", pnl=-500.0, pnl_net=-505.0)]
    r = report(docs)
    assert r["signal_driven"]["return_on_capital_net"] == pytest.approx(0.045)
    assert r["signal_driven"]["realised_pnl_net"] == 45.0
    # The pooled column is dragged down by the approved half, which is exactly
    # why the panel showing it must also show the split.
    assert r["agent_originated"]["realised_pnl_net"] == pytest.approx(-460.0)


def test_proposals_reach_no_bucket_that_counts_outcomes(report):
    """
    A PROPOSED record carries signal_type BUY, so it sorts as agent-originated
    — but it committed nothing, and a proposal declined or still waiting is not
    a trade. It must not move a rate.
    """
    docs = [
        closed_trade(),
        closed_trade(status=TradeStatus.PROPOSED, pnl=None, pnl_net=None),
        closed_trade(status=TradeStatus.DECLINED, pnl=None, pnl_net=None),
    ]
    r = report(docs)["agent_originated"]
    assert r["closed"] == 1
    assert r["open"] == 0
    assert r["capital_deployed_net"] == 1000.0
