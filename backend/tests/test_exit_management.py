"""
Tests for the exit side — what a position did, how it ended, and when the stop
moves with it.

Every automated exit in this system used to be decided before the position
moved: the bracket's stop and target are set at entry and, apart from a
scale-in, nothing revised them. Three consequences, and these tests pin the fix
to each.

  * A trade recorded its entry and its exit and nothing in between, so "ran 9%
    and gave it all back" and "never moved" were the same record — a stop-out at
    −5%. `_excursion_update` / `_excursion_summary`.
  * Reconciliation stamped `bracket_or_manual` on everything it found flat, so a
    target hit and a stop-out were indistinguishable — although the document
    carries both levels and the fill price. `_classify_bracket_exit`.
  * Nothing ever raised a stop. `_trailed_stop`, which is off by default and
    must never loosen one.

Run with:  pytest backend/tests -q
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.services.trade_manager import (  # noqa: E402
    _classify_bracket_exit,
    _excursion_summary,
    _excursion_update,
    _trailed_stop,
    _ratcheted_target,
)
from app.services.trade_rationale import (  # noqa: E402
    _EXIT_REASON,
    exit_rationale,
    exit_trigger_phrase,
)


@pytest.fixture
def trailing(monkeypatch):
    """Switch the trail on with known distances; it ships off."""
    s = get_settings()
    def _set(**over):
        defaults = dict(
            trailing_stop_enabled=True,
            trailing_stop_pct=0.08,
            trailing_stop_activate_pct=0.06,
            breakeven_trigger_pct=0.04,
            trailing_stop_min_step_pct=0.01,
            trailing_target_headroom_pct=0.10,
        )
        defaults.update(over)
        for k, v in defaults.items():
            monkeypatch.setattr(s, k, v)
    return _set


def trail(**kw):
    # The target defaults well above the marks used below: a position trading
    # through its target would have had that leg fill, so a case where the trail
    # collides with it is a deliberate scenario, not the ambient one.
    base = dict(entry=100.0, mark=100.0, high_water=None,
                working_stop=95.0, target=140.0)
    base.update(kw)
    return _trailed_stop(**base)


# ── Excursion: the measurement none of this could be argued from ─────────────

def test_a_new_high_is_recorded():
    assert _excursion_update({"high_water_price": 105.0}, 108.0)["high_water_price"] == 108.0


def test_a_lower_mark_never_lowers_the_high():
    assert "high_water_price" not in _excursion_update({"high_water_price": 105.0}, 101.0)


def test_a_new_low_is_recorded_and_a_higher_mark_does_not_raise_it():
    assert _excursion_update({"low_water_price": 95.0}, 92.0)["low_water_price"] == 92.0
    assert "low_water_price" not in _excursion_update({"low_water_price": 95.0}, 99.0)


def test_the_first_observation_sets_both():
    upd = _excursion_update({}, 103.0)
    assert upd["high_water_price"] == upd["low_water_price"] == 103.0


def test_an_unpriced_pass_records_nothing():
    """
    A missing mark is the venue not pricing the position, which is not the same
    as the price being zero — the `commission_paid` rule. Seeding from the entry
    price would report a peak that never happened.
    """
    assert _excursion_update({"entry_price": 100.0}, 0.0) == {}
    assert _excursion_update({"entry_price": 100.0}, None) == {}


def test_the_give_back_is_the_whole_point():
    """A stop-out that had been up 9% is a different trade from one that never rose."""
    summary = _excursion_summary(
        {"entry_price": 100.0, "high_water_price": 109.0, "low_water_price": 95.0}, 95.0,
    )
    assert summary["mfe_pct"] == pytest.approx(0.09)
    assert summary["mae_pct"] == pytest.approx(-0.05)
    assert summary["gave_back_pct"] == pytest.approx(0.14)


def test_an_unobserved_position_gives_back_none_not_zero():
    """
    Zero would say the exit was perfectly timed — flatteringly, in the same
    direction, every time. Same rule as `alpha`.
    """
    summary = _excursion_summary({"entry_price": 100.0}, 95.0)
    assert "gave_back_pct" not in summary
    assert "mfe_pct" not in summary


def test_no_entry_price_means_no_excursion_at_all():
    assert _excursion_summary({"high_water_price": 109.0}, 95.0) == {}


# ── Which leg fired ──────────────────────────────────────────────────────────

def test_a_fill_at_or_above_the_target_is_a_take_profit():
    assert _classify_bracket_exit(110.0, 95.0, 110.0) == "TAKE_PROFIT"
    assert _classify_bracket_exit(112.0, 95.0, 110.0) == "TAKE_PROFIT"


def test_a_fill_at_or_below_the_stop_is_a_stop_out():
    assert _classify_bracket_exit(95.0, 95.0, 110.0) == "STOP_LOSS"
    assert _classify_bracket_exit(88.0, 95.0, 110.0) == "STOP_LOSS"   # gapped through


def test_a_fill_between_the_legs_is_not_attributed():
    """
    Neither leg can have fired, so the honest answer is None. Guessing the
    likelier one is exactly the fabrication this replaces.
    """
    assert _classify_bracket_exit(102.0, 95.0, 110.0) is None


def test_an_unbracketed_or_unpriced_trade_is_not_attributed():
    assert _classify_bracket_exit(102.0, None, None) is None
    assert _classify_bracket_exit(None, 95.0, 110.0) is None
    assert _classify_bracket_exit(0.0, 95.0, 110.0) is None


def test_both_legs_now_have_a_sentence_and_a_phrase():
    assert exit_rationale("TAKE_PROFIT", None) == _EXIT_REASON["TAKE_PROFIT"]
    assert exit_trigger_phrase("STOP_LOSS") == "stopped out"
    assert exit_trigger_phrase(None) is None


def test_the_exit_alert_ghost_is_gone():
    """
    It had a sentence for years and no caller — `execute_exit`'s trigger
    defaulted to it and both call sites passed something else, so the string
    could never be written. A reason for an exit that cannot happen is the same
    class of lie as a gate panel contradicting the badge beside it.
    """
    assert "EXIT_ALERT" not in _EXIT_REASON
    assert exit_trigger_phrase("EXIT_ALERT") is None


def test_execute_exit_has_no_default_trigger():
    import inspect
    from app.services.trade_manager import execute_exit

    assert inspect.signature(execute_exit).parameters["trigger"].default \
        is inspect.Parameter.empty


# ── The trail: off by default, and it may only ever move a stop up ───────────

def test_one_switch_governs_both_legs(monkeypatch):
    """
    The trail and the target ratchet are one mechanism. A trail under a fixed
    target is inert — the take-profit leg fills before it can bite — so neither
    leg may be switchable on its own. Off, both refuse; on, both answer.
    """
    s = get_settings()
    monkeypatch.setattr(s, "trailing_stop_enabled", False)
    assert trail(mark=130.0, high_water=130.0) == (None, None)
    assert _ratcheted_target(
        entry=100.0, mark=130.0, high_water=130.0, working_target=140.0,
    ) == (None, None)

    monkeypatch.setattr(s, "trailing_stop_enabled", True)
    assert trail(mark=130.0, high_water=130.0)[1] == "trail"
    assert _ratcheted_target(
        entry=100.0, mark=130.0, high_water=130.0, working_target=140.0,
    )[1] == "ratchet"


def test_a_position_that_runs_25pct_trails_all_the_way_up(trailing):
    """
    The fence this feature never had, and the reason 1.31.0 exists.

    Under the shipped defaults the trail could not fire. The take-profit leg was
    set at entry (+10%) and nothing ever raised it, so a position walking up to
    its target moved its stop exactly twice:

        peak +4.00%   breakeven -> stop 100.00
        peak +9.89%   trail     -> stop 101.10   <- limit leg fills at +10%

    One trail move, locking in 1.1%, inside the last 0.11% of price travel
    before the trade closed. `TRAILING_STOP_ENABLED=true` bought break-even and
    nothing else, while `config.py` advertised "an 8% trail on a name up 20%
    still locks in ~10%" — a position that could not exist.

    Walk one 25% up-move and assert the pair keeps moving the whole way.
    """
    trailing()
    entry = 100.0
    stop, target = 95.0, 110.0
    moves = []

    for i in range(0, 2501):
        peak = mark = entry * (1 + i / 10000.0)
        if mark >= target:
            break                                    # the limit leg would fill
        new_stop, _ = _trailed_stop(
            entry=entry, mark=mark, high_water=peak,
            working_stop=stop, target=target, enforce_min_step=False,
        )
        new_target, _ = _ratcheted_target(
            entry=entry, mark=mark, high_water=peak, working_target=target,
        )
        step = mark * 0.01
        stop_worth = new_stop is not None and new_stop - stop >= step
        target_worth = new_target is not None and new_target - target >= step
        if not (stop_worth or target_worth):
            continue
        stop = new_stop if new_stop is not None else stop
        target = new_target if new_target is not None else target
        assert 0 < stop < target                     # `_reprotect`'s invariant
        moves.append((round(peak, 2), stop, target))

    # The position is still alive well past the +10% that used to close it. The
    # last move lands short of 125 because the step limit is still doing its
    # job — it is a rate limit, not a ceiling.
    assert moves[-1][0] > 120.0
    # Many moves, not two.
    assert len(moves) > 5
    # The stop finishes a trail-width under the peak it last acted on, so the
    # position gives back ~8% of its high rather than running to a fixed target.
    assert moves[-1][1] == pytest.approx(moves[-1][0] * 0.92, abs=0.5)
    # The number that matters: locked-in gain, against the 1.1% of the old path.
    assert moves[-1][1] > 113.0


def test_break_even_engages_first(trailing):
    """Up 4%: past the break-even trigger, short of the trail's activation."""
    trailing()
    level, rule = trail(mark=104.0, high_water=104.0)
    assert (level, rule) == (100.0, "breakeven")


