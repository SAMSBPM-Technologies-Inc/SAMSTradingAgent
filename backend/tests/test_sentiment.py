"""
Tests for headline sentiment.

Two defects are pinned here. VADER, trained on social media, scored four of ten
unambiguous financial headlines at exactly 0.000 — it has no lexicon for
"beats", "raises guidance", "buyback" or "halts production". And the result
ignored how many headlines it was built from, so one stray article could set
0.20 of a ticker's composite by itself.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.finance_lexicon import build_analyzer, phrase_adjustment  # noqa: E402
from app.services.news import _FULL_COVERAGE_ARTICLES, _headline_compound, _vader_sentiment  # noqa: E402


@pytest.fixture(scope="module")
def analyzer():
    return build_analyzer()


def tone(analyzer, headline):
    v = _headline_compound(analyzer, headline)
    return "bullish" if v > 0.05 else "bearish" if v < -0.05 else "neutral"


# The exact four VADER returned 0.000 for.
REGRESSION = [
    ("Apple beats Q3 earnings estimates, raises guidance", "bullish"),
    ("Microsoft announces $60 billion buyback program", "bullish"),
    ("Meta stock jumps 12% on ad revenue surge", "bullish"),
    ("Boeing halts 737 production amid FAA probe", "bearish"),
]


@pytest.mark.parametrize("headline,expected", REGRESSION)
def test_headlines_vader_scored_neutral_now_read_correctly(analyzer, headline, expected):
    assert tone(analyzer, headline) == expected


def test_guidance_direction_is_not_lost(analyzer):
    """
    The sharpest case for phrase matching: these differ by one verb and VADER
    scores tokens independently, so it cannot separate them.
    """
    up = _headline_compound(analyzer, "Acme raises guidance for full year")
    down = _headline_compound(analyzer, "Acme cuts guidance for full year")
    assert up > 0.05 and down < -0.05


def test_profit_warning_is_bearish_despite_containing_profit(analyzer):
    assert tone(analyzer, "Acme issues profit warning for second half") == "bearish"


def test_analyst_actions_are_directional(analyzer):
    assert tone(analyzer, "Analysts upgrade Acme to overweight") == "bullish"
    assert tone(analyzer, "Analysts downgrade Acme to underweight") == "bearish"


def test_dividend_cut_is_not_read_as_a_dividend(analyzer):
    """'dividend' alone is mildly positive; cutting one is not."""
    assert tone(analyzer, "Acme cuts dividend to preserve cash") == "bearish"


def test_compound_stays_in_vader_range(analyzer):
    """Phrase adjustments stack; the result must not escape [-1, 1]."""
    piled = ("Acme beats estimates, raises guidance, record revenue, "
             "share buyback, fda approval, takeover bid")
    assert -1.0 <= _headline_compound(analyzer, piled) <= 1.0
    grim = ("Acme misses estimates, cuts guidance, profit warning, "
            "sec investigation, dividend cut, bankruptcy")
    assert -1.0 <= _headline_compound(analyzer, grim) <= 1.0


def test_phrase_adjustment_counts_each_phrase_once():
    """A headline repeating a term is not twice the news."""
    once = phrase_adjustment("raises guidance")
    twice = phrase_adjustment("raises guidance and raises guidance again")
    assert once == twice


def test_neutral_headline_stays_neutral(analyzer):
    assert tone(analyzer, "Acme to present at industry conference in March") == "neutral"


# ── Coverage weighting ────────────────────────────────────────────────────────

def test_thin_coverage_is_pulled_toward_neutral():
    """One bullish headline must not produce the same score as six."""
    h = "Acme beats estimates, raises guidance"
    thin = _vader_sentiment("X", [h])["score"]
    thick = _vader_sentiment("X", [h] * _FULL_COVERAGE_ARTICLES)["score"]
    assert 0.5 < thin < thick


def test_full_coverage_is_untouched():
    """At or above the threshold the raw score passes through unchanged."""
    h = "Acme beats estimates, raises guidance"
    out = _vader_sentiment("X", [h] * _FULL_COVERAGE_ARTICLES)
    assert out["score"] == pytest.approx(out["raw_score"], abs=1e-4)


def test_coverage_never_exceeds_one():
    out = _vader_sentiment("X", ["Acme beats estimates"] * 50)
    assert out["coverage"] == 1.0


def test_bearish_thin_coverage_is_also_damped():
    """Damping must be symmetric — toward 0.5 from either side."""
    h = "Acme cuts guidance amid profit warning"
    thin = _vader_sentiment("X", [h])["score"]
    thick = _vader_sentiment("X", [h] * _FULL_COVERAGE_ARTICLES)["score"]
    assert thick < thin < 0.5


def test_score_stays_in_unit_interval():
    for headlines in (["Acme beats estimates, raises guidance, record revenue"],
                      ["Acme bankruptcy filing, delisting, sec investigation"] * 9,
                      ["Acme to present at conference"] * 3):
        assert 0.0 <= _vader_sentiment("X", headlines)["score"] <= 1.0
