"""
Tests for relative scoring — `services/cross_section.py` and the rank rule in
`signal_generator`.

The case these exist for: the composite is a convex combination of six
sub-scores that three separate mechanisms push back toward 0.5 (coverage
weighting, a market-wide macro factor, a zeroed volatility weight). A near-best
realistic name works out at 0.747 against a 0.70 BUY threshold and a typical one
at 0.567, which is why 592 of 602 recorded signals were HOLD. An absolute cutoff
on a distribution that narrow mostly selects for how much data happened to be
available.

The relative rule is the fix, and it has two failure modes worth fencing
against permanently. A rank on its own **always fires** — somebody is always
top of the list — so it must never be able to buy the least-bad name in a bad
field. And a rank applied to exits would **hold a falling position** whenever
its peers were falling faster, which would make ranking the first thing in this
system ever to brake an exit.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.cross_section import Cohort, percentile_rank  # noqa: E402
from app.services.risk_engine import RISK_MAX_FOR_BUY  # noqa: E402
from app.services.signal_generator import (  # noqa: E402
    BUY_THRESHOLD, RANK_BUY_FLOOR, RANK_BUY_PERCENTILE, RANK_HYSTERESIS,
    RANK_MIN_COHORT, RANK_SELL_CEILING, RANK_SELL_PERCENTILE, SELL_THRESHOLD,
    classify_signal,
)

SAFE = 1.0            # a risk score that never blocks a BUY
BIG = RANK_MIN_COHORT + 5


def top(size=BIG):
    """A cohort standing comfortably inside the buy rank."""
    return Cohort(percentile=1.0, size=size)


def bottom(size=BIG):
    return Cohort(percentile=0.0, size=size)


def mid(size=BIG):
    return Cohort(percentile=0.5, size=size)


# ── The percentile itself ─────────────────────────────────────────────────────

def test_percentile_is_the_share_of_the_field_beaten():
    field = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert percentile_rank(0.5, field) == 1.0
    assert percentile_rank(0.1, field) == 0.0
    assert percentile_rank(0.3, field) == 0.5


def test_ties_rank_pessimistically_so_a_flat_field_buys_nothing():
    """
    Three identical scores each rank 0.0, not 0.5.

    A field where nothing is distinguishable should produce no BUY at all, and
    given how compressed this score is, "these all look the same" is a reading
    that happens often enough to matter. Counting ties as beaten would put every
    member of a flat field in the top quintile simultaneously.
    """
    flat = [0.6, 0.6, 0.6]
    assert percentile_rank(0.6, flat) == 0.0
    assert classify_signal(0.6, SAFE, None, Cohort(percentile=0.0, size=3)) != "BUY"


def test_a_field_too_small_to_rank_returns_none_rather_than_a_number():
    assert percentile_rank(0.6, [0.6]) is None
    assert percentile_rank(0.6, []) is None


# ── The relative rule ─────────────────────────────────────────────────────────

def test_top_of_the_field_above_the_floor_is_a_buy():
    assert classify_signal(RANK_BUY_FLOOR + 0.01, SAFE, None, top()) == "BUY"


def test_the_floor_refuses_the_best_of_a_bad_field():
    """
    The single most important property here.

    A rank always fires — there is always a top quintile — so without an
    absolute floor the agent buys the least-bad name every day regardless of
    whether anything is worth owning. The floor is what can say "nothing here".
    """
    assert classify_signal(RANK_BUY_FLOOR - 0.01, SAFE, None, top()) == "HOLD"


def test_the_risk_veto_still_outranks_a_perfect_rank():
    assert classify_signal(
        RANK_BUY_FLOOR + 0.1, RISK_MAX_FOR_BUY, None, top()
    ) == "HOLD"


def test_bottom_of_the_field_under_the_ceiling_is_a_sell():
    assert classify_signal(RANK_SELL_CEILING - 0.01, SAFE, None, bottom()) == "SELL"


def test_the_ceiling_refuses_to_sell_the_worst_of_a_strong_field():
    assert classify_signal(RANK_SELL_CEILING + 0.01, SAFE, None, bottom()) == "HOLD"


def test_mid_field_is_a_hold_however_good_the_absolute_score():
    """
    Ranking replaces the BUY test. A name clearing the absolute threshold but
    sitting mid-field no longer buys — that reshaping is the entire point.
    """
    assert classify_signal(BUY_THRESHOLD + 0.1, SAFE, None, mid()) == "HOLD"


# ── The exit is never braked ──────────────────────────────────────────────────

def test_the_absolute_exit_survives_a_field_that_is_falling_faster():
    """
    A name under SELL_THRESHOLD sells even when its peers are worse.

    Applied symmetrically, ranking would hold a position at 0.20 because four
    other names were at 0.10 — turning "everything I watch is collapsing" into
    a reason to sell nothing. Ranking may *add* exits. It may never remove one,
    which is the same rule that exempts SELL from the risk gate, from dwell and
    confirmations, and from both vetoes.
    """
    falling_slower_than_peers = Cohort(percentile=1.0, size=BIG)
    assert classify_signal(
        SELL_THRESHOLD - 0.01, SAFE, None, falling_slower_than_peers
    ) == "SELL"


def test_ranking_only_ever_adds_exits():
    """Every score the absolute rule sells, the relative rule also sells."""
    for score in (0.05, 0.15, 0.25, SELL_THRESHOLD - 0.001):
        for cohort in (top(), mid(), bottom()):
            assert classify_signal(score, SAFE, None) == "SELL"
            assert classify_signal(score, SAFE, None, cohort) == "SELL"


# ── Stickiness ────────────────────────────────────────────────────────────────

def test_a_standing_buy_holds_through_a_rank_wobble():
    slipped = Cohort(percentile=RANK_BUY_PERCENTILE - RANK_HYSTERESIS / 2, size=BIG)
    score = RANK_BUY_FLOOR + 0.05
    assert classify_signal(score, SAFE, "BUY", slipped) == "BUY"
    assert classify_signal(score, SAFE, "HOLD", slipped) == "HOLD"


def test_the_rank_band_is_one_sided():
    """It makes a standing verdict sticky; it never makes one easier to open."""
    just_short = Cohort(percentile=RANK_BUY_PERCENTILE - 0.01, size=BIG)
    assert classify_signal(RANK_BUY_FLOOR + 0.05, SAFE, None, just_short) == "HOLD"


def test_the_floor_is_not_banded_for_a_standing_buy():
    """
    The rank band forgives movement in the *field*; the floor describes the
    *name*. A position whose own score has fallen through the level at which it
    stopped being worth owning is dropped however well it still ranks.
    """
    assert classify_signal(RANK_BUY_FLOOR - 0.01, SAFE, "BUY", top()) == "HOLD"


# ── Falling back ──────────────────────────────────────────────────────────────

def test_no_cohort_is_the_absolute_rule_exactly():
    """
    The invariant calibration replays depend on: omitting the cohort gives the
    raw rule, unchanged, at every score.
    """
    for score in (0.0, 0.1, 0.29, 0.3, 0.5, 0.69, 0.7, 0.71, 0.9, 1.0):
        assert classify_signal(score, SAFE, None, None) == classify_signal(score, SAFE)


def test_a_thin_cohort_falls_back_rather_than_ranking_on_noise():
    """
    Under RANK_MIN_COHORT a percentile is mostly a statement about which peers
    happened to ingest. Falling back lands on the absolute rule, which is the
    stricter of the two — the safe direction for an uncertain path.
    """
    thin = Cohort(percentile=1.0, size=RANK_MIN_COHORT - 1)
    assert classify_signal(RANK_BUY_FLOOR + 0.01, SAFE, None, thin) == "HOLD"
    assert classify_signal(BUY_THRESHOLD + 0.01, SAFE, None, thin) == "BUY"
