"""
Behavioural tests for the momentum / relative-strength factor.

This factor exists because the composite could not express "this is working".
Under `technical_stance=mean_reversion` trend enters `_technical_score` only as
a multiplier capped at 1.0, so momentum could never add a point: an extended
market leader scored 0.037 there against a falling knife's 0.391, and no other
rate-of-change or relative-strength term existed anywhere in the composite.

Two properties carry the module and both have already failed once in
development, which is why they are pinned here.

**Neutral means neutral.** A stock that merely tracks the index must score
exactly 0.5. The first draft left the range component as an absolute 52-week
position, and in a rising market almost everything sits near its high — so an
index-matching name scored 0.625 and the factor lifted the whole book without
ranking it. That is the `_macro_score` defect rebuilt in a new place.

**Absence is neutral, never weak.** Every component is benchmark-relative, so a
missing benchmark means the factor has nothing to say. It must return 0.5 at
zero coverage, not 0.0 — the `commission_paid` rule. A 0.0 would argue against
every name it could not measure.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.momentum import (  # noqa: E402
    _LONG_LOOKBACK,
    _RANGE_MIN_BARS,
    _SKIP_RECENT,
    compute_momentum,
)

_INDEX = pd.bdate_range("2025-09-01", periods=300)


def path(total_return: float, periods: int = 300) -> pd.Series:
    """A clean geometric path returning `total_return` over the window."""
    idx = _INDEX[-periods:]
    step = (1.0 + total_return) ** (1.0 / len(idx))
    return pd.Series(100 * np.cumprod(np.full(len(idx), step)), index=idx)


MARKET = path(0.18)


# ── Neutrality ────────────────────────────────────────────────────────────────

def test_a_stock_that_tracks_the_index_scores_exactly_neutral():
    """The regression that caught the absolute-range bug. 0.625 was the wrong answer."""
    score, coverage, _ = compute_momentum(path(0.18), MARKET)
    assert coverage == pytest.approx(1.0)
    assert score == pytest.approx(0.5, abs=1e-9)


def test_every_component_is_neutral_for_an_index_tracker():
    """Not just the blend — each leg individually, or the neutrality is a coincidence."""
    _, _, detail = compute_momentum(path(0.18), MARKET)
    for key in ("rs_3m", "rs_6m_skip_1m", "range_position"):
        assert detail[key] == pytest.approx(0.5, abs=1e-9), key


# ── Absence is neutral, never weak ────────────────────────────────────────────

def test_no_benchmark_yields_neutral_at_zero_coverage():
    for total_return in (0.90, -0.45):
        score, coverage, detail = compute_momentum(path(total_return), None)
        assert score == 0.5
        assert coverage == 0.0
        assert detail["benchmark_available"] is False


def test_a_collapsing_stock_without_a_benchmark_is_not_scored_weak():
    """The one direction of error that matters: unknown must not read as bearish."""
    score, _, _ = compute_momentum(path(-0.60), None)
    assert score == 0.5


def test_too_little_history_is_neutral_rather_than_zero():
    score, coverage, _ = compute_momentum(path(0.90, periods=40), MARKET)
    assert score == 0.5
    assert coverage == 0.0


# ── Ranking — the thing the engine could not previously do ────────────────────

def test_leaders_outrank_laggards():
    ordered = [0.90, 0.45, 0.18, 0.05, -0.15, -0.45]
    scores = [compute_momentum(path(r), MARKET)[0] for r in ordered]
    assert scores == sorted(scores, reverse=True), scores


def test_outperformance_scores_above_neutral_and_underperformance_below():
    assert compute_momentum(path(0.60), MARKET)[0] > 0.5
    assert compute_momentum(path(-0.10), MARKET)[0] < 0.5


def test_the_factor_separates_names_far_more_than_the_macro_factor_can():
    """Momentum must actually discriminate, which is macro's whole failing."""
    best = compute_momentum(path(0.90), MARKET)[0]
    worst = compute_momentum(path(-0.45), MARKET)[0]
    assert best - worst > 0.4


# ── Coverage weighting ────────────────────────────────────────────────────────

def test_partial_coverage_lands_nearer_neutral_than_full_coverage():
    """A shorter series drops the long leg; conviction must fall with evidence."""
    full, full_cov, _ = compute_momentum(path(0.90), MARKET)
    short_series = path(0.90).iloc[-_RANGE_MIN_BARS - 5 :]
    partial, partial_cov, detail = compute_momentum(short_series, MARKET)
    assert detail["rs_6m_skip_1m"] is None
    assert partial_cov < full_cov
    assert abs(partial - 0.5) < abs(full - 0.5)


