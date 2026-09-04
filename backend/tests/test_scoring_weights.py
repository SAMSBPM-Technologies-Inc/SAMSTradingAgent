"""
Tests for the composite weighting, and specifically for volatility being priced
ONCE.

Volatility used to be charged twice: 0.10 of the composite (quieter scored
higher) and up to 7 of the 10 risk points, where risk_score >= 6 vetoes a BUY.
The gate is the right home for it — it answers "is this too dangerous to hold" —
while the composite answers "is this the better opportunity", and a stock is not
a better opportunity for being quiet.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, get_settings  # noqa: E402
from app.services.risk_engine import assess_risk  # noqa: E402
from app.services.scoring import _weighted_score, compute_personalized_score  # noqa: E402


def feat(volatility_score, **over):
    base = {
        "technical_score": 0.85, "fundamental_score": 0.80, "sentiment_score": 0.70,
        "macro_score": 0.75, "volatility_score": volatility_score,
        "catalyst_score": 0.70, "alternative_data_score": 0.60,
    }
    base.update(over)
    return base


# ── The core property ─────────────────────────────────────────────────────────

def test_composite_is_independent_of_volatility_score():
    """Two identical businesses at different volatility must rank identically."""
    s = get_settings()
    quiet = _weighted_score(feat(1.0), s)
    wild = _weighted_score(feat(0.0), s)
    assert quiet == pytest.approx(wild), "volatility is still leaking into the alpha score"


def test_volatility_still_drives_the_risk_gate():
    """Removing it from the score must not remove it from the gate."""
    calm = assess_risk({"volatility_20d": 0.20, "rsi_14": 45, "composite_score": 0.8})
    wild = assess_risk({"volatility_20d": 1.40, "rsi_14": 45, "composite_score": 0.8})
    assert wild["risk_score"] > calm["risk_score"]


def test_extreme_volatility_can_still_veto_a_buy_alone():
    """
    With the composite drag gone, the gate is the ONLY volatility control left.
    If this ever stops holding, nothing restrains position risk.
    """
    r = assess_risk({"volatility_20d": 1.50, "rsi_14": 45, "composite_score": 0.85,
                     "ma_cross_bullish": True})
    assert r["risk_score"] >= 6.0, "volatility alone can no longer block a BUY"


# ── Weight configuration ──────────────────────────────────────────────────────

def test_default_weights_sum_to_one():
    s = get_settings()
    total = (s.weight_technical + s.weight_fundamental + s.weight_sentiment
             + s.weight_macro + s.weight_volatility + s.weight_catalyst)
    assert total == pytest.approx(1.0)


def test_volatility_weight_defaults_to_zero():
    assert get_settings().weight_volatility == 0.0


def test_weights_that_do_not_sum_to_one_are_rejected():
    """The validator is the only thing stopping a silently rescaled composite."""
    with pytest.raises(ValueError, match="sum to 1.0"):
        Settings(weight_technical=0.9, weight_fundamental=0.9)


# ── Per-user weights ──────────────────────────────────────────────────────────

def test_personalized_score_defaults_match_settings_defaults():
    """
    compute_personalized_score keeps its own fallback table. If it drifts from
    config.py, a user with a partial weight dict gets a different model than the
    stored signal — the two silently disagree.
    """
    s = get_settings()
    partial_user = {"technical": s.weight_technical}      # every other key absent
    score, _ = compute_personalized_score(feat(0.5), partial_user)
    assert score == pytest.approx(_weighted_score(feat(0.5), s), abs=1e-4)


def test_user_may_knowingly_reinstate_a_volatility_weight():
    """Explicit user choice must still be honoured, double-count and all."""
    weights = {"technical": 0.25, "fundamental": 0.15, "sentiment": 0.20,
               "macro": 0.15, "volatility": 0.10, "catalyst": 0.15}
    quiet, _ = compute_personalized_score(feat(1.0), weights)
    wild, _ = compute_personalized_score(feat(0.0), weights)
    assert quiet > wild


def test_personalized_signal_thresholds_match_the_generator():
    """BUY > 0.70 and risk < 6; SELL < 0.30. Kept in sync with signal_generator."""
    hot = feat(0.5, technical_score=1.0, fundamental_score=1.0, sentiment_score=1.0,
               macro_score=1.0, catalyst_score=1.0, alternative_data_score=1.0)
    hot["risk"] = {"score": 1.0}
    _, sig = compute_personalized_score(hot, None)
    assert sig == "BUY"

    cold = feat(0.5, technical_score=0.0, fundamental_score=0.0, sentiment_score=0.0,
                macro_score=0.0, catalyst_score=0.0, alternative_data_score=0.0)
    _, sig = compute_personalized_score(cold, None)
    assert sig == "SELL"


# ── A measured zero is not a missing value ────────────────────────────────────
#
# `explain_score` read every sub-score as `float(feat.get(key, 0.5) or 0.5)`,
# and in Python `0.0 or 0.5` is `0.5`. The engine itself (`_weighted_score`) has
# no `or`, so the two disagreed by up to 0.20 — exactly on the names where it
# matters, since under `mean_reversion` an extended leader floors
# `technical_score` at exactly 0.0 by design.
#
# The breakdown panel exists so the engine and the UI cannot drift. These pin
# that they cannot.

def _zero_technical():
    return {
        "technical_score": 0.0, "fundamental_score": 0.60,
        "sentiment_score": 0.50, "macro_score": 0.50, "volatility_score": 0.50,
        "catalyst_score": 0.50, "momentum_score": 0.50,
        "alternative_data_score": 0.50,
    }


def test_explain_score_matches_the_engine_on_a_zero_sub_score():
    from app.services.scoring import (
        _WeightView, _weighted_score, effective_weights, explain_score,
    )
    feat = _zero_technical()
    engine = _weighted_score(feat, _WeightView(effective_weights(None)))
    assert explain_score(feat)["composite"] == pytest.approx(engine, abs=1e-9)


def test_a_zero_sub_score_is_reported_as_zero_not_neutral():
    from app.services.scoring import explain_score
    technical = next(
        f for f in explain_score(_zero_technical())["factors"]
        if f["key"] == "technical"
    )
    assert technical["score"] == 0.0
    assert technical["contribution"] == 0.0


def test_a_zero_alternative_score_still_drags():
    """The additive modifier is centred on 0.5, so 0.0 must subtract."""
    from app.services.scoring import explain_score
    feat = _zero_technical() | {"alternative_data_score": 0.0}
    assert explain_score(feat)["alternative_data"]["contribution"] < 0


def test_a_missing_sub_score_still_reads_neutral():
    """The `or` was wrong; the default was not. An absent factor is 0.5."""
    from app.services.scoring import explain_score
    feat = _zero_technical()
    del feat["fundamental_score"]
    fundamental = next(
        f for f in explain_score(feat)["factors"] if f["key"] == "fundamental"
    )
    assert fundamental["score"] == 0.5
