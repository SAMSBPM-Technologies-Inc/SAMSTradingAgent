"""
Tests for scaling into an existing position.

Holding a stock was never a reason to refuse buying more of it. What the old
refusal protected was the bracket: a second entry attached a second, independent
stop to one holding, and `execute_exit` cancels every working order for a ticker
while closing only the single record it loads — so an exit left the remainder
held, unprotected, and invisible to the agent.

The rules that make adding safe, and that these tests pin:

  * protection is never weakened by an add
  * protective orders never cover more shares than are held
  * the position cap applies to the position, not to each order
  * an add is refused below the stop, where it would be averaging down through
    the level that says the thesis is wrong

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.trade_manager import (  # noqa: E402
    EntryPlan, _combined_bracket_levels, _volatility_size_factor,
)


def levels(**kw):
    base = dict(
        blended_entry=100.0,
        current_price=100.0,
        existing_stop=None,
        existing_target=None,
        analyst_stop=None,
        analyst_target=None,
    )
    base.update(kw)
    return _combined_bracket_levels(**base)


# ── Protection may never get looser ──────────────────────────────────────────

def test_adding_lower_does_not_drag_the_stop_down():
    """
    Bought at 100 with a stop at 95, added at 92: the blend is ~96, and a
    percentage stop off that blend lands at ~91.2 — below where the first
    shares were already protected. Keeping the higher of the two is the whole
    point; "improving" the average must not weaken the exit.
    """
    stop, target = levels(
        blended_entry=96.0, current_price=96.0, existing_stop=95.0,
    )
    assert stop == 95.0
    assert stop < 96.0 < target


def test_adding_higher_tightens_the_stop():
    """Pyramiding up raises the blended cost, so the derived stop rises with it."""
    stop, _ = levels(blended_entry=110.0, current_price=112.0, existing_stop=95.0)
    assert stop > 95.0


def test_target_is_never_lowered_either():
    _, target = levels(
        blended_entry=96.0, current_price=96.0,
        existing_stop=90.0, existing_target=130.0,
    )
    assert target == 130.0


def test_analyst_levels_are_used_when_they_validate():
    stop, target = levels(
        blended_entry=100.0, current_price=100.0,
        analyst_stop=93.0, analyst_target=125.0,
    )
    assert (stop, target) == (93.0, 125.0)


# ── The result has to be live-able ───────────────────────────────────────────

def test_a_stop_above_the_live_price_is_refused_not_clamped():
    """
    An existing stop that now sits above the market would liquidate the position
    the instant it reached the venue. Refusing leaves the working bracket alone,
    which is the safe failure; clamping would move a level nobody chose.
    """
    assert levels(blended_entry=100.0, current_price=94.0, existing_stop=95.0) == (None, None)


def test_a_target_below_the_live_price_is_refused():
    assert levels(
        blended_entry=100.0, current_price=140.0,
        existing_stop=90.0, existing_target=130.0,
    ) == (None, None)


def test_levels_must_straddle_the_blended_entry():
    assert levels(blended_entry=100.0, current_price=100.0, existing_stop=101.0) == (None, None)


# ── Protective orders cover the position, never the order ────────────────────

def test_total_qty_is_what_protection_must_cover():
    plan = EntryPlan(
        ticker="HXL", qty=100, limit_price=95.20,
        stop_price=90.0, target_price=110.0, account_id="DU123",
        add_to_trade_id="abc", held_qty=450,
    )
    assert plan.is_add is True
    assert plan.total_qty == 550


def test_a_fresh_entry_covers_only_itself():
    plan = EntryPlan(
        ticker="HXL", qty=100, limit_price=95.20,
        stop_price=90.0, target_price=110.0, account_id="DU123",
    )
    assert plan.is_add is False
    assert plan.total_qty == 100


# ── Sizing caps the position, not the order ──────────────────────────────────

def _room_qty(equity, pct, vol, held_qty, held_price, price):
    """The sizing arithmetic `_prepare_entry` runs for an add."""
    max_dollars = equity * pct * _volatility_size_factor(vol)
    return int((max_dollars - held_qty * held_price) / price)


def test_three_five_percent_adds_cannot_build_a_fifteen_percent_position():
    equity, pct, vol, price = 100_000.0, 0.05, 0.35, 100.0
    held = 0
    for _ in range(5):
        room = _room_qty(equity, pct, vol, held, price, price)
        if room < 1:
            break
        held += room
    assert held * price == pytest.approx(equity * pct, rel=0.01)


def test_a_full_position_leaves_no_room():
    # 50 shares at $100 is the whole 5% of a $100k account.
    assert _room_qty(100_000.0, 0.05, 0.35, 50, 100.0, 100.0) < 1


def test_room_is_measured_on_cost_basis_not_market_value():
    """
    A position down 40% must not free up room to buy more of it. Cost basis is
    what the cap is measured against precisely so that a falling price cannot
    invite the agent to average down mechanically.
    """
    cost_basis_room = _room_qty(100_000.0, 0.05, 0.35, 50, 100.0, 60.0)
    market_value_room = int((100_000.0 * 0.05 - 50 * 60.0) / 60.0)
    assert cost_basis_room < 1
    assert market_value_room > 0


# ── Routing: a held ticker becomes an add, not a refusal ─────────────────────

import asyncio  # noqa: E402

from app.models.trade import AutoTradeSettings, TradeStatus  # noqa: E402


class _FakeBroker:
    """Records what the trade manager asked the venue to do."""

    def __init__(self, *, cash=1_000_000.0, equity=1_000_000.0):
        self.cash, self.equity = cash, equity
        self.orders, self.protective, self.cancels = [], [], []
        self.working = False
        self.reject_order = False
        self.reject_protective = False

    def is_connected(self):
        return True

    async def get_account_summary(self, account_id=""):
        return {"connected": True, "net_liquidation": self.equity,
                "total_cash": self.cash, "buying_power": self.cash,
                "account_id": "DU123"}

    async def place_limit_order(self, ticker, action, qty, limit_price, **kw):
        self.orders.append({"ticker": ticker, "action": action, "qty": qty,
                            "limit_price": limit_price, **kw})
        return None if self.reject_order else "ORD-1"

    async def place_protective_orders(self, ticker, qty, stop, target, account_id=""):
        self.protective.append({"ticker": ticker, "qty": qty,
                                "stop": stop, "target": target})
        return None if self.reject_protective else "OCA-1"

    async def cancel_open_orders(self, ticker, account_id=""):
        self.cancels.append(ticker)
        return 2

    async def has_open_orders(self, ticker, account_id=""):
        return self.working


def _patch_tm(monkeypatch, *, position=None, broker=None, vol=0.35):
    """Wire trade_manager's collaborators to fakes. Returns (module, broker)."""
    import app.services.trade_manager as tm

    broker = broker or _FakeBroker()
    updates: list[tuple[str, dict]] = []

    async def _pos(user_id, ticker):
        return position

    async def _none(*a, **kw):
        return None

    async def _zero(*a, **kw):
        return 0

    async def _acct(user_id):
        return "DU123"

    async def _vol(ticker):
        return vol

    async def _update(trade_id, update):
        updates.append((trade_id, update))

    monkeypatch.setattr(tm, "ibkr", broker)
    monkeypatch.setattr(tm, "_open_position", _pos)
    monkeypatch.setattr(tm, "_pending_proposal", _none)
    monkeypatch.setattr(tm, "_count_open_positions", _zero)
    monkeypatch.setattr(tm, "_daily_realized_loss", _zero)
    monkeypatch.setattr(tm, "_get_user_account_id", _acct)
    monkeypatch.setattr(tm, "_ticker_volatility", _vol)
    monkeypatch.setattr(tm, "_update_trade", _update)
    broker.updates = updates
    return tm, broker


