"""
Tests for the catalyst score.

It used to be volume anomaly alone. On typical volume — 0.8x to 1.5x, which is
most days — the entire component moved the composite between -0.003 and +0.019
while carrying 0.15 of the weight. The property under test is that it now has
usable RANGE and that each component actually contributes.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.catalyst import compute_catalyst_score  # noqa: E402


def score(volume=None, articles=None, target=None, price=None):
    raw = {
        "sentiment_raw": {} if articles is None else {"article_count": articles},
        "fundamentals": {} if target is None else {"analyst_target_price": target},
    }
    return compute_catalyst_score(raw, {"volume_anomaly": volume, "current_price": price})


# ── Range ─────────────────────────────────────────────────────────────────────

def test_a_real_catalyst_scores_far_above_a_quiet_tape():
    """The whole point: the score must be able to say something."""
    live = score(volume=3.2, articles=14, target=135, price=100)
    quiet = score(volume=0.6, articles=0, target=88, price=100)
    assert live - quiet > 0.5


def test_ordinary_day_sits_near_neutral():
    assert 0.45 <= score(volume=1.0, articles=3, target=108, price=100) <= 0.60


def test_average_volume_is_neutral_not_zero():
    """
    The original curve returned 0.0 at or below 1x, making an ordinary day score
    maximally bearish — worse than having no data at all.
    """
    assert score(volume=1.0) > 0.4


# ── Each component pulls its weight ───────────────────────────────────────────

def test_volume_spike_raises_the_score():
    assert score(volume=3.0, articles=3, target=108, price=100) > \
           score(volume=1.0, articles=3, target=108, price=100)


def test_news_burst_raises_the_score():
    assert score(volume=1.0, articles=15, target=108, price=100) > \
           score(volume=1.0, articles=1, target=108, price=100)


def test_analyst_upside_raises_the_score():
    assert score(volume=1.0, articles=3, target=140, price=100) > \
           score(volume=1.0, articles=3, target=95, price=100)


def test_news_flow_is_direction_agnostic():
    """
    Attention is not tone. Direction is sentiment's job; this component must not
    depend on whether the news was good, only that there was a lot of it.
    """
    assert score(articles=15) > score(articles=1)


# ── Coverage weighting ────────────────────────────────────────────────────────

def test_partial_data_lands_nearer_neutral_than_complete_data():
    one = score(volume=3.2)
    three = score(volume=3.2, articles=14, target=135, price=100)
    assert 0.5 < one < three


def test_no_data_at_all_is_neutral():
    assert score() == 0.5


def test_missing_price_disables_upside_without_crashing():
    assert score(volume=1.5, articles=5, target=130) == pytest.approx(
        score(volume=1.5, articles=5)
    )


# ── Robustness ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target,price", [(0, 100), (100, 0), (-5, 100), ("x", 100), (None, 100)])
def test_degenerate_target_or_price_is_ignored(target, price):
    s = score(volume=1.2, articles=4, target=target, price=price)
    assert 0.0 <= s <= 1.0


def test_score_stays_in_unit_interval():
    for v in (None, 0.0, 0.5, 1.0, 3.0, 50.0):
        for a in (None, 0, 3, 12, 500):
            for t, p in ((None, None), (200, 100), (10, 100), (100, 100)):
                assert 0.0 <= score(v, a, t, p) <= 1.0


def test_insider_and_options_are_not_double_counted_here():
    """
    alternative_data_score already prices both. Importing them into catalyst
    would recreate the double-count just removed from volatility, so catalyst
    must ignore them even when present.
    """
    raw = {
        "sentiment_raw": {"article_count": 3},
        "fundamentals": {"analyst_target_price": 108},
        "alternative_data": {
            "insider_trades": {"buy_count_90d": 99, "sell_count_90d": 0},
            "options_flow": {"put_call_ratio": 0.1},
        },
    }
    with_alt = compute_catalyst_score(raw, {"volume_anomaly": 1.0, "current_price": 100})
    without = score(volume=1.0, articles=3, target=108, price=100)
    assert with_alt == pytest.approx(without)
