"""
Behavioural tests for `_macro_score` and `_macro_sensitivity`.

VIX, the yield curve and CPI describe the market, not a stock. Carried at a flat
0.15 weight the reading was identical for every ticker, so it could not rank two
names against each other — it only raised or lowered the whole book, which made
the BUY count track the regime instead of the names.

The property under test is therefore DISCRIMINATION: within one macro regime,
tickers with different exposure must receive different scores, and in the
financially correct order.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.feature_engineering as fe  # noqa: E402

STRESS = {"vix": 30, "yield_curve_spread": -0.2, "cpi_yoy_pct": 4.5, "source": "fred"}
BENIGN = {"vix": 14, "yield_curve_spread": 0.8, "cpi_yoy_pct": 2.3, "source": "fred"}

# (sector, realised volatility) — a high-beta growth name vs a staple.
GROWTH = ("Technology", 0.52)
STAPLE = ("Consumer Defensive", 0.14)


def test_macro_discriminates_between_tickers_in_one_regime():
    """The whole point of the change: identical inputs must stop producing identical output."""
    assert fe._macro_score(STRESS, *GROWTH) != fe._macro_score(STRESS, *STAPLE)


def test_defensives_hold_up_better_under_macro_stress():
    assert fe._macro_score(STRESS, *STAPLE) > fe._macro_score(STRESS, *GROWTH)


def test_high_beta_benefits_more_from_a_benign_regime():
    assert fe._macro_score(BENIGN, *GROWTH) >= fe._macro_score(BENIGN, *STAPLE)


def test_sensitivity_of_one_reproduces_the_old_market_wide_value():
    """
    Unknown sector at the volatility pivot must be a no-op, so tickers without
    sector coverage behave exactly as they did before.
    """
    for regime in (STRESS, BENIGN):
        assert fe._macro_score(regime, None, 0.30) == pytest.approx(fe._macro_score(regime))


def test_unknown_sector_falls_back_to_volatility_only():
    """No sector data is not a reason to ignore exposure entirely."""
    quiet = fe._macro_score(STRESS, None, 0.10)
    wild = fe._macro_score(STRESS, None, 0.90)
    assert quiet > wild, "a quiet name should be damped less by a stressed macro"


def test_sector_matching_is_case_and_spelling_insensitive():
    """Providers disagree: 'Consumer Cyclical' (yfinance) vs 'Consumer Discretionary'."""
    a = fe._macro_sensitivity("Consumer Cyclical", 0.30)
    b = fe._macro_sensitivity("consumer discretionary", 0.30)
    assert a == pytest.approx(b)
    assert fe._macro_sensitivity("TECHNOLOGY", 0.30) == pytest.approx(
        fe._macro_sensitivity("Technology", 0.30)
    )


def test_volatility_is_a_secondary_adjustment_not_the_driver():
    """
    A quiet month must not turn a cyclical into a defensive. The vol factor is
    capped at ±30%, so sector ordering survives an extreme volatility gap.
    """
    cyclical_quiet = fe._macro_sensitivity("Technology", 0.05)
    staple_wild = fe._macro_sensitivity("Consumer Defensive", 2.0)
    assert cyclical_quiet > staple_wild


def test_missing_macro_data_is_still_neutral():
    assert fe._macro_score({}, "Technology", 0.5) == 0.5
    assert fe._macro_score({"source": "no_api_key"}, "Technology", 0.5) == 0.5


def test_missing_volatility_does_not_crash_or_skew():
    assert fe._macro_score(STRESS, "Technology", None) == pytest.approx(
        fe._macro_score(STRESS, "Technology", 0.30)
    )


def test_score_stays_in_unit_interval():
    sectors = list(fe._SECTOR_MACRO_BETA) + [None, "Nonsense Sector"]
    for regime in (STRESS, BENIGN):
        for sector in sectors:
            for vol in (0.0, 0.05, 0.30, 0.80, 2.0, None):
                s = fe._macro_score(regime, sector, vol)
                assert 0.0 <= s <= 1.0, f"{sector} {vol} -> {s}"


def test_sensitivity_is_bounded():
    for sector in list(fe._SECTOR_MACRO_BETA) + [None]:
        for vol in (0.0, 0.05, 0.30, 0.80, 5.0, None):
            assert 0.0 <= fe._macro_sensitivity(sector, vol) <= 1.5