#: 450 shares bought at $88, protected 83/110, now trading at $95.20.
#: The levels have to straddle the live price — a position still held at $95
#: cannot have a $72 target working, because it would already have fired. The
#: first draft of this fixture did, and `_combined_bracket_levels` refused it,
#: which is the guard doing its job.
HELD = {
    "_id": "pos-1", "ticker": "HXL", "action": "BUY",
    "status": TradeStatus.FILLED, "qty": 450, "filled_qty": 450,
    "entry_price": 88.0, "limit_price": 88.0,
    "stop_loss": 83.0, "take_profit": 110.0, "closed_at": None,
}


def _prepare(tm, price=95.20, settings=None, requested_qty=None):
    return asyncio.run(tm._prepare_entry(
        "u1", "HXL", settings or AutoTradeSettings(position_size_pct=0.05),
        price, None, None, requested_qty=requested_qty,
    ))


def test_a_held_ticker_now_produces_an_add(monkeypatch):
    tm, _ = _patch_tm(monkeypatch, position=dict(HELD))
    plan, reason = _prepare(tm)
    assert reason is None
    assert plan.is_add is True
    assert plan.held_qty == 450
    assert plan.total_qty == 450 + plan.qty


def test_the_blended_entry_is_the_cost_weighted_average(monkeypatch):
    tm, _ = _patch_tm(monkeypatch, position=dict(HELD))
    plan, _ = _prepare(tm)
    expected = (450 * 88.0 + plan.qty * plan.limit_price) / (450 + plan.qty)
    assert plan.blended_entry == pytest.approx(expected, rel=1e-4)


