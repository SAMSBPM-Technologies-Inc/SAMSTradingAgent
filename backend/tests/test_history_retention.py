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

#: The dip-buy setup behind the verdict. Same failure mode, different question:
#: the declared strategy is mean-reversion, and `score` is a blend of six
#: factors that cannot be taken apart twenty days later. Without these, "did an
#: entry setup predict forward alpha" is unanswerable however long anyone waits.
SETUP_FIELDS = {
    "technical_score", "setup_trigger",
    "rsi_14", "stoch_rsi", "bb_pct", "macd_bullish", "ma_cross_bullish",
}

#: The number the SELL test was actually measured against. The composite ranks
#: entry opportunity; the exit reading swaps its oscillator component for trend
#: and relative strength (`scoring.exit_score`). It is recomputed from
#: sub-scores, so a replay would recompute it from whatever the weights are by
#: then and describe a rule that never ran — the `score_percentile` trap.
EXIT_FIELDS = {"exit_score"}

RETAINED_FIELDS = OVERRIDE_FIELDS | SETUP_FIELDS | EXIT_FIELDS


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


#: A textbook dip: oversold on all three oscillators with the trend intact.
PULLBACK = {
    "technical_score": 0.907, "rsi_14": 24.0, "stoch_rsi": 0.10, "bb_pct": 0.20,
    "macd_bullish": True, "ma_cross_bullish": True,
}

#: The same oscillator readings with the trend gone — the case the ENTRY badge
#: used to call identical to the one above.
KNIFE = {**PULLBACK, "technical_score": 0.388,
         "macd_bullish": False, "ma_cross_bullish": False}


def append(monkeypatch, signal, feat=None):
    history = _History()

    async def fake_get_db():
        return _Db(history)

    monkeypatch.setattr(P, "get_db", fake_get_db)
    asyncio.run(P._append_history(
        signal, {"current_price": 100.0}, PULLBACK if feat is None else feat,
    ))
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
    asyncio.run(P._append_history(signal_doc(), {"current_price": 100.0}, PULLBACK))


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
        for field in RETAINED_FIELDS:
            assert f'"{field}"' in projection, (
                f"{path.name} drops {field} — it would be invisible to the "
                f"report that reads it"
            )


# ── The setup behind the verdict ──────────────────────────────────────────────

def test_the_setup_indicators_are_retained(monkeypatch):
    """
    The raw indicators, not just the verdict they produced. Thresholds are
    tunable, so a replay that recomputed the trigger from today's constants
    would describe a rule that was never run — the indicators are what a
    different rule can actually be tested against.
    """
    rec = written(append(monkeypatch, signal_doc()))

    assert SETUP_FIELDS <= set(rec)
    assert rec["rsi_14"] == 24.0
    assert rec["stoch_rsi"] == 0.10
    assert rec["bb_pct"] == 0.20
    assert rec["technical_score"] == 0.907


def test_the_trigger_is_stored_as_well_as_its_inputs(monkeypatch):
    """Both, for the reason above — neither is recoverable from the other."""
    assert written(append(monkeypatch, signal_doc()))["setup_trigger"] == "ENTRY"


def test_the_stored_trigger_is_trend_gated_like_the_badge(monkeypatch):
    """
    Identical oscillator readings, opposite trend. If the retained series could
    not tell these apart, the sample it exists to build would pool a pullback
    with a falling knife and measure neither.
    """
    knife = written(append(monkeypatch, signal_doc(), KNIFE))

    assert knife["setup_trigger"] == "NEUTRAL"
    assert knife["rsi_14"] == 24.0            # same oversold reading
    assert knife["ma_cross_bullish"] is False  # different trend


def test_a_feature_document_with_no_indicators_writes_nulls_not_absences(
    monkeypatch,
):
    """
    The `analyst_override` convention. `None` means this code wrote the row and
    the indicator was not computed; the key being ABSENT means the row predates
    this and must be excluded rather than counted as a missing indicator.
    """
    rec = written(append(monkeypatch, signal_doc(), {}))

    assert SETUP_FIELDS <= set(rec)
    assert rec["rsi_14"] is None
    assert rec["technical_score"] is None
    assert rec["setup_trigger"] == "NEUTRAL"