def test_the_trail_follows_the_peak_down(trailing):
    trailing()
    level, rule = trail(mark=118.0, high_water=120.0)
    assert rule == "trail"
    assert level == pytest.approx(110.4)      # 120 × (1 − 0.08)


def test_the_higher_of_the_two_rules_wins(trailing):
    """At +6% the trail is still under cost; break-even must not be given up."""
    trailing()
    level, rule = trail(mark=106.0, high_water=106.0)
    assert rule == "breakeven"
    assert level == 100.0                      # not 106 × 0.92 = 97.52


def test_a_stop_is_never_loosened(trailing):
    """The invariant the whole thing rests on, and the one `_combined_bracket_levels` shares."""
    trailing()
    assert trail(mark=118.0, high_water=120.0, working_stop=115.0) == (None, None)


def test_a_position_that_never_rose_is_left_alone(trailing):
    trailing()
    assert trail(mark=99.0, high_water=101.0) == (None, None)


def test_a_move_too_small_to_be_worth_an_order_is_refused(trailing):
    """
    Reconciliation runs every two minutes and each move costs a cancel and two
    placements — the `MIN_ADD_FRACTION` instinct on the exit side.
    """
    trailing()
    # Trail level 110.4 against a working stop of 110.0 — a 0.4 move on a 118
    # mark, well under the 1% step.
    assert trail(mark=118.0, high_water=120.0, working_stop=110.0) == (None, None)
    # Widen the step allowance and the same move is now worth making.
    trailing(trailing_stop_min_step_pct=0.001)
    assert trail(mark=118.0, high_water=120.0, working_stop=110.0)[0] == pytest.approx(110.4)