# ── Construction details that are load-bearing ────────────────────────────────

def test_the_long_leg_skips_the_most_recent_month():
    """
    A run that rolled over in the last month must keep a strong 6-1 reading and
    a weak 3-month one. If the long leg included the recent weeks the two would
    move together and the skip would be doing nothing.
    """
    values = path(0.90).to_numpy().copy()
    values[-_SKIP_RECENT:] = values[-_SKIP_RECENT] * np.linspace(1.0, 0.85, _SKIP_RECENT)
    rolled = pd.Series(values, index=_INDEX)

    _, _, detail = compute_momentum(rolled, MARKET)
    assert detail["rs_6m_skip_1m"] > 0.65
    assert detail["rs_3m"] < 0.40


def test_a_timezone_aware_benchmark_still_aligns():
    """
    yfinance returns tz-aware stamps for some tickers and naive for others. An
    unaligned join produces an all-NaN reindex and a silently neutral factor
    rather than an error, so this is pinned.
    """
    aware = MARKET.copy()
    aware.index = MARKET.index.tz_localize("UTC")
    assert compute_momentum(path(0.90), aware)[0] == pytest.approx(
        compute_momentum(path(0.90), MARKET)[0]
    )


def test_raw_components_are_retained_beside_the_score():
    """
    The bands are tunable, so a replay that recomputed the score from later
    constants would describe a rule that never ran. Same reasoning as
    `setup_trigger` being stored alongside its five indicators.
    """
    _, _, detail = compute_momentum(path(0.90), MARKET)
    assert detail["excess_return_3m"] is not None
    assert detail["range_position_raw"] is not None
    assert detail["bars_available"] == 300


def test_the_score_never_leaves_the_unit_interval():
    for total_return in (-0.99, -0.5, 0.0, 2.0, 20.0):
        score, _, _ = compute_momentum(path(total_return), MARKET)
        assert 0.0 <= score <= 1.0


# ── Wiring: it ships inert ────────────────────────────────────────────────────
#
# The factor is computed and stored on every cycle so calibration can settle
# history under it, but it must move no score until somebody raises the weight
# deliberately. Same posture as `enable_rank_signals` and
# `RESEARCH_VETO_ENABLED`: this decides which names an agent with real money
# buys, and nothing has measured whether it ranks outcomes better yet.

from app.config import Settings  # noqa: E402
from app.services.scoring import (  # noqa: E402
    FACTORS,
    _weighted_score,
    effective_weights,
    explain_score,
)


def test_momentum_ships_at_zero_weight():
    assert Settings().weight_momentum == 0.0


def test_a_stored_momentum_score_moves_no_composite_at_the_default_weight():
    settings = Settings()
    base = {
        "technical_score": 0.4, "fundamental_score": 0.6, "sentiment_score": 0.5,
        "macro_score": 0.8, "volatility_score": 0.5, "catalyst_score": 0.55,
        "alternative_data_score": 0.5,
    }
    assert _weighted_score({**base, "momentum_score": 0.95}, settings) == pytest.approx(
        _weighted_score({**base, "momentum_score": 0.05}, settings)
    )


def test_raising_the_weight_requires_rebalancing_rather_than_inflating_the_score():
    """The sum-to-1.0 check must cover momentum, or its weight is free."""
    with pytest.raises(ValueError, match="sum to 1.0"):
        Settings(weight_momentum=0.15)

    rebalanced = Settings(weight_momentum=0.15, weight_macro=0.0)
    assert rebalanced.weight_momentum == 0.15


def test_momentum_is_surfaced_in_the_attribution_breakdown():
    """A factor the UI cannot see is a factor nobody can argue about."""
    assert "momentum" in {key for key, _, _ in FACTORS}
    assert "momentum" in effective_weights(None)

    breakdown = explain_score({"momentum_score": 0.82})
    row = next(f for f in breakdown["factors"] if f["key"] == "momentum")
    assert row["score"] == pytest.approx(0.82)
    assert row["label"] == "Momentum"


def test_a_feature_document_written_before_this_factor_scores_neutral():
    """Back-documents have no momentum_score; they must not read as weak."""
    settings = Settings(weight_momentum=0.15, weight_macro=0.0)
    legacy = {"technical_score": 0.4, "fundamental_score": 0.6, "sentiment_score": 0.5,
              "macro_score": 0.8, "volatility_score": 0.5, "catalyst_score": 0.55,
              "alternative_data_score": 0.5}
    assert _weighted_score(legacy, settings) == pytest.approx(
        _weighted_score({**legacy, "momentum_score": 0.5}, settings)
    )
