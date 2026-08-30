"""
Tests for the record of what a score was made of.

Every external source here degrades to a neutral 0.5 rather than failing the
cycle, which is the right trade. The cost, stated in `docs/10-due-diligence.md`
§6.6, is that a composite assembled from three fallbacks looked identical in the
API to one assembled from live data. These tests pin the distinction, and the
two rules that keep it honest: coverage is weight-independent, and a figure that
cannot be computed stays absent rather than defaulting to something flattering.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.services.input_quality import (  # noqa: E402
    FALLBACK, MEASURED, PARTIAL, build_inputs, completeness, fallback_factors,
)

WEIGHTS = {
    "technical": 0.30, "fundamental": 0.20, "sentiment": 0.20,
    "macro": 0.15, "volatility": 0.00, "catalyst": 0.15,
    "alternative_data": 0.10,
}


def raw(**overrides) -> dict:
    """A raw document in which every source answered."""
    base = {
        "sentiment_raw": {"source": "finnhub+vader+finlex", "coverage": 1.0},
        "macro": {"source": "fred", "vix": 17.2,
                  "yield_curve_spread": 0.4, "cpi_yoy_pct": 2.9},
        "fundamentals": {"source": "massive+alphavantage"},
        "alternative_data": {
            "options_flow": {"source": "yfinance"},
            "insider_trades": {"source": "yfinance"},
        },
    }
    base.update(overrides)
    return base


def built(**kwargs) -> dict:
    defaults = {"fundamental_coverage": 1.0, "catalyst_coverage": 1.0,
                "has_long_ma": True}
    defaults.update(kwargs)
    doc = defaults.pop("raw", None) or raw()
    return build_inputs(doc, **defaults)


# ── Coverage is a fact about the data ─────────────────────────────────────────

def test_a_complete_read_is_measured_across_the_board():
    inputs = built()
    assert {f["state"] for f in inputs["factors"].values()} == {MEASURED}
    assert completeness(inputs, WEIGHTS) == 1.0
    assert fallback_factors(inputs, WEIGHTS) == []


def test_a_missing_key_makes_its_factor_a_fallback_not_a_low_score():
    """
    The distinction the whole module exists for. A 0.5 sentiment sub-score can
    mean "measured, and genuinely balanced news" or "we never looked", and the
    factor breakdown alone cannot tell them apart.
    """
    inputs = built(raw=raw(sentiment_raw={"source": "no_api_key", "coverage": 0.0}))
    assert inputs["factors"]["sentiment"]["state"] == FALLBACK
    assert fallback_factors(inputs, WEIGHTS) == ["Sentiment"]


def test_measured_silence_is_not_a_fallback():
    """
    Finnhub answering "no news this week" is a measurement. Only "we never
    looked" is absence — the same line `catalyst.py` draws.
    """
    inputs = built(raw=raw(sentiment_raw={"source": "no_articles", "coverage": 0.0}))
    assert inputs["factors"]["sentiment"]["state"] == FALLBACK
    # …but it got there through a real coverage figure, not through the source
    # being unobserved. A thin real read and an absent one both land near
    # neutral; what differs is that this one is a fact about the company.
    inputs = built(raw=raw(sentiment_raw={"source": "no_articles", "coverage": 0.5}))
    assert inputs["factors"]["sentiment"]["state"] == PARTIAL


def test_a_live_fred_missing_one_series_is_partial_not_dead():
    inputs = built(raw=raw(macro={"source": "fred", "vix": 17.2,
                                  "yield_curve_spread": None, "cpi_yoy_pct": 2.9}))
    assert inputs["factors"]["macro"]["state"] == PARTIAL
    assert inputs["factors"]["macro"]["coverage"] == pytest.approx(2 / 3, abs=1e-3)


def test_thin_fundamentals_are_partial():
    """The CBRS shape: a young listing with no filings, so no P/E, FCF or D/E."""
    inputs = built(fundamental_coverage=0.55)
    assert inputs["factors"]["fundamental"]["state"] == PARTIAL
    assert completeness(inputs, WEIGHTS) < 1.0


def test_a_listing_too_young_for_a_50_day_average_is_partial():
    assert built(has_long_ma=False)["factors"]["technical"]["state"] == PARTIAL
    assert built(has_long_ma=True)["factors"]["technical"]["state"] == MEASURED


# ── Completeness is an opinion, weighted by the reader's own weights ──────────

def test_completeness_is_the_weighted_share_that_was_measured():
    inputs = built(raw=raw(
        sentiment_raw={"source": "no_api_key", "coverage": 0.0},
        macro={"source": "no_api_key"},
    ))
    # The five weighted factors sum to 1.00 (volatility is 0.00 and so is not
    # in the denominator at all). Sentiment 0.20 and macro 0.15 are gone, so
    # 0.65 of the composite came from measured data.
    assert completeness(inputs, WEIGHTS) == pytest.approx(0.65, abs=1e-4)


def test_a_factor_weighted_at_zero_is_not_part_of_the_denominator():
    """
    Volatility defaults to weight 0.00 — it is priced at the risk gate instead.
    Counting its coverage would report a completeness the composite never had.
    """
    without = completeness(built(), WEIGHTS)
    with_vol = completeness(built(), {**WEIGHTS, "volatility": 0.10})
    assert without == with_vol == 1.0

    thin = built(fundamental_coverage=0.0)
    assert completeness(thin, WEIGHTS) != completeness(
        thin, {**WEIGHTS, "volatility": 0.30, "fundamental": 0.05}
    )


def test_the_same_coverage_reads_differently_to_two_traders():
    """
    Coverage is a fact; completeness is a weighted opinion about it. A trader
    who weights macro at zero loses nothing when FRED is down.
    """
    inputs = built(raw=raw(macro={"source": "no_api_key"}))
    assert completeness(inputs, WEIGHTS) < 1.0
    assert completeness(inputs, {**WEIGHTS, "macro": 0.0}) == 1.0


def test_fallbacks_are_named_heaviest_first():
    inputs = built(
        fundamental_coverage=0.0,
        raw=raw(macro={"source": "error"}),
    )
    # fundamental 0.20 outranks macro 0.15.
    assert fallback_factors(inputs, WEIGHTS) == ["Fundamental", "Macro"]


# ── A figure that cannot be computed stays absent ─────────────────────────────

def test_a_signal_from_before_this_existed_has_no_completeness():
    """
    Never 1.0. Defaulting would claim every historical verdict was built on
    complete data — the same flattering guess `alpha` and `commission_paid`
    both refuse to make.
    """
    assert completeness(None, WEIGHTS) is None
    assert completeness({}, WEIGHTS) is None
    assert completeness({"factors": {}}, WEIGHTS) is None
    assert fallback_factors(None, WEIGHTS) == []


def test_no_weights_at_all_yields_no_figure_rather_than_zero():
    assert completeness(built(), {k: 0.0 for k in WEIGHTS}) is None