# ── The target ratchet ────────────────────────────────────────────────────────

def ratchet(**kw):
    base = dict(entry=100.0, mark=100.0, high_water=None, working_target=110.0)
    base.update(kw)
    return _ratcheted_target(**base)


def test_the_target_does_not_move_before_the_trail_arms(trailing):
    """
    A position that has not run has no reason to move its target, and widening
    one on a position sitting at cost is a worse exit chosen for free.
    """
    trailing()
    assert ratchet(mark=104.0, high_water=104.0) == (None, None)   # +4%, under +6%
    level, rule = ratchet(mark=106.0, high_water=106.0)
    assert (level, rule) == (pytest.approx(116.6), "ratchet")      # 106 × 1.10


def test_a_target_is_never_lowered(trailing):
    """
    The mirror of the stop invariant, and it bites harder: a target moved down
    pulls the exit toward the market and can fill the moment it reaches the
    venue.
    """
    trailing()
    # Peak 120 implies 132, but the record already carries a higher one.
    assert ratchet(mark=120.0, high_water=120.0, working_target=150.0) == (None, None)


def test_a_target_is_never_placed_at_or_below_the_market(trailing):
    """A target under the mark is a market order with extra steps."""
    trailing(trailing_target_headroom_pct=0.01)
    # Peak 120 implies 121.2, but the mark has run to 130 since.
    assert ratchet(mark=130.0, high_water=120.0, working_target=110.0) == (None, None)


