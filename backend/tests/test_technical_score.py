"""
Behavioural tests for `_technical_score`.

The property under test is not a number, it is an ORDERING: a pullback inside
an intact uptrend must outrank a stock in free fall, even though both read
oversold on RSI, Bollinger and Stochastic. The additive blend could not express
that distinction — it scored the two 0.045 apart — so the ordering is the thing
worth pinning down. Absolute levels are deliberately asserted loosely.

Run with:  pytest backend/tests -q
(pytest is not a runtime dependency; install it separately.)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.feature_engineering as fe  # noqa: E402


@pytest.fixture
def stance(monkeypatch):
    """Pin the technical stance without touching the real settings cache."""
    def _set(name: str):
        monkeypatch.setattr(fe, "get_settings", lambda: type("S", (), {"technical_stance": name})())
    return _set


def tech(rsi=None, bb=None, stoch=None, macd=None, ma=None):
    return {
        "rsi_14": rsi, "bb_pct": bb, "stoch_rsi": stoch,
        "macd_bullish": macd, "ma_cross_bullish": ma,
    }


# Oversold on every oscillator. The only difference is whether the trend holds.
KNIFE    = tech(rsi=22, bb=0.05, stoch=0.05, macd=False, ma=False)
PULLBACK = tech(rsi=35, bb=0.20, stoch=0.15, macd=True,  ma=True)
DRIFT    = tech(rsi=50, bb=0.50, stoch=0.50, macd=True,  ma=True)
BLOWOFF  = tech(rsi=78, bb=0.97, stoch=0.97, macd=True,  ma=True)


def test_pullback_outranks_falling_knife(stance):
    """The distinction the additive blend could not make."""
    stance("mean_reversion")
    assert fe._technical_score(PULLBACK, 100.0) > fe._technical_score(KNIFE, 100.0)


def test_separation_is_wide_enough_to_act_on(stance):
    """
    Additive scored these 0.155 apart, inside the noise. Anything under ~0.25
    means the engine is again indifferent between a dip and a collapse.
    """
    stance("mean_reversion")
    gap = fe._technical_score(PULLBACK, 100.0) - fe._technical_score(KNIFE, 100.0)
    assert gap > 0.25, f"pullback/knife separation collapsed to {gap:.3f}"


def test_falling_knife_scores_below_neutral_drift(stance):
    """Oversold against a broken trend is not a buy signal at all."""
    stance("mean_reversion")
    assert fe._technical_score(KNIFE, 100.0) < fe._technical_score(DRIFT, 100.0)


def test_blowoff_top_is_the_worst_reading(stance):
    stance("mean_reversion")
    scores = {k: fe._technical_score(v, 100.0)
              for k, v in {"knife": KNIFE, "pullback": PULLBACK,
                           "drift": DRIFT, "blowoff": BLOWOFF}.items()}
    assert min(scores, key=scores.get) == "blowoff"


def test_pullback_is_the_best_reading(stance):
    stance("mean_reversion")
    scores = {k: fe._technical_score(v, 100.0)
              for k, v in {"knife": KNIFE, "pullback": PULLBACK,
                           "drift": DRIFT, "blowoff": BLOWOFF}.items()}
    assert max(scores, key=scores.get) == "pullback"


def test_momentum_stance_inverts_the_oscillators(stance):
    """Under momentum, strength is bullish and weakness is not."""
    stance("momentum")
    strong = tech(rsi=68, bb=0.85, stoch=0.88, macd=True, ma=True)
    assert fe._technical_score(strong, 100.0) > fe._technical_score(KNIFE, 100.0)


def test_blended_keeps_the_legacy_additive_arithmetic(stance):
    """
    `blended` exists so pre-gate results stay reproducible. If this drifts, the
    historical comparison it was kept for is worthless.
    """
    stance("blended")
    t = tech(rsi=42, bb=0.35, stoch=0.25, macd=True, ma=True)
    expected = 0.70 * 0.25 + 1.0 * 0.25 + 0.65 * 0.20 + 0.75 * 0.15 + 1.0 * 0.15
    assert fe._technical_score(t, 100.0) == pytest.approx(expected)


def test_missing_trend_inputs_fall_back_to_stance_weights(stance):
    """
    With nothing to gate on, gating against an invented neutral would scale
    every score down. The fallback must reproduce the old additive result.
    """
    stance("mean_reversion")
    t = tech(rsi=42, bb=0.35, stoch=0.25)          # no MACD, no MA cross
    expected = (0.70 * 0.30 + 0.65 * 0.25 + 0.75 * 0.20) / (0.30 + 0.25 + 0.20)
    assert fe._technical_score(t, 100.0) == pytest.approx(expected)


def test_partial_trend_input_still_gates(stance):
    """One trend input present is enough to gate; it should not be ignored."""
    stance("mean_reversion")
    both_bear = fe._technical_score(tech(rsi=30, bb=0.15, stoch=0.10, macd=False, ma=False), 100.0)
    one_bull  = fe._technical_score(tech(rsi=30, bb=0.15, stoch=0.10, macd=False, ma=True), 100.0)
    assert one_bull > both_bear


def test_no_indicators_returns_neutral(stance):
    stance("mean_reversion")
    assert fe._technical_score({}, 100.0) == 0.5


def test_score_stays_in_unit_interval(stance):
    """Every stance, every corner of the input space."""
    for name in ("mean_reversion", "momentum", "blended"):
        stance(name)
        for rsi in (0, 30, 50, 70, 100):
            for band in (0.0, 0.5, 1.0):
                for macd in (True, False, None):
                    for ma in (True, False, None):
                        s = fe._technical_score(
                            tech(rsi=rsi, bb=band, stoch=band, macd=macd, ma=ma), 100.0
                        )
                        assert 0.0 <= s <= 1.0, f"{name} {rsi} {band} {macd} {ma} -> {s}"
