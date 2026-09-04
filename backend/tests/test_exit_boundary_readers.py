"""
Everything downstream that reads the SELL boundary.

1.31.0 split the entry test from the exit test: BUY reads the composite, SELL
reads `scoring.exit_score`. It rewired the three places that *decide* a verdict
— `classify_signal`, `_classify_relative`, `_gate_analyst_signal` — and left
every place that *describes* one still assuming a single number did both jobs.

Three readers were wrong in three different ways, and none of them failed
loudly:

  * `boundary_confidence` measured a SELL's distance from the composite, so a
    verdict two points past its threshold stored confidence 0.0 and fed that to
    the calibration buckets;
  * `_analyst_worth_calling` measured the SELL band on the composite, so the
    call was skipped on names one tick from an exit and spent on names nowhere
    near one;
  * `_publish_verdict` corrected the verdict and left the candidate's derived
    fields in place, so a held-back BUY kept a full buy plan — entry, stop and
    target — underneath a published HOLD.

The last is the defect `_gate_analyst_signal` exists to prevent, reintroduced
one layer above it.

`test_the_whole_document_is_coherent_at_one_exit_driven_sell` is the test that
would have caught all three: one synthetic ticker at composite 0.4125 / exit
reading 0.2925, walked end to end.

Run with:  pytest backend/tests -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, get_settings  # noqa: E402
from app.services import pipeline as P  # noqa: E402
from app.services.cross_section import Cohort  # noqa: E402
from app.services.signal_generator import (  # noqa: E402
    RANK_MIN_COHORT, SELL_THRESHOLD, boundary_confidence, classify_signal,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

#: A falling knife. Deeply oversold oscillators — which the composite *rewards*
#: under `mean_reversion`, because an oversold reading is the entry timer — over
#: a broken trend and no relative strength at all.
#:
#: Composite **0.4125**, so the composite alone holds it. Exit reading
#: **0.2925**, so the exit test sells it. That gap is the entire reason the two
#: numbers exist, and every assertion below depends on it.
DETERIORATING = {
    "technical_score": 0.40, "fundamental_score": 0.40, "sentiment_score": 0.35,
    "macro_score": 0.50, "volatility_score": 0.50, "catalyst_score": 0.45,
    "momentum_score": 0.0, "momentum_coverage": 1.0,
    "alternative_data_score": 0.5,
    "macd_bullish": False, "ma_cross_bullish": False,
    "current_price": 100.0, "volatility_20d": 0.30,
}
DETERIORATING["composite_score"] = 0.4125

#: The mirror image, and the incident that produced the exit reading: a leader
#: running away from its cost basis. The oscillators are pinned overbought so
#: `_technical_score` floors it at 0.05 — a correct answer to "is there a dip to
#: buy here" — while trend and relative strength are both intact.
#:
#: Composite **0.3750**, which sits inside the old SELL band. Exit reading
#: **0.6435**, which is nowhere near one.
EXTENDED_LEADER = {
    "technical_score": 0.05, "fundamental_score": 0.55, "sentiment_score": 0.50,
    "macro_score": 0.50, "volatility_score": 0.50, "catalyst_score": 0.50,
    "momentum_score": 0.90, "momentum_coverage": 1.0,
    "alternative_data_score": 0.5,
    "macd_bullish": True, "ma_cross_bullish": True,
    "current_price": 100.0, "volatility_20d": 0.30,
}
EXTENDED_LEADER["composite_score"] = 0.3750


def exit_reading(feat):
    from app.services.scoring import exit_score
    return exit_score(feat)


# ── The reading itself ────────────────────────────────────────────────────────

def test_the_fixture_really_does_separate_the_two_numbers():
    """
    Guard the premise. If the exit reading ever stopped diverging from the
    composite here, every assertion below would pass vacuously.
    """
    reading = exit_reading(DETERIORATING)
    assert reading is not None
    assert reading < SELL_THRESHOLD < DETERIORATING["composite_score"], (
        f"composite {DETERIORATING['composite_score']}, exit reading {reading}"
    )
    leader = exit_reading(EXTENDED_LEADER)
    assert EXTENDED_LEADER["composite_score"] < leader, (
        "the leader's composite must sit below its exit reading, or the "
        "inversion this fixture stands for is not being reproduced"
    )


def test_the_exit_reading_is_what_publishes_the_sell():
    score = DETERIORATING["composite_score"]
    reading = exit_reading(DETERIORATING)
    assert classify_signal(score, 2.0, exit_score=reading) == "SELL"
    assert classify_signal(score, 2.0) == "HOLD", (
        "the composite alone would hold this — that is the whole point"
    )


def test_the_extended_leader_is_no_longer_sold_for_being_extended():
    """
    The incident. A leader up 24% in six months, sold because the dip-buy timer
    said "do not enter here" — a correct answer to a question nobody asked.
    """
    score = EXTENDED_LEADER["composite_score"]
    reading = exit_reading(EXTENDED_LEADER)
    assert classify_signal(score, 2.0, exit_score=reading) == "HOLD"


# ── Reader 1: confidence ──────────────────────────────────────────────────────

def test_an_exit_driven_sell_carries_real_confidence():
    score = DETERIORATING["composite_score"]
    reading = exit_reading(DETERIORATING)
    stored = boundary_confidence(score, "SELL", sell_basis=reading)
    assert stored == pytest.approx((SELL_THRESHOLD - reading) / SELL_THRESHOLD)
    assert boundary_confidence(score, "SELL") == 0.0, (
        "the premise: measured from the composite this was exactly 0.0 — a "
        "verdict past its threshold reported as maximally marginal, and that "
        "number went into the calibration buckets"
    )
    assert stored > 0.0


# ── Reader 2: the analyst spend gate ──────────────────────────────────────────

def _worth_calling(feat, *, holding=False, ranked=False, monkeypatch=None):
    monkeypatch.setattr(P, "_has_open_position", _returns(holding))
    base = get_settings()
    settings = Settings(
        analyst_gate_enabled=True,
        analyst_gate_margin=base.analyst_gate_margin,
        analyst_always_analyse_holdings=True,
        enable_rank_signals=ranked,
    )
    monkeypatch.setattr(P, "get_settings", lambda: settings)
    return asyncio.run(P._analyst_worth_calling("EXMP", feat))


def _returns(value):
    async def _f(*_a, **_k):
        return value
    return _f


def test_a_name_one_tick_from_an_exit_is_worth_the_call(monkeypatch):
    """
    A falling knife: composite 0.4125, comfortably mid-range, over an exit
    reading of 0.2925 that is already past the sell threshold. Measured on the
    composite this reported `mid_range` and the second opinion was never
    bought — on the one name where the rule was about to publish an exit.
    """
    feat = DETERIORATING
    margin = get_settings().analyst_gate_margin
    assert exit_reading(feat) <= SELL_THRESHOLD + margin
    assert feat["composite_score"] > SELL_THRESHOLD + margin, (
        "the premise: measured on the composite this reported mid_range"
    )
    worth, reason = _worth_calling(feat, monkeypatch=monkeypatch)
    assert worth is True
    assert reason.startswith("near_sell"), reason


def test_a_low_composite_in_good_condition_does_not_spend_the_call(monkeypatch):
    """
    The mirror image: composite 0.3750 sits inside the SELL band and the name
    is not remotely a sell — trend intact, relative strength strong, exit
    reading 0.6435. The old gate spent a research call on it every cycle.
    """
    feat = EXTENDED_LEADER
    margin = get_settings().analyst_gate_margin
    assert exit_reading(feat) > SELL_THRESHOLD + margin
    assert feat["composite_score"] <= SELL_THRESHOLD + margin, (
        "the premise: measured on the composite this spent the call"
    )
    worth, reason = _worth_calling(feat, monkeypatch=monkeypatch)
    assert worth is False, reason


def test_an_open_position_is_still_analysed_whatever_the_readings(monkeypatch):
    """The exit decision is worth paying for at any score."""
    feat = {**EXTENDED_LEADER, "composite_score": 0.50}
    worth, reason = _worth_calling(feat, holding=True, monkeypatch=monkeypatch)
    assert worth is True
    assert reason.startswith("position_open"), reason


def test_the_missing_exit_reading_falls_back_to_the_composite(monkeypatch):
    """
    On the ML path `exit_score` returns `None`. The gate must then behave
    exactly as it did before the split rather than skipping every SELL.
    """
    feat = {**DETERIORATING, "scoring_method": "xgboost",
            "composite_score": 0.33}
    assert exit_reading(feat) is None
    worth, reason = _worth_calling(feat, monkeypatch=monkeypatch)
    assert worth is True
    assert reason == "near_sell_0.33", reason


# ── Reader 3: what gets published ─────────────────────────────────────────────

def test_a_held_back_buy_does_not_publish_a_buy_plan():
    """
    The candidate's entry price, stop and target were computed for a BUY and
    persisted by the signal path's own upsert. Correcting only `signal` left a
    full buy plan sitting under a published HOLD — exactly what
    `_gate_analyst_signal` refuses to do one layer down.
    """
    signal = {
        "signal": "BUY", "score": 0.71, "exit_score": 0.55,
        "current_price": 100.0, "confidence": 0.91,
        "entry_suggestion": "$100.00 (current) or limit near $99.00",
        "exit_suggestion": "Stop-loss ~$96.25 | Take-profit ~$105.63",
    }
    P._rederive_for_published(signal, "HOLD", DETERIORATING)

    assert signal["entry_suggestion"] is None
    assert "Stop-loss" not in (signal["exit_suggestion"] or "")
    assert "Take-profit" not in (signal["exit_suggestion"] or "")


def test_the_published_verdict_gets_its_own_confidence():
    signal = {"signal": "BUY", "score": 0.71, "exit_score": 0.55,
              "current_price": 100.0, "confidence": 0.91}
    P._rederive_for_published(signal, "HOLD", DETERIORATING)
    assert signal["confidence"] != 0.91
    assert signal["confidence"] == pytest.approx(
        round(boundary_confidence(0.71, "HOLD", sell_basis=0.55), 4)
    )


def test_the_rederived_confidence_reads_the_stored_exit_score():
    """A published SELL is measured against the number that decides a SELL."""
    signal = {"signal": "HOLD", "score": 0.52, "exit_score": 0.28,
              "current_price": 100.0, "confidence": 0.05}
    P._rederive_for_published(signal, "SELL", DETERIORATING)
    assert signal["confidence"] == pytest.approx(
        round((SELL_THRESHOLD - 0.28) / SELL_THRESHOLD, 4)
    )


def test_the_rederive_uses_the_stored_cohort_not_a_fresh_one():
    """
    The rank the verdict was classified with is stored on the document for
    exactly this reason. Re-reading the watchlist half a second later could
    rank against a different field.
    """
    signal = {"signal": "BUY", "score": 0.60, "exit_score": 0.58,
              "current_price": 100.0,
              "score_percentile": 0.95, "cohort_size": 12}
    P._rederive_for_published(signal, "BUY", DETERIORATING)
    assert signal["confidence"] == pytest.approx(round(
        boundary_confidence(0.60, "BUY", Cohort(percentile=0.95, size=12),
                            sell_basis=0.58), 4
    ))


# ── The one test that would have caught all three ─────────────────────────────

def test_the_whole_document_is_coherent_at_one_exit_driven_sell(monkeypatch):
    """
    One synthetic ticker, composite 0.4125 / exit reading 0.2925, walked end to
    end.

    Every assertion here is about a *different* module agreeing with the same
    boundary. That is the property the split broke, and a single case exercising
    all of them is cheaper to keep true than three separate ones.
    """
    feat = DETERIORATING
    reading = exit_reading(feat)

    # 1. The rule publishes SELL, on the exit reading rather than the composite.
    score = feat["composite_score"]
    verdict = classify_signal(score, 2.0, exit_score=reading)
    assert verdict == "SELL"

    # 2. Its confidence describes the boundary that fired.
    confidence = boundary_confidence(score, verdict, sell_basis=reading)
    assert confidence == pytest.approx((SELL_THRESHOLD - reading) / SELL_THRESHOLD)
    assert confidence > 0

    # 3. The analyst gate agrees this was a live call.
    worth, reason = _worth_calling(feat, monkeypatch=monkeypatch)
    assert worth is True, reason

    # 4. The published document carries no entry plan and a SELL-shaped exit.
    signal = {
        "signal": "HOLD", "score": score,
        "exit_score": round(reading, 4), "current_price": 100.0,
        "confidence": 0.05, "entry_suggestion": "…", "exit_suggestion": "…",
    }
    P._rederive_for_published(signal, verdict, feat)
    assert signal["entry_suggestion"] is None
    assert "not a short signal" in signal["exit_suggestion"]
    assert signal["confidence"] == pytest.approx(round(confidence, 4))


# ── The rank fields, and the order bar that reads them ────────────────────────

def test_a_cohort_too_small_to_rank_leaves_no_rank_fields():
    """
    `cohort_for` returns a field of two or more, but `classify_signal` only uses
    the relative rule at `RANK_MIN_COHORT`. Stamping the rank fields anyway made
    `pipeline._execute_trades` read `rank_decided`, which hands
    `_order_score_bar` the rank floor (0.55) for a BUY the absolute rule
    required 0.70 of.
    """
    from app.services.trade_manager import _order_score_bar
    from app.services.signal_generator import BUY_THRESHOLD, RANK_BUY_FLOOR

    small = Cohort(percentile=0.99, size=RANK_MIN_COHORT - 1)
    # The verdict this cohort produces is the absolute one …
    assert classify_signal(0.60, 2.0, cohort=small) == "HOLD"
    # … so the order path must hold it to the absolute bar.
    assert _order_score_bar(BUY_THRESHOLD, rank_decided=False) == BUY_THRESHOLD
    assert _order_score_bar(BUY_THRESHOLD, rank_decided=True) == RANK_BUY_FLOOR


def test_the_rank_fields_are_written_only_when_the_rank_decided():
    """
    Both writers build the same conditional. Pinned by source, because they are
    two files and the consequence of a disagreement is a loosened order bar
    rather than an error.
    """
    root = Path(__file__).resolve().parents[1] / "app" / "services"
    for name in ("signal_generator.py", "analyst.py"):
        text = (root / name).read_text()
        assert (
            "if cohort is not None and cohort.size >= RANK_MIN_COHORT else {}"
            in text
        ), f"{name} stamps rank fields on verdicts the absolute rule decided"