def test_the_ratchet_follows_the_peak_not_the_cost_basis(trailing):
    """
    Measured from the high-water mark, so the ceiling moves with the position
    instead of staying where entry put it.
    """
    trailing()
    assert ratchet(mark=118.0, high_water=125.0)[0] == pytest.approx(137.5)


def test_both_legs_move_on_one_trip_to_the_venue(monkeypatch, trailing):
    """
    One cancel and two placements buys both legs, so the rate limit belongs to
    the pair. Charging each leg separately would refuse a stop move worth making
    because the target beside it was not.
    """
    trailing()
    (_, raised), writes, broker = run_trail(monkeypatch, dict(OPEN), 130.0)

    assert raised is True
    assert len(broker.placed) == 1                     # one pair, not two trips
    _t, _q, stop, target = broker.placed[-1]
    assert (stop, target) == (pytest.approx(119.6), pytest.approx(143.0))

    written = writes[-1]
    assert written["stop_raise_count"] == 1
    assert written["target_raise_count"] == 1
    assert written["target_raised_by"] == "ratchet"


def test_a_target_move_alone_is_enough_to_pay_for_the_trip(monkeypatch, trailing):
    """
    The stop is already where the trail wants it; only the target has room to
    move. That still justifies the placement — the alternative is a target
    frozen a cycle behind the peak for no reason.
    """
    trailing()
    # Stop already at 119.6 (130 × 0.92), so `_trailed_stop` has nothing to add.
    trade = dict(OPEN, stop_loss=119.6, take_profit=120.0)
    (_, raised), writes, broker = run_trail(monkeypatch, trade, 130.0)

    assert raised is True
    assert broker.placed[-1][3] == pytest.approx(143.0)
    written = writes[-1]
    assert written["target_raise_count"] == 1
    assert "stop_raise_count" not in written           # the stop did not move


def test_a_stop_is_never_placed_through_the_market(trailing):
    """
    A stop at or above the mark is not protection, it is a market order with
    extra steps. Refused rather than clamped — clamping would place a level
    nobody chose.
    """
    trailing(trailing_stop_pct=0.01)
    # Gapped down hard from the peak: 130 × 0.99 = 128.7, above a 105 mark.
    assert trail(mark=105.0, high_water=130.0) == (None, None)


def test_a_stop_is_never_placed_through_the_target(trailing):
    """`_reprotect` requires 0 < stop < target and would refuse the pair, leaving
    the position uncovered — worse than not trailing."""
    trailing(trailing_stop_pct=0.02)
    assert trail(mark=119.0, high_water=120.0, target=115.0) == (None, None)


def test_break_even_can_be_switched_off_on_its_own(trailing):
    trailing(breakeven_trigger_pct=0.0)
    assert trail(mark=104.0, high_water=104.0) == (None, None)
    # The trail still works.
    assert trail(mark=118.0, high_water=120.0)[1] == "trail"


def test_unknown_prices_never_move_a_stop(trailing):
    """
    The failure being avoided is a guard that tightens on bad data and closes a
    live position for free. Every uncertain path leaves the stop alone.
    """
    trailing()
    assert trail(entry=None, mark=120.0, high_water=120.0) == (None, None)
    assert trail(entry=0.0, mark=120.0, high_water=120.0) == (None, None)
    assert trail(mark=None, high_water=120.0) == (None, None)
    assert trail(mark=0.0, high_water=120.0) == (None, None)


def test_an_unprotected_position_can_still_be_trailed(trailing):
    """
    No working stop on the record is not a reason to refuse — it is the case
    where raising protection matters most. (Whether an order is actually placed
    is `reconcile_trades`' decision, not this function's.)
    """
    trailing()
    assert trail(mark=118.0, high_water=120.0, working_stop=None)[0] == pytest.approx(110.4)


# ── Telling the analyst it is holding something ──────────────────────────────
#
# The analyst is called on every open position *because* "the exit decision is
# worth paying for at any score", and was never told there was a position. So it
# answered "would I buy this?" and its SELL meant "bad name to own" rather than
# "take the profit" — which on a rip, where the company still looks excellent
# and only the price is extended, is the wrong question.

import asyncio  # noqa: E402

from app.services.analyst import _position_block, position_context  # noqa: E402


