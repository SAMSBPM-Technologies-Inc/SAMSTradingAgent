"""
Tests for retail sentiment and prediction-market evidence.

The engine reads news sentiment, which measures what *publishers* wrote. This
adds what holders are saying and what funded participants are pricing — two
different quantities, both noisy, neither allowed anywhere near the composite
score.

The properties under test are the ones that keep noisy data honest:

  * these items are EVIDENCE, never a judgement — no "retail is bullish" number
    is computed anywhere, so an agent must cite counts to make a claim;
  * a source that could not be read contributes ABSENCE, never a neutral
    reading, because a fabricated 0.5 is indistinguishable from a measurement;
  * every item is `meta` or count-shaped such that a name with no financials
    cannot become researchable on chatter alone;
  * nothing here touches the composite score's factors or weights — adding one
    would change every published signal and invalidate settled history.

Run with:  pytest backend/tests -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import prediction_markets as PM  # noqa: E402
from app.services import social as S  # noqa: E402
from app.services.research import prediction as PE  # noqa: E402
from app.services.research import social as SE  # noqa: E402
from app.services.research.evidence import Ledger  # noqa: E402


# ── Evidence, not judgement ───────────────────────────────────────────────────

def stocktwits(**over):
    base = {
        "source": "StockTwits", "window_days": 7, "messages": 240, "tagged": 60,
        "bullish": 48, "bearish": 12, "bull_share": 0.8, "as_of": "2026-08-28",
    }
    base.update(over)
    return base


def test_social_items_land_under_the_s_prefix():
    ledger = Ledger()
    SE.build(ledger, {"enabled": True, "stocktwits": stocktwits(), "reddit": None})
    assert all(i.id.startswith("S") for i in ledger.items)


def test_the_counts_are_recorded_not_a_sentiment_score():
    """
    A "retail sentiment: 0.72" item would launder brigading and bot traffic
    into a number an agent would reason from as a measurement. Counts force it
    to cite what it is actually claiming from.
    """
    ledger = Ledger()
    SE.build(ledger, {"enabled": True, "stocktwits": stocktwits(), "reddit": None})
    text = ledger.render(("S",))
    assert "240" in text and "48" in text and "12" in text
    for forbidden in ("sentiment score", "retail is bullish", "bullish overall"):
        assert forbidden not in text.lower()


def test_the_bull_share_is_labelled_as_a_self_reported_tag():
    ledger = Ledger()
    SE.build(ledger, {"enabled": True, "stocktwits": stocktwits(), "reddit": None})
    assert "not a survey" in ledger.render(("S",))


def test_no_directional_tags_is_an_absence_not_a_neutral_split():
    """
    A ratio computed from an empty denominator is not a neutral reading, it is
    no reading. 0.5 here would be a fabricated measurement.
    """
    ledger = Ledger()
    SE.build(ledger, {
        "enabled": True,
        "stocktwits": stocktwits(tagged=0, bullish=0, bearish=0, bull_share=None),
        "reddit": None,
    })
    text = ledger.render(("S",))
    assert "no message carried a direction tag" in text
    assert "50%" not in text


def test_an_unreachable_board_contributes_a_declared_absence():
    ledger = Ledger()
    summary = SE.build(ledger, {"enabled": True, "stocktwits": None, "reddit": None})
    assert summary["available"] is False
    assert "no data collected" in ledger.render(("S",))


def test_disabled_collection_adds_nothing_at_all():
    ledger = Ledger()
    summary = SE.build(ledger, {"enabled": False, "stocktwits": None, "reddit": None})
    assert len(ledger) == 0
    assert summary["available"] is False


def test_chatter_alone_cannot_make_a_name_researchable():
    """
    `substantive_count` decides whether a ticker is worth running agents over.
    A dead name with an active message board must not clear that guard.
    """
    ledger = Ledger()
    SE.build(ledger, {"enabled": True, "stocktwits": stocktwits(),
                      "reddit": {"source": "Reddit", "window_days": 7, "posts": 30,
                                 "total_score": 900, "total_comments": 400,
                                 "median_score": 30.0,
                                 "subreddits": {"stocks": 30},
                                 "as_of": "2026-08-28"}})
    # The counts are real facts about attention, so they are substantive — but
    # they are the news agent's slice, and the guard that matters is the
    # per-agent one. What must never happen is a *fundamentals* agent being
    # called on the strength of chatter.
    assert ledger.substantive_count(("F", "V", "E", "P")) == 0


# ── Prediction markets ────────────────────────────────────────────────────────

def market(**over):
    base = {"question": "Will the Fed hold rates in September?",
            "probability": 0.88, "volume": 2_400_000.0, "ends": "2026-09-17",
            "source": "Polymarket", "as_of": "2026-08-28"}
    base.update(over)
    return base


def test_market_items_land_under_the_k_prefix_and_are_meta():
    """
    They describe the environment, not the business. A name with no financials
    must not become researchable because the Fed has a liquid market this week.
    """
    ledger = Ledger()
    PE.build(ledger, [market()])
    assert all(i.id.startswith("K") for i in ledger.items)
    assert ledger.substantive_count() == 0


def test_the_item_carries_the_question_the_price_and_the_resolution_date():
    """An agent may cite the market; it may not assert the outcome."""
    ledger = Ledger()
    PE.build(ledger, [market()])
    text = ledger.render(("K",))
    assert "Will the Fed hold rates in September?" in text
    assert "88%" in text
    assert "2026-09-17" in text


def test_nothing_liquid_enough_is_said_out_loud():
    ledger = Ledger()
    summary = PE.build(ledger, [])
    assert summary["available"] is False
    assert "no market cleared the liquidity floor" in ledger.render(("K",))


def test_not_collected_adds_nothing():
    ledger = Ledger()
    summary = PE.build(ledger, None)
    assert len(ledger) == 0
    assert summary["reason"] == "not collected"


# ── Provider parsing ──────────────────────────────────────────────────────────

def test_the_yes_price_parses_from_both_shapes_polymarket_returns():
    assert PM._yes_probability({"outcomePrices": '["0.88", "0.12"]'}) == 0.88
    assert PM._yes_probability({"outcomePrices": [0.61, 0.39]}) == 0.61


def test_an_unparseable_price_is_none_rather_than_a_guess():
    """
    A mis-parsed probability would enter the ledger looking exactly like a real
    one — the same reason a fabricated citation is worse than none.
    """
    assert PM._yes_probability({"outcomePrices": "not json"}) is None
    assert PM._yes_probability({"outcomePrices": []}) is None
    assert PM._yes_probability({}) is None
    assert PM._yes_probability({"outcomePrices": [1.4]}) is None


def test_collection_is_off_by_default(monkeypatch):
    got = asyncio.run(S.fetch_social("EXMP"))
    assert got == {"stocktwits": None, "reddit": None, "enabled": False}
    assert asyncio.run(PM.fetch_macro_markets()) is None


def test_one_source_failing_does_not_cost_the_other(monkeypatch):
    monkeypatch.setattr(S.get_settings(), "social_sentiment_enabled", True,
                        raising=False)

    async def boom(_ticker):
        raise RuntimeError("board down")

    async def fine(_ticker):
        return {"source": "Reddit", "posts": 4}

    monkeypatch.setattr(S, "fetch_stocktwits", boom)
    monkeypatch.setattr(S, "fetch_reddit", fine)

    got = asyncio.run(S.fetch_social("EXMP"))
    assert got["stocktwits"] is None
    assert got["reddit"]["posts"] == 4


# ── The composite score is untouched ──────────────────────────────────────────

def test_no_social_source_reaches_the_scoring_path():
    """
    Adding a factor would change every published signal and invalidate the
    settled history that Phase 1's alpha work and the calibration arm read.
    This stays research evidence only.
    """
    import re

    root = Path(__file__).resolve().parents[1] / "app/services"
    for name in ("scoring.py", "feature_engineering.py", "signal_generator.py",
                 "pipeline.py"):
        text = (root / name).read_text()
        for token in (r"\bstocktwits\b", r"\breddit\b", r"\bpolymarket\b",
                      r"fetch_social", r"fetch_macro_markets"):
            assert not re.search(token, text, re.IGNORECASE), \
                f"{token} reached {name}"