def test_an_unfilled_first_entry_still_refuses(monkeypatch):
    """No fill price to blend and no settled quantity to size legs against."""
    pending = dict(HELD, status=TradeStatus.PENDING)
    tm, _ = _patch_tm(monkeypatch, position=pending)
    plan, reason = _prepare(tm)
    assert plan is None and "still working" in reason


def test_a_working_add_blocks_a_second_one(monkeypatch):
    busy = dict(HELD, pending_add={"qty": 100, "order_id": "ORD-9"})
    tm, _ = _patch_tm(monkeypatch, position=busy)
    plan, reason = _prepare(tm)
    assert plan is None and "still working" in reason


def test_adding_below_the_stop_is_refused(monkeypatch):
    tm, _ = _patch_tm(monkeypatch, position=dict(HELD))
    plan, reason = _prepare(tm, price=82.0)  # stop is 83
    assert plan is None
    assert "stop" in reason and "thesis is wrong" in reason


def test_scale_in_can_be_switched_off(monkeypatch):
    tm, _ = _patch_tm(monkeypatch, position=dict(HELD))
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "enable_scale_in", False)
    plan, reason = _prepare(tm)
    assert plan is None and "already hold" in reason


def test_the_add_goes_out_unbracketed_and_cancels_nothing(monkeypatch):
    """
    The existing bracket must survive: cancelling it first would leave the
    holding naked for as long as the add rests unfilled.
    """
    tm, broker = _patch_tm(monkeypatch, position=dict(HELD))
    plan, _ = _prepare(tm)
    trade_id, status, order_id = asyncio.run(tm._submit_add(
        "u1", plan, signal_score=0.8, signal_type="BUY", trigger="BUY signal",
    ))
    assert (status, order_id) == (TradeStatus.PENDING, "ORD-1")
    assert broker.cancels == []
    sent = broker.orders[0]
    assert sent["qty"] == plan.qty
    assert sent.get("stop_loss_price") is None
    assert sent.get("take_profit_price") is None


def test_a_rejected_add_leaves_the_position_exactly_as_it_was(monkeypatch):
    tm, broker = _patch_tm(monkeypatch, position=dict(HELD))
    broker.reject_order = True
    plan, _ = _prepare(tm)
    _, status, order_id = asyncio.run(tm._submit_add(
        "u1", plan, signal_score=0.8, signal_type="BUY", trigger="BUY signal",
    ))
    assert (status, order_id) == (TradeStatus.REJECTED, None)
    assert broker.cancels == [] and broker.protective == []


def test_the_pending_add_records_the_combined_levels_not_the_live_ones(monkeypatch):
    """
    Until the add fills, the working bracket still covers only the original
    shares, so stop_loss/take_profit must keep describing it.
    """
    tm, broker = _patch_tm(monkeypatch, position=dict(HELD))
    plan, _ = _prepare(tm)
    asyncio.run(tm._submit_add(
        "u1", plan, signal_score=0.8, signal_type="BUY", trigger="BUY signal",
    ))
    _, update = broker.updates[-1]
    assert "stop_loss" not in update and "take_profit" not in update
    pa = update["pending_add"]
    assert pa["total_qty"] == plan.total_qty
    assert pa["combined_stop"] == plan.stop_price


# ── Settlement: protection is sized to what is actually held ─────────────────

class _Status:
    def __init__(self, filled=True, partial=False, dead=False, avg=95.5, qty=100):
        self.is_filled, self.is_partial, self.is_dead = filled, partial, dead
        self.avg_fill_price, self.filled_qty = avg, qty
        self.status = "Filled"


PENDING_ADD = {
    "qty": 100, "limit_price": 95.20, "order_id": "ORD-1", "total_qty": 550,
    "blended_entry": 90.5, "combined_stop": 86.0, "combined_target": 110.0,
}


def _settle(tm, trade, held, statuses=None):
    return asyncio.run(tm._settle_pending_add(
        trade, statuses or {}, {}, held, "DU123",
    ))