HELD = {
    "entry": 100.0, "qty": 50.0, "stop": 95.0, "target": 130.0, "peak": 122.0,
    "opened_at": datetime.now(tz=timezone.utc) - timedelta(days=6),
}


def test_the_block_states_the_position_the_peak_and_the_drawdown_from_it():
    text = _position_block(HELD, 118.0)

    assert "OPEN POSITION" in text
    assert "$100.00" in text          # blended cost
    assert "+18.0%" in text           # unrealised
    assert "$122.00" in text          # peak
    assert "3.3% below that peak" in text
    assert "Held for 6 days" in text


def test_the_block_says_the_decision_is_whether_to_keep():
    assert "whether to KEEP" in _position_block(HELD, 118.0)


def test_no_position_means_no_block_at_all():
    """
    A prompt that invents a position is worse than one that omits a real one:
    the first argues about money that is not there.
    """
    assert _position_block(None, 118.0) == ""
    assert _position_block(HELD, 0.0) == ""


def test_a_position_never_observed_omits_the_peak_rather_than_faking_one():
    text = _position_block({**HELD, "peak": None}, 118.0)

    assert "Peak since entry" not in text
    assert "OPEN POSITION" in text     # the rest still stands


def test_the_system_prompt_separates_holding_from_buying():
    from app.services.analyst import _SYSTEM_PROMPT

    assert "OPEN POSITION" in _SYSTEM_PROMPT
    assert "whether to KEEP it" in _SYSTEM_PROMPT
    # And it still refuses to read SELL as a short.
    assert "never opens shorts" in _SYSTEM_PROMPT


class _Trades:
    def __init__(self, rows):
        self._rows = rows

    def find(self, *_a, **_k):
        rows = self._rows
        class _C:
            async def to_list(self, length=None):
                return rows
        return _C()


def _ctx(monkeypatch, rows):
    import app.services.analyst as A

    async def fake_db():
        return {"trades": _Trades(rows)}

    monkeypatch.setattr(A, "get_db", fake_db)
    monkeypatch.setattr(A, "COLL_TRADES", "trades")
    return asyncio.run(position_context("EXMP"))


def test_two_lots_blend_into_one_cost_basis(monkeypatch):
    pos = _ctx(monkeypatch, [
        {"entry_price": 100.0, "filled_qty": 100, "stop_loss": 95.0, "take_profit": 130.0},
        {"entry_price": 90.0, "filled_qty": 100, "stop_loss": 88.0, "take_profit": 125.0},
    ])

    assert pos["qty"] == 200
    assert pos["entry"] == pytest.approx(95.0)
    # The tightest stop and the nearest target resolve the position first.
    assert pos["stop"] == 95.0
    assert pos["target"] == 125.0


def test_an_unfilled_order_is_not_a_position(monkeypatch):
    """Counting it would report a cost basis for shares nobody owns."""
    assert _ctx(monkeypatch, [{"limit_price": 100.0, "qty": 50}]) is None


def test_nothing_held_returns_none(monkeypatch):
    assert _ctx(monkeypatch, []) is None


def test_a_database_error_returns_none_rather_than_guessing(monkeypatch):
    import app.services.analyst as A

    async def boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(A, "get_db", boom)
    assert asyncio.run(position_context("EXMP")) is None


def test_the_highest_peak_across_lots_wins(monkeypatch):
    pos = _ctx(monkeypatch, [
        {"entry_price": 100.0, "filled_qty": 10, "high_water_price": 118.0},
        {"entry_price": 100.0, "filled_qty": 10, "high_water_price": 122.0},
    ])
    assert pos["peak"] == 122.0


# ── The wiring: the one thing here that can cancel a live stop ───────────────

import app.services.trade_manager as tm  # noqa: E402


class _Broker:
    def __init__(self, working=True, place=True, cancels_work=True):
        self.working = working
        self.place = place
        self.cancels_work = cancels_work
        self.placed: list[tuple] = []
        self.cancelled = 0

    async def has_open_orders(self, ticker, account_id=""):
        return self.working

    async def cancel_open_orders(self, ticker, account_id=""):
        self.cancelled += 1
        if self.cancels_work:
            self.working = False
        return 2

    async def place_protective_orders(self, ticker, qty, stop, target, account_id=""):
        if not self.place:
            return None
        self.placed.append((ticker, qty, stop, target))
        self.working = True
        return "oca-1"


