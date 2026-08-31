"""
Tests for what `stocks_signal_history` actually keeps.

`analyst_gate` is written to `stocks_signals`, which holds one document per
ticker and is replaced on every cycle. So the record of the gate refusing the
analyst survived roughly five minutes and left nothing behind but a log line —
there was no sample anywhere from which to ask whether those refusals were
worth making. This series is the only retained record, and until the override
reached it the calibration question could not be asked at all, however long
anyone waited.

The failure mode being fenced here is silence, not error: a field missing from
`_append_history`, or dropped by one of the two explicit projections over this
collection, produces a report that looks complete and describes nothing.

Run with:  pytest backend/tests -q
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import pipeline as P  # noqa: E402

#: The fields Phase 1 exists to retain.
OVERRIDE_FIELDS = {"analyst_override", "analyst_wanted", "rule_signal"}


class _History:
    def __init__(self):
        self.writes = []

    async def update_one(self, query, update, upsert=False):
        self.writes.append((query, update, upsert))


class _Db:
    def __init__(self, history):
        self._history = history

    def __getitem__(self, _name):
        return self._history


def append(monkeypatch, signal):
    history = _History()

    async def fake_get_db():
        return _Db(history)

    monkeypatch.setattr(P, "get_db", fake_get_db)
    asyncio.run(P._append_history(signal, {"current_price": 100.0}))
    return history


def signal_doc(**over):
    from datetime import datetime, timezone
    base = {
        "ticker": "EXMP",
        "generated_at": datetime(2026, 8, 31, 14, 5, tzinfo=timezone.utc),
        "signal": "HOLD",
        "score": 0.62,
        "confidence": 0.2,
        "risk": {"risk_score": 2.0},
        "analyst_used": True,
    }
    base.update(over)
    return base


def written(history):
    """The record `$setOnInsert` would write."""
    return history.writes[0][1]["$setOnInsert"]


# ── The record ────────────────────────────────────────────────────────────────

def test_a_refused_buy_is_retained(monkeypatch):
    rec = written(append(monkeypatch, signal_doc(analyst_gate={
        "model_signal": "BUY", "rule_signal": "HOLD", "overridden": True,
        "override": "buy_refused", "reason": "…under the 0.70 a BUY needs.",
    })))

    assert rec["analyst_override"] == "buy_refused"
    assert rec["analyst_wanted"] == "BUY"
    assert rec["rule_signal"] == "HOLD"


def test_a_restored_sell_is_retained(monkeypatch):
    rec = written(append(monkeypatch, signal_doc(
        signal="SELL", score=0.18,
        analyst_gate={
            "model_signal": "HOLD", "rule_signal": "SELL", "overridden": True,
            "override": "sell_restored", "reason": "…never held back.",
        },
    )))

    assert rec["analyst_override"] == "sell_restored"
    assert rec["analyst_wanted"] == "HOLD"


def test_an_agreeing_gate_records_a_null_override_not_an_absent_one(monkeypatch):
    """
    The distinction the whole counterfactual rests on. `None` here means the
    gate ran and had nothing to override; the key being *absent* means the row
    predates this and can say nothing either way. A consumer that cannot tell
    them apart will count old rows as agreement and dilute every bucket.
    """
    rec = written(append(monkeypatch, signal_doc(analyst_gate={
        "model_signal": "BUY", "rule_signal": "BUY", "overridden": False,
        "override": None, "reason": None,
    })))

    assert OVERRIDE_FIELDS <= set(rec)
    assert rec["analyst_override"] is None
    assert rec["analyst_wanted"] == "BUY"


def test_a_rule_only_cycle_still_writes_the_keys(monkeypatch):
    """
    No analyst ran, so there is nothing to override — but the keys are present
    and null, which is what marks the row as one this code wrote.
    """
    rec = written(append(monkeypatch, signal_doc(analyst_used=False)))

    assert OVERRIDE_FIELDS <= set(rec)
    assert rec["analyst_override"] is None
    assert rec["analyst_wanted"] is None


def test_the_prose_reason_is_not_retained(monkeypatch):
    """
    Reconstructible from the other three, and otherwise written ~24 times a day
    per ticker to say the same sentence.
    """
    rec = written(append(monkeypatch, signal_doc(analyst_gate={
        "model_signal": "BUY", "rule_signal": "HOLD", "overridden": True,
        "override": "buy_refused", "reason": "…under the 0.70 a BUY needs.",
    })))

    assert "reason" not in rec
    assert "analyst_gate" not in rec


def test_the_outcome_fields_are_still_left_for_settlement(monkeypatch):
    """A guard against the new fields displacing what fills in at 20 days."""
    rec = written(append(monkeypatch, signal_doc()))

    assert rec["return_20d"] is None
    assert rec["price_20d_later"] is None


def test_a_write_failure_never_fails_the_cycle(monkeypatch):
    async def boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(P, "get_db", boom)
    # Returns rather than raising: losing a history row is a lost data point,
    # and taking the pipeline down over it would lose the verdict too.
    asyncio.run(P._append_history(signal_doc(), {"current_price": 100.0}))


# ── The two projections ───────────────────────────────────────────────────────

def test_both_projections_over_the_history_collection_carry_the_fields():
    """
    There are two explicit field lists reading `stocks_signal_history` —
    `calibration.calibration_report` and the `/performance/calibration` route.
    A field named in one and not the other is not an error: Mongo drops it
    silently, and the report renders a confident-looking page describing
    nothing. Neither list can be trusted to be updated by hand, so it is
    checked here.
    """
    root = Path(__file__).resolve().parents[1] / "app"
    sources = [
        root / "services" / "calibration.py",
        root / "routes" / "performance.py",
    ]

    for path in sources:
        text = path.read_text()
        # The projection dict passed alongside the COLL_SIGNAL_HISTORY query.
        block = re.search(
            r"COLL_SIGNAL_HISTORY\]\.find\(\s*query,\s*\{(.*?)\}\s*,?\s*\)",
            text, re.S,
        )
        assert block, f"no history projection found in {path.name}"
        projection = block.group(1)
        for field in OVERRIDE_FIELDS:
            assert f'"{field}"' in projection, (
                f"{path.name} drops {field} — the override would be invisible "
                f"to the report that reads it"
            )