def test_a_filled_add_consolidates_protection_onto_the_whole_holding(monkeypatch):
    tm, broker = _patch_tm(monkeypatch)
    trade = dict(HELD, pending_add=dict(PENDING_ADD))
    assert _settle(tm, trade, {"HXL": 550}) is True
    assert broker.cancels == ["HXL"]
    assert broker.protective == [
        {"ticker": "HXL", "qty": 550, "stop": 86.0, "target": 110.0}
    ]
    _, update = broker.updates[-1]
    assert update["qty"] == 550 and update["pending_add"] is None


def test_a_partial_fill_protects_what_filled_not_what_was_ordered(monkeypatch):
    """
    The whole reason legs are not sized to the intended total: 30 of 100 filled
    means 480 held, and a 550-share stop would sell 70 shares that do not exist.
    """
    tm, broker = _patch_tm(monkeypatch)
    trade = dict(HELD, pending_add=dict(PENDING_ADD))
    _settle(tm, trade, {"HXL": 480}, {"ORD-1": _Status(filled=False, partial=True, qty=30)})
    assert broker.protective[0]["qty"] == 480


def test_an_add_that_never_filled_leaves_the_original_size(monkeypatch):
    tm, broker = _patch_tm(monkeypatch)
    trade = dict(HELD, pending_add=dict(PENDING_ADD))
    _settle(tm, trade, {"HXL": 450}, {"ORD-1": _Status(filled=False, dead=True)})
    assert broker.protective[0]["qty"] == 450
    _, update = broker.updates[-1]
    assert "qty" not in update            # nothing was added
    assert update["pending_add"] is None  # but the add is resolved


def test_a_working_add_is_left_alone(monkeypatch):
    tm, broker = _patch_tm(monkeypatch)
    trade = dict(HELD, pending_add=dict(PENDING_ADD))
    working = _Status(filled=False, partial=False, dead=False)
    assert _settle(tm, trade, {"HXL": 450}, {"ORD-1": working}) is False
    assert broker.protective == [] and broker.cancels == []


def test_a_position_that_exited_while_the_add_rested_cancels_the_add(monkeypatch):
    """The stop fired first. Buying back in would open an unprotected position
    into a thesis that has already exited."""
    tm, broker = _patch_tm(monkeypatch)
    trade = dict(HELD, pending_add=dict(PENDING_ADD))
    assert _settle(tm, trade, {"HXL": 0}) is True
    assert broker.cancels == ["HXL"]
    assert broker.protective == []


def test_consolidation_aborts_if_the_old_legs_survive_cancellation(monkeypatch):
    """A read-only gateway session refuses cancels; adding a second pair then
    puts two stops on one holding."""
    tm, broker = _patch_tm(monkeypatch)
    broker.working = True
    trade = dict(HELD, pending_add=dict(PENDING_ADD))
    _settle(tm, trade, {"HXL": 550})
    assert broker.protective == []
    _, update = broker.updates[-1]
    assert update["unprotected_since"] is not None


def test_a_failed_consolidation_is_flagged_on_the_record(monkeypatch):
    tm, broker = _patch_tm(monkeypatch)
    broker.reject_protective = True
    trade = dict(HELD, pending_add=dict(PENDING_ADD))
    _settle(tm, trade, {"HXL": 550})
    _, update = broker.updates[-1]
    assert update["unprotected_since"] is not None
    assert "stop_loss" not in update  # levels not claimed when unprotected


# ── Healing a position that has no working protection ────────────────────────

def test_an_uncovered_position_gets_its_bracket_back(monkeypatch):
    tm, broker = _patch_tm(monkeypatch)
    broker.working = False
    assert asyncio.run(tm._heal_unprotected(dict(HELD), {"HXL": 450}, "DU123")) is True
    assert broker.protective == [
        {"ticker": "HXL", "qty": 450, "stop": 83.0, "target": 110.0}
    ]


def test_a_covered_position_is_left_alone(monkeypatch):
    tm, broker = _patch_tm(monkeypatch)
    broker.working = True
    assert asyncio.run(tm._heal_unprotected(dict(HELD), {"HXL": 450}, "DU123")) is False
    assert broker.protective == []


def test_healing_never_invents_a_level(monkeypatch):
    tm, broker = _patch_tm(monkeypatch)
    naked = dict(HELD, stop_loss=None, take_profit=None)
    assert asyncio.run(tm._heal_unprotected(naked, {"HXL": 450}, "DU123")) is False
    assert broker.protective == []