def run_trail(monkeypatch, trade, mark, broker=None):
    """Drive `_track_and_trail` against a stub venue; returns (result, writes)."""
    broker = broker or _Broker()
    writes: list[dict] = []

    async def _update(_id, update):
        writes.append(update)

    monkeypatch.setattr(tm, "ibkr", broker)
    monkeypatch.setattr(tm, "_update_trade", _update)
    trade.setdefault("_id", "t1")
    trade.setdefault("action", "BUY")
    trade.setdefault("closed_at", None)
    trade.setdefault("ticker", "EXMP")
    result = asyncio.run(
        tm._track_and_trail(trade, {"EXMP": 50}, {"EXMP": mark}, "DU1")
    )
    return result, writes, broker


OPEN = {"entry_price": 100.0, "filled_qty": 50, "stop_loss": 95.0, "take_profit": 140.0}


def test_the_excursion_is_recorded_even_with_the_trail_off(monkeypatch, trailing):
    """The measurement ships regardless; only the behaviour is gated."""
    trailing(trailing_stop_enabled=False)
    (marked, trailed), writes, broker = run_trail(monkeypatch, dict(OPEN), 118.0)

    assert (marked, trailed) == (True, False)
    assert writes[0]["high_water_price"] == 118.0
    assert broker.placed == []


def test_a_new_high_this_pass_trails_from_itself(monkeypatch, trailing):
    """
    Not from the previous peak — otherwise the stop lags the price by a full
    cycle on exactly the fast moves the trail exists to catch.
    """
    trailing()
    trade = dict(OPEN, high_water_price=110.0)
    (_, trailed), writes, broker = run_trail(monkeypatch, trade, 130.0)

    assert trailed is True
    # 130 × 0.92 = 119.6, from this pass's high, not 110 × 0.92 = 101.2.
    assert broker.placed[-1][2] == pytest.approx(119.6)
    assert writes[-1]["stop_loss"] == pytest.approx(119.6)
    assert writes[-1]["stop_raised_by"] == "trail"
    assert writes[-1]["stop_raise_count"] == 1


def test_an_unprotected_position_is_left_for_the_heal_phase(monkeypatch, trailing):
    """
    Nothing to cancel, and `_heal_unprotected` is about to re-place from the
    record in this same pass. Both acting would put two pairs on one holding.
    """
    trailing()
    (_, trailed), writes, broker = run_trail(
        monkeypatch, dict(OPEN), 130.0, _Broker(working=False),
    )

    assert trailed is False
    assert broker.placed == []
    # The excursion is still recorded; only the placement is deferred.
    assert any("high_water_price" in w for w in writes)


def test_a_refused_placement_never_writes_the_tighter_stop(monkeypatch, trailing):
    """
    A record claiming protection the venue never took is the one direction of
    error that makes a position look safer than it is.
    """
    trailing()
    (_, trailed), writes, _ = run_trail(
        monkeypatch, dict(OPEN), 130.0, _Broker(place=False),
    )

    assert trailed is False
    assert not any("stop_loss" in w for w in writes)


def test_a_cancel_that_does_not_take_aborts_rather_than_double_bracketing(
    monkeypatch, trailing,
):
    """`_reprotect`'s own guard, reached through this path."""
    trailing()
    (_, trailed), writes, broker = run_trail(
        monkeypatch, dict(OPEN), 130.0, _Broker(cancels_work=False),
    )

    assert trailed is False
    assert broker.placed == []
    assert not any("stop_loss" in w for w in writes)


def test_a_closed_or_unheld_row_is_skipped(monkeypatch, trailing):
    trailing()
    from datetime import datetime as _dt
    closed = dict(OPEN, closed_at=_dt.now(tz=timezone.utc))
    assert run_trail(monkeypatch, closed, 130.0)[0] == (False, False)

    broker, writes = _Broker(), []

    async def _update(_id, update):
        writes.append(update)

    monkeypatch.setattr(tm, "ibkr", broker)
    monkeypatch.setattr(tm, "_update_trade", _update)
    flat = dict(OPEN, _id="t1", action="BUY", closed_at=None, ticker="EXMP")
    # Held nothing, and no mark for it.
    assert asyncio.run(tm._track_and_trail(flat, {"EXMP": 0}, {}, "DU1")) == (False, False)
    assert writes == []


