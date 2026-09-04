"""
The exit reading — `scoring.exit_score` and `scoring.exit_condition`.

The incident
────────────
AAPL published a SELL while it was ripping. `bb_pct` 1.03, `stoch_rsi` 0.99, up
24% in six months, sitting at 0.87 of its 52-week range — and a technical score
of **0.066**, because under `technical_stance=mean_reversion` an oversold
oscillator reading *is* the entry timer and an extended name floors it by
design. That score is 0.30 of a composite whose low end publishes SELL, and SELL
is the one verdict with no brakes: no risk gate, no confirmations, no dwell, no
research veto, and unappealable by the analyst (`sell_restored`).

So the composite was answering "is there a dip to buy here" and the exit was
reading the answer as "this is bad to own". Measured on the real functions it
had the two cases backwards — an extended leader scored 0.297 and a name with a
broken trend, negative relative strength and weak fundamentals scored 0.340.

The fix changes which number the SELL test reads, upstream of the verdict. It
adds no veto, no delay and no gate: a deteriorating name still sells
immediately. Momentum decides exits; technical decides entries.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.scoring import (  # noqa: E402
    exit_condition,
    exit_score,
    _weighted_score,
    effective_weights,
    _WeightView,
)
from app.services.signal_generator import (  # noqa: E402
    SELL_THRESHOLD,
    classify_signal,
)


def composite(feat):
    return _weighted_score(feat, _WeightView(effective_weights(None)))


#: A market leader that has run. The oscillators are pegged — correctly, there
#: is no dip here — but the trend is intact and relative strength is strong.
LEADER = dict(
    scoring_method="weighted",
    technical_score=0.066, fundamental_score=0.45, sentiment_score=0.30,
    macro_score=0.45, catalyst_score=0.40, alternative_data_score=0.5,
    momentum_score=0.88, momentum_coverage=1.0,
    macd_bullish=True, ma_cross_bullish=True,
)

#: A name genuinely coming apart: both trend legs broken, relative strength in
#: the gutter, and weak on everything the oscillators do not measure.
FALLING = dict(
    scoring_method="weighted",
    technical_score=0.391, fundamental_score=0.30, sentiment_score=0.25,
    macro_score=0.40, catalyst_score=0.35, alternative_data_score=0.5,
    momentum_score=0.15, momentum_coverage=1.0,
    macd_bullish=False, ma_cross_bullish=False,
)


# ── The inversion this exists to fix ──────────────────────────────────────────

def test_the_composite_had_the_two_cases_backwards():
    """
    Not an argument about thresholds — the ordering itself was wrong. The
    leader scored *below* the name that was falling apart, so the composite
    sold the wrong one of the pair whatever the threshold had been set to.
    """
    assert composite(LEADER) < composite(FALLING)
    assert exit_score(LEADER) > exit_score(FALLING)


def test_an_extended_leader_is_no_longer_sold_for_being_extended():
    assert composite(LEADER) < SELL_THRESHOLD          # today's rule sells it
    assert exit_score(LEADER) > SELL_THRESHOLD         # the exit reading does not
    assert classify_signal(
        composite(LEADER), risk_score=3.0, exit_score=exit_score(LEADER),
    ) == "HOLD"


def test_a_deteriorating_name_still_sells():
    """
    The whole point of the change is that it is not a brake. A name with a
    broken trend and no relative strength sells on the exit reading even though
    the composite — propped up by an oversold oscillator — would have held it.
    """
    assert composite(FALLING) > SELL_THRESHOLD         # today's rule holds it
    assert exit_score(FALLING) < SELL_THRESHOLD        # the exit reading sells
    assert classify_signal(
        composite(FALLING), risk_score=3.0, exit_score=exit_score(FALLING),
    ) == "SELL"


def test_the_exit_reading_never_touches_the_buy_side():
    """
    A strong exit reading must not manufacture an entry. The BUY test reads the
    composite and only the composite.
    """
    assert classify_signal(0.50, risk_score=1.0, exit_score=0.99) == "HOLD"
    assert classify_signal(0.72, risk_score=1.0, exit_score=0.01) == "SELL"


# ── Refusals ──────────────────────────────────────────────────────────────────

def test_an_unknown_condition_reads_neutral_and_never_the_oscillators():
    """
    SELL has no brakes, so the safe reading of an unknown condition is *do not
    manufacture an exit*. Falling back to `technical_score` would reinstate the
    defect on exactly the documents carrying the least evidence — the same
    instinct as `classify_trigger` giving NEUTRAL when the trend is unknown.
    """
    bare = {k: v for k, v in LEADER.items()
            if k not in ("macd_bullish", "ma_cross_bullish",
                         "momentum_score", "momentum_coverage")}
    assert exit_condition(bare) == (0.5, 0.0)
    assert exit_condition(bare)[0] != bare["technical_score"]


def test_a_momentum_score_with_no_coverage_is_not_evidence():
    """
    `compute_momentum` returns a flat 0.5 at zero coverage when the benchmark is
    missing. Counting that as a reading would let an absent benchmark vote.
    """
    no_bench = dict(LEADER, momentum_score=0.5, momentum_coverage=0.0)
    score, coverage = exit_condition(no_bench)
    assert coverage < 1.0
    assert score == pytest.approx(1.0)          # trend alone, both legs bullish


def test_the_xgboost_path_refuses_to_derive_a_reading():
    """
    The weights did not produce that score, so an exit reading built from them
    is a different number wearing the same name — the refusal `explain_score`
    makes when it sets `attributable: false`. `classify_signal` then falls back
    to the composite, which is the rule exactly as it was.
    """
    assert exit_score(dict(LEADER, scoring_method="xgboost")) is None


def test_omitting_it_gives_the_raw_rule():
    """The convention `cohort` and `previous_signal` already follow — a
    calibration replay has no exit reading and must get the unmodified rule."""
    assert classify_signal(0.18, risk_score=3.0) == "SELL"
    assert classify_signal(0.18, risk_score=3.0, exit_score=None) == "SELL"


# ── It is not a brake ─────────────────────────────────────────────────────────

def test_the_exit_is_still_ungated_by_risk():
    """A dangerous name is not thereby un-sellable; risk gates BUY alone."""
    assert classify_signal(
        0.50, risk_score=9.9, exit_score=0.10,
    ) == "SELL"


def test_the_sell_band_still_applies_to_the_exit_reading():
    """
    The one-sided hysteresis band holds a standing verdict in place. It has to
    read the same number the verdict was made on, or a standing SELL is judged
    against a threshold nothing measured it with.
    """
    just_over = SELL_THRESHOLD + 0.02
    assert classify_signal(0.50, 3.0, None, None, exit_score=just_over) == "HOLD"
    assert classify_signal(0.50, 3.0, "SELL", None, exit_score=just_over) == "SELL"
