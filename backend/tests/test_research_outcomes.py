"""
Tests for the outcome memory loop.

`research_dossiers` was written as a retained series and read one document at a
time, newest first. No reading was ever compared to a result, so no agent had
been told it was wrong about a name and `RESEARCH_VETO_MIN_CONVICTION` sat at a
guessed number with nothing behind it. This closes that loop.

Four properties carry the design, and each has a way of failing silently:

  * a reading is graded on ALPHA, not on raw return — settled the other way the
    loop would teach the agents to prefer beta, which is the exact failure the
    benchmark work exists to expose;
  * an ungraded reading (NEUTRAL, or a window with no benchmark) is None and
    never False — a miss and "cannot say" mean opposite things in an average;
  * the written lesson is CITATION-FILTERED against the dossier's own stored
    ledger, so unattributable prose can never be injected into a future prompt;
  * the prior record enters as `meta=True` ledger evidence and never reaches
    the conviction anchor — memory can temper a reading, never manufacture one.

Run with:  pytest backend/tests -q
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.research import outcomes as O  # noqa: E402
from app.services.research import prior_record as PR  # noqa: E402
from app.services.research.evidence import Ledger  # noqa: E402

BASE = datetime(2026, 7, 1, tzinfo=timezone.utc)
LATER = BASE + timedelta(days=21)


def series(start, closes):
    return pd.Series(
        closes,
        index=pd.DatetimeIndex(
            [start + timedelta(days=i) for i in range(len(closes))], tz=timezone.utc
        ),
    )


def dossier(assessment="BULLISH", conviction=72.0, evidence=None):
    return {
        "ticker": "EXMP",
        "as_of": BASE.isoformat(),
        "generated_at": BASE,
        "research_conviction": conviction,
        "report": {
            "assessment": assessment,
            "thesis": "Compounding at scale [F2].",
            "bear_case": "Valuation is full [V1].",
            "what_would_change_my_opinion": ["Gross margin below 55% [F2]"],
        },
        "evidence": evidence if evidence is not None else [
            {"id": "F2", "claim": "Gross margin", "value": "58%",
             "source": "filings", "as_of": "2026-06-30"},
            {"id": "V1", "claim": "P/E", "value": "41x",
             "source": "provider", "as_of": "2026-06-30"},
        ],
    }


# ── Grading: alpha, not raw return ────────────────────────────────────────────

def test_bullish_that_beat_the_market_is_correct():
    assert O.assessment_correct("BULLISH", 0.03) is True


def test_bullish_that_rose_but_lost_to_the_market_is_wrong():
    """
    The whole reason Phase 1 had to land first. +4% in a +9% market is not a
    win, and a loop settled on raw return would have recorded it as one — then
    taught the next reading to keep doing it.
    """
    assert O.assessment_correct("BULLISH", -0.05) is False


def test_bearish_is_graded_the_other_way():
    assert O.assessment_correct("BEARISH", -0.04) is True
    assert O.assessment_correct("BEARISH", 0.04) is False


def test_neutral_is_ungraded_not_wrong():
    """
    A reading that declined to take a side cannot be graded by direction. The
    same handling `was_correct` gives HOLD — grading it anyway would reward
    whichever side the sample happened to favour.
    """
    assert O.assessment_correct("NEUTRAL", 0.09) is None
    assert O.assessment_correct("NEUTRAL", -0.09) is None


def test_an_unmeasurable_window_is_ungraded_not_wrong():
    assert O.assessment_correct("BULLISH", None) is None


# ── measure() ─────────────────────────────────────────────────────────────────

def test_measure_computes_return_benchmark_and_alpha():
    prices = series(BASE, [100.0] + [104.0] * 25)
    bench = series(BASE, [400.0] + [412.0] * 25)   # +3%
    got = O.measure(dossier(), prices, bench, LATER)

    assert got["return"] == pytest.approx(0.04)
    assert got["benchmark_return"] == pytest.approx(0.03)
    assert got["alpha"] == pytest.approx(0.01)
    assert got["assessment_correct"] is True
    assert got["horizon_days"] == 21


def test_measure_keeps_the_return_when_the_benchmark_is_unreadable():
    """
    A partly priced outcome is still a fact. Withholding it would discard the
    return; folding a zero benchmark in would credit the whole return as alpha.
    """
    prices = series(BASE, [100.0] + [104.0] * 25)
    got = O.measure(dossier(), prices, None, LATER)

    assert got["return"] == pytest.approx(0.04)
    assert got["benchmark_return"] is None
    assert got["alpha"] is None
    assert got["assessment_correct"] is None


def test_measure_is_none_when_the_name_itself_cannot_be_priced():
    assert O.measure(dossier(), None, None, LATER) is None


def test_measure_is_none_when_the_dossier_has_no_usable_date():
    doc = dossier()
    doc["generated_at"] = None
    doc["as_of"] = "not a date"
    prices = series(BASE, [100.0, 104.0])
    assert O.measure(doc, prices, None, LATER) is None


# ── The reflection is citation-filtered ───────────────────────────────────────

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Usage:
    input_tokens = 10
    output_tokens = 10
    cache_read_input_tokens = 0


class _Message:
    stop_reason = "end_turn"
    stop_details = None

    def __init__(self, text):
        self.content = [_Block(text)]
        self.usage = _Usage()


class _ReflectionClient:
    def __init__(self, payload):
        import json as _json
        self._text = _json.dumps(payload)

        class _M:
            async def create(_self, **kwargs):
                return _Message(self._text)

        self.messages = _M()


def _reflect(payload, doc=None):
    from app.config import get_settings

    settings = get_settings()
    measured = {
        "horizon_days": 21, "return": 0.04, "benchmark_return": 0.03,
        "alpha": 0.01, "benchmark_ticker": "SPY", "assessment_correct": True,
    }
    return asyncio.run(
        O.reflect(_ReflectionClient(payload), doc or dossier(), measured, settings)
    )


def test_a_cited_lesson_survives():
    got = _reflect({
        "lesson": "Margin durability [F2] held; the multiple [V1] did not compress.",
        "what_held": ["Gross margin stayed above 55% [F2]"],
        "what_failed": [],
    })
    assert got["uncited"] is False
    assert "[F2]" in got["lesson"]
    assert got["what_held"] == ["Gross margin stayed above 55% [F2]"]


def test_an_uncited_lesson_is_dropped_entirely():
    """
    The load-bearing test. This prose would be injected into the next dossier's
    prompt, where nothing downstream could tell a grounded claim from one that
    merely sounds grounded. The rest of the research module deletes uncited
    prose; the one piece that feeds future prompts cannot be the exception.
    """
    got = _reflect({
        "lesson": "The thesis was simply too optimistic about growth.",
        "what_held": [], "what_failed": ["Everything"],
    })
    assert got["uncited"] is True
    assert got["lesson"] is None


def test_a_fabricated_citation_is_dropped_and_recorded():
    """
    An invented id is worse than none — it survives exactly the check a reader
    would make. Recorded rather than silently removed, so the loop's own
    reliability is observable.
    """
    got = _reflect({
        "lesson": "Customer concentration [F99] was the problem all along.",
        "what_held": [], "what_failed": [],
    })
    assert got["uncited"] is True
    assert "F99" in got["fabricated_citations"]


def test_list_items_are_filtered_whole():
    got = _reflect({
        "lesson": "Margins [F2] held.",
        "what_held": ["Gross margin [F2]", "Management execution was good"],
        "what_failed": ["Valuation discipline"],
    })
    assert got["what_held"] == ["Gross margin [F2]"]
    assert got["what_failed"] == []


def test_a_dossier_with_no_stored_ledger_cannot_produce_a_cited_lesson():
    """
    Dossiers written before evidence was persisted have nothing to cite
    against. The lesson must be dropped rather than admitted unchecked.
    """
    got = _reflect(
        {"lesson": "Margins [F2] held.", "what_held": [], "what_failed": []},
        doc=dossier(evidence=[]),
    )
    assert got["uncited"] is True


# ── The prior record as ledger evidence ───────────────────────────────────────

def resolved(ticker="EXMP", assessment="BULLISH", alpha=-0.05, lesson=None,
             correct=False, days=21):
    return {
        "ticker": ticker,
        "as_of": BASE.isoformat(),
        "outcome": {
            "assessment": assessment,
            "research_conviction": 72.0,
            "horizon_days": days,
            "return": 0.04,
            "benchmark_return": 0.09,
            "benchmark_ticker": "SPY",
            "alpha": alpha,
            "assessment_correct": correct,
            "reflection": {"lesson": lesson} if lesson else None,
        },
    }


def test_prior_readings_enter_the_ledger_under_the_o_prefix():
    ledger = Ledger()
    PR.add_prior_record(ledger, "EXMP", [resolved()])
    ids = ledger.ids()
    assert ids == {"O1"}
    assert ledger.by_prefix(("O",))[0].id == "O1"


def test_prior_readings_are_meta_and_do_not_count_as_evidence():
    """
    The guard at the top of `build_dossier` counts facts about the company. A
    name with a long track record and no financial statements must still fail
    it, or the fan-out would run four agents over nothing but its own history.
    """
    ledger = Ledger()
    PR.add_prior_record(ledger, "EXMP", [resolved() for _ in range(8)])
    assert len(ledger) == 8
    assert ledger.substantive_count() == 0
    assert ledger.substantive_count(("O",)) == 0


def test_the_rendered_item_names_the_alpha_and_the_verdict():
    ledger = Ledger()
    PR.add_prior_record(ledger, "EXMP", [resolved(alpha=-0.05, correct=False)])
    text = ledger.render(("O",))
    assert "-5.0%" in text
    assert "wrong on alpha" in text


def test_an_ungraded_prior_reading_does_not_read_as_a_miss():
    """NEUTRAL declined to take a side. An agent shown 'wrong' would be
    learning from a fact that is not one."""
    ledger = Ledger()
    PR.add_prior_record(
        ledger, "EXMP",
        [resolved(assessment="NEUTRAL", correct=None)],
    )
    text = ledger.render(("O",))
    assert "wrong" not in text
    assert "not graded" in text


def test_an_unmeasurable_prior_reading_says_so():
    ledger = Ledger()
    PR.add_prior_record(ledger, "EXMP", [resolved(alpha=None, correct=None)])
    text = ledger.render(("O",))
    assert "not gradeable" in text


def test_a_recorded_lesson_is_carried_forward():
    ledger = Ledger()
    PR.add_prior_record(
        ledger, "EXMP",
        [resolved(lesson="Margin durability [F2] was read from two periods.")],
    )
    assert "[F2]" in ledger.render(("O",))


def test_cross_ticker_entries_are_labelled_as_another_company():
    """
    A pattern in how a kind of business is read repeats across names, which is
    why these are carried. An agent must not mistake one for history of the
    name in front of it.
    """
    ledger = Ledger()
    added = PR.add_prior_record(
        ledger, "EXMP", [resolved(), resolved(ticker="OTHR")]
    )
    assert added == {"same_ticker": 1, "cross_ticker": 1, "available": True}
    text = ledger.render(("O",))
    assert "[different company]" in text
    assert text.index("EXMP") < text.index("[different company]")


def test_an_unsettled_reading_contributes_nothing():
    """
    A dossier with no outcome is a prediction, not a record. Feeding an agent
    its own unsettled opinion is a feedback loop with no ground truth in it.
    """
    ledger = Ledger()
    added = PR.add_prior_record(ledger, "EXMP", [{"ticker": "EXMP", "outcome": {}}])
    assert len(ledger) == 0
    assert added["available"] is False


def test_no_prior_record_is_a_clean_empty_state():
    ledger = Ledger()
    added = PR.add_prior_record(ledger, "EXMP", [])
    assert len(ledger) == 0
    assert added == {"same_ticker": 0, "cross_ticker": 0, "available": False}