def test_the_new_pair_covers_the_held_quantity_and_ratchets_the_target(
    monkeypatch, trailing,
):
    """
    Protective orders may never cover more shares than are held, and the target
    moves up with the peak rather than staying where entry put it. Leaving it
    alone is what made the trail inert: the limit leg filled first, every time.
    """
    trailing()
    _, _, broker = run_trail(monkeypatch, dict(OPEN), 130.0)

    ticker, qty, _stop, target = broker.placed[-1]
    # 130 × 1.10, ahead of the peak — not the 140 the record carried in.
    assert (ticker, qty, target) == ("EXMP", 50, 143.0)


# ── The EXIT_ALERT counterfactual ─────────────────────────────────────────────
#
# Nothing sells on the overbought flag and nothing here changes that. What was
# missing was the evidence to argue about it: `setup_trigger` is retained on the
# signal row, which is a fact about a ticker, while the exit question is about a
# position's path. These pin the record that makes the comparison possible.

def test_the_alert_return_is_measured_against_entry():
    """Directly comparable with `return_pct` and `mfe_pct`, no third
    denominator to keep track of."""
    trade = dict(entry_price=100.0, high_water_price=130.0,
                 first_exit_alert_price=120.0)
    out = tm._excursion_summary(trade, 110.0)

    assert out["return_at_first_exit_alert_pct"] == pytest.approx(0.20)
    assert out["mfe_pct"] == pytest.approx(0.30)
    # Held past the alert and gave back 10 points of the 30 it had made.
    assert out["gave_back_pct"] == pytest.approx(0.20)


def test_a_position_that_never_drew_an_alert_reports_no_number():
    """
    Not 0.0 — that would read as "selling on the alert would have changed
    nothing", flatteringly, in the same direction, every time. The
    `commission_paid` rule.
    """
    out = tm._excursion_summary(dict(entry_price=100.0, high_water_price=130.0), 110.0)
    assert "return_at_first_exit_alert_pct" not in out


def test_the_first_alert_is_written_once_and_the_count_keeps_going(monkeypatch):
    """
    The first alert is the moment the flag fired, not the last time it was still
    firing — those are different facts, and only the first is a decision point.
    """
    import app.services.pipeline as P

    calls: list[tuple[dict, dict]] = []

    class _Trades:
        async def update_many(self, flt, update):
            calls.append((flt, update))

    async def fake_db():
        return {"trades": _Trades()}

    monkeypatch.setattr(P, "get_db", fake_db)
    monkeypatch.setattr(P, "COLL_TRADES", "trades")
    asyncio.run(P._stamp_exit_alert("EXMP", "EXIT_ALERT", 120.0))

    first, counter = calls
    # The stamp is guarded on the field being absent, so it cannot be revised.
    assert first[0]["first_exit_alert_at"] == {"$exists": False}
    assert first[1]["$set"]["first_exit_alert_price"] == 120.0
    # The counter is unguarded and separate: "flagged once and kept running" and
    # "flagged twenty times" are different stories about the same peak.
    assert counter[1] == {"$inc": {"exit_alert_count": 1}}
    assert "first_exit_alert_at" not in counter[0]


def test_nothing_is_stamped_without_an_alert_or_a_price(monkeypatch):
    import app.services.pipeline as P

    calls: list = []

    class _Trades:
        async def update_many(self, flt, update):
            calls.append((flt, update))

    async def fake_db():
        return {"trades": _Trades()}

    monkeypatch.setattr(P, "get_db", fake_db)
    monkeypatch.setattr(P, "COLL_TRADES", "trades")

    asyncio.run(P._stamp_exit_alert("EXMP", "ENTRY", 120.0))
    asyncio.run(P._stamp_exit_alert("EXMP", "NEUTRAL", 120.0))
    asyncio.run(P._stamp_exit_alert("EXMP", "EXIT_ALERT", None))
    assert calls == []


def test_the_overbought_flag_still_sells_nothing():
    """
    The vocabulary 1.28.0 deleted stays deleted. A reason string for an exit
    that cannot happen is the same class of lie as a gate panel contradicting
    the badge beside it — it comes back with the code that writes it.
    """
    from app.services.trade_rationale import _EXIT_REASON

    assert "EXIT_ALERT" not in _EXIT_REASON
