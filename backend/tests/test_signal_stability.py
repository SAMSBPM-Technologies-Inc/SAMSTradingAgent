"""
Tests for signal debouncing — hysteresis and flip confirmation.

The case these exist for: on 24 Aug 2026 HXL alerted eight times in sixty-five
minutes, BUY/HOLD/BUY/HOLD, with score 61 and confidence 55% in every message.
Nothing had changed about the stock. Both mechanisms below have to hold for
that to stay fixed — hysteresis stops a score jittering across a threshold from
re-deciding the ticker, and confirmation stops a re-sampled analyst verdict
from reaching the user before it has held.

Run with:  pytest backend/tests -q
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.signal_generator import (  # noqa: E402
    BUY_THRESHOLD, SELL_THRESHOLD, SIGNAL_HYSTERESIS, classify_signal,
)
from app.services.signal_stability import (  # noqa: E402
    StabilityState, stabilise,
)

NOW = datetime(2026, 8, 24, 15, 30, tzinfo=timezone.utc)
SAFE = 1.0  # a risk score that never blocks a BUY


def run(published, candidate, *, state=None, now=NOW, confirmations=2, dwell=60):
    return stabilise(
        published=published,
        candidate=candidate,
        now=now,
        state=state or StabilityState(),
        confirmations=confirmations,
        min_dwell_minutes=dwell,
    )


# ── Hysteresis: an established verdict is sticky ──────────────────────────────

def test_entering_buy_still_requires_clearing_the_threshold():
    """The band makes a verdict harder to lose, never easier to acquire."""
    just_under = BUY_THRESHOLD - SIGNAL_HYSTERESIS / 2
    assert classify_signal(just_under, SAFE, previous_signal="HOLD") == "HOLD"
    assert classify_signal(just_under, SAFE, previous_signal=None) == "HOLD"


def test_an_existing_buy_survives_a_dip_inside_the_band():
    inside = BUY_THRESHOLD - SIGNAL_HYSTERESIS / 2
    assert classify_signal(inside, SAFE, previous_signal="BUY") == "BUY"


def test_an_existing_buy_is_given_up_beyond_the_band():
    beyond = BUY_THRESHOLD - SIGNAL_HYSTERESIS - 0.001
    assert classify_signal(beyond, SAFE, previous_signal="BUY") == "HOLD"


def test_hysteresis_applies_to_sell_symmetrically():
    inside = SELL_THRESHOLD + SIGNAL_HYSTERESIS / 2
    assert classify_signal(inside, SAFE, previous_signal="SELL") == "SELL"
    assert classify_signal(inside, SAFE, previous_signal="HOLD") == "HOLD"


def test_risk_still_vetoes_a_buy_the_band_would_otherwise_hold():
    """Stickiness must not outrank the risk gate."""
    from app.services.risk_engine import RISK_MAX_FOR_BUY
    inside = BUY_THRESHOLD - SIGNAL_HYSTERESIS / 2
    assert classify_signal(inside, RISK_MAX_FOR_BUY, previous_signal="BUY") == "HOLD"


def test_omitting_the_previous_signal_gives_the_raw_rule():
    """Calibration replays history and has no 'previous' to speak of."""
    for score in (0.1, 0.29, 0.31, 0.5, 0.69, 0.71, 0.9):
        assert classify_signal(score, SAFE) == classify_signal(score, SAFE, None)


# ── Confirmation: a flip must repeat before it is published ───────────────────

def test_first_ever_verdict_publishes_immediately():
    d = run(None, "BUY")
    assert (d.signal, d.changed) == ("BUY", False)
    assert d.state.last_published_change == NOW


def test_a_single_flip_is_withheld():
    d = run("HOLD", "BUY")
    assert (d.signal, d.changed) == ("HOLD", False)
    assert d.held_back == "BUY"
    assert d.state.pending_count == 1


def test_the_hxl_sequence_publishes_nothing():
    """
    The exact alternation that produced eight alerts. An oscillating verdict
    never accumulates two agreeing evaluations in a row, so it never publishes
    and the user hears nothing — which is the honest report of a ticker sitting
    on a threshold.
    """
    published, state = "HOLD", StabilityState(last_published_change=NOW - timedelta(hours=6))
    alerts = 0
    for i, candidate in enumerate(["BUY", "HOLD"] * 4):
        d = run(published, candidate, state=state, now=NOW + timedelta(minutes=5 * i))
        alerts += int(d.changed)
        published, state = d.signal, d.state
    assert alerts == 0
    assert published == "HOLD"


def test_a_flip_that_repeats_is_published():
    old = NOW - timedelta(hours=6)
    first = run("HOLD", "BUY", state=StabilityState(last_published_change=old))
    second = run("HOLD", "BUY", state=first.state, now=NOW + timedelta(hours=1))
    assert (second.signal, second.changed) == ("BUY", True)


def test_agreement_clears_a_half_formed_candidate():
    """
    A flip that did not survive must not linger and combine with an unrelated
    one later — two BUY candidates an hour apart, separated by a HOLD, are not
    a confirmed BUY.
    """
    first = run("HOLD", "BUY")
    assert first.state.pending_count == 1
    settled = run("HOLD", "HOLD", state=first.state)
    assert settled.state.pending_signal is None
    again = run("HOLD", "BUY", state=settled.state)
    assert again.state.pending_count == 1
    assert again.changed is False


def test_dwell_holds_a_confirmed_flip_until_the_verdict_has_stood():
    """Confirmed twice, but the published verdict is eight minutes old."""
    recent = StabilityState(
        pending_signal="BUY", pending_count=1, pending_since=NOW,
        last_published_change=NOW - timedelta(minutes=8),
    )
    d = run("HOLD", "BUY", state=recent, dwell=60)
    assert (d.signal, d.changed) == ("HOLD", False)
    assert "dwell" in d.reason


def test_sell_is_never_delayed():
    """
    Delaying an exit costs money; delaying an entry costs an opportunity. The
    debounce must not make it harder to leave a position than to enter one.
    """
    recent = StabilityState(last_published_change=NOW - timedelta(seconds=30))
    d = run("BUY", "SELL", state=recent, confirmations=5, dwell=1440)
    assert (d.signal, d.changed) == ("SELL", True)


def test_dwell_of_zero_disables_the_wait_but_not_the_confirmation():
    first = run("HOLD", "BUY", dwell=0)
    assert first.changed is False
    second = run("HOLD", "BUY", state=first.state, dwell=0)
    assert (second.signal, second.changed) == ("BUY", True)


def test_naive_timestamps_from_mongo_do_not_break_the_dwell_check():
    """Motor hands back naive datetimes; subtracting one from an aware raises."""
    naive = StabilityState(
        pending_signal="BUY", pending_count=1,
        last_published_change=(NOW - timedelta(hours=3)).replace(tzinfo=None),
    )
    d = run("HOLD", "BUY", state=naive)
    assert (d.signal, d.changed) == ("BUY", True)


def test_state_survives_a_round_trip_through_a_document():
    d = run("HOLD", "BUY")
    restored = StabilityState.from_doc({"stability": d.state.to_doc()})
    assert restored == d.state


# ── The pipeline's publish step ───────────────────────────────────────────────

class _FakeCollection:
    def __init__(self):
        self.updates = []

    async def update_one(self, flt, update):
        self.updates.append((flt, update))


class _FakeDb:
    def __init__(self):
        self.coll = _FakeCollection()

    def __getitem__(self, _name):
        return self.coll


def _patch_pipeline(monkeypatch, db):
    import app.services.pipeline as p

    async def fake_get_db():
        return db

    monkeypatch.setattr(p, "get_db", fake_get_db)
    return p


def test_publish_step_writes_the_held_verdict_not_the_candidate(monkeypatch):
    """
    The candidate must not reach the stored document, the history record, the
    alert or the trade path — `_publish_verdict` mutates the signal dict in
    place so all four read the same published verdict.
    """
    import asyncio

    db = _FakeDb()
    p = _patch_pipeline(monkeypatch, db)

    signal = {"ticker": "HXL", "signal": "BUY", "explanation": "HXL -> BUY"}
    changed = asyncio.run(p._publish_verdict(
        "HXL", signal, "HOLD", StabilityState(),
        extra={"current_price": 95.2},
    ))

    assert changed is False
    assert signal["signal"] == "HOLD"
    assert "not yet confirmed" in signal["explanation"]

    written = db.coll.updates[0][1]["$set"]
    assert written["signal"] == "HOLD"
    assert written["current_price"] == 95.2
    assert written["stability"]["pending_signal"] == "BUY"


def test_publish_step_passes_a_confirmed_flip_through(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone

    db = _FakeDb()
    p = _patch_pipeline(monkeypatch, db)

    state = StabilityState(
        pending_signal="BUY", pending_count=1,
        last_published_change=datetime.now(tz=timezone.utc) - timedelta(hours=4),
    )
    signal = {"ticker": "HXL", "signal": "BUY", "explanation": "HXL -> BUY"}
    changed = asyncio.run(p._publish_verdict(
        "HXL", signal, "HOLD", state, extra={},
    ))

    assert changed is True
    assert signal["signal"] == "BUY"
    assert "not yet confirmed" not in signal["explanation"]
    assert db.coll.updates[0][1]["$set"]["stability"]["pending_signal"] is None
