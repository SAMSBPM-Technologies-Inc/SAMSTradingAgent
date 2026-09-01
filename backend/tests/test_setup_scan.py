"""
Behavioural tests for the watchlist's timing badge — `setup_scan`.

The scan had no tests at all, which is how it kept the ungated dip rule for as
long as it did. `_technical_score` was rewritten so that trend GATES the
oscillators, because oversold-in-an-uptrend and oversold-in-free-fall look
identical on RSI, Bollinger and Stochastic and only the first is worth buying.
That module scores the two 0.388 and 0.907. This one printed the same green
ENTRY badge on both — at the top of the watchlist rail, above a high-conviction
BUY, where it is the most prominent thing on the page.

So the property under test is agreement: the badge and the score must answer
"dip or falling knife" the same way. Absolute thresholds matter far less and
are asserted only where the boundary is the point.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.setup_scan import (  # noqa: E402
    classify_trigger,
    setup_from_feature_doc,
    trend_confirmation,
)


def feat(rsi=None, stoch=None, bb=None, macd=None, ma=None, **over):
    doc = {
        "ticker": "EXMP", "rsi_14": rsi, "stoch_rsi": stoch, "bb_pct": bb,
        "macd_bullish": macd, "ma_cross_bullish": ma,
    }
    doc.update(over)
    return doc


def trig(**kw):
    d = feat(**kw)
    return classify_trigger(
        d["rsi_14"], d["stoch_rsi"], d["bb_pct"],
        d["macd_bullish"], d["ma_cross_bullish"],
    )


# ── The distinction the badge exists to draw ──────────────────────────────────

def test_a_pullback_in_an_uptrend_is_an_entry():
    assert trig(rsi=24, stoch=0.10, bb=0.20, macd=True, ma=True) == "ENTRY"


def test_a_falling_knife_is_not_an_entry():
    """
    Identical oscillator readings to the pullback above; the trend is the only
    difference, and it is the whole difference. This is the regression: the
    ungated rule badged this ENTRY at a risk score of 7.2.
    """
    assert trig(rsi=24, stoch=0.10, bb=0.20, macd=False, ma=False) != "ENTRY"


def test_one_surviving_confirmation_is_enough():
    """
    The bar is one leg, not two, because that is where the engine's own reading
    puts it — one bullish leg scores 0.662, neither scores 0.388. A discounted
    signal still ranks; an unconfirmed one does not prompt.
    """
    assert trig(rsi=24, stoch=0.10, bb=0.20, macd=True, ma=False) == "ENTRY"
    assert trig(rsi=24, stoch=0.10, bb=0.20, macd=False, ma=True) == "ENTRY"


def test_an_unknown_trend_is_not_an_entry():
    """
    Fail closed on the side that prompts a purchase. Note this is the OPPOSITE
    of what `_technical_score` does with a missing trend, where it falls back to
    the additive blend — a score must return a number for every ticker, and a
    badge has a third answer that costs nothing.
    """
    assert trig(rsi=24, stoch=0.10, bb=0.20) == "NEUTRAL"


# ── The oscillator conjunction, unchanged ─────────────────────────────────────

def test_all_three_oscillators_must_hold():
    for over in ({"rsi": 60}, {"stoch": 0.55}, {"bb": 0.80}):
        assert trig(**{"rsi": 24, "stoch": 0.10, "bb": 0.20,
                       "macd": True, "ma": True, **over}) != "ENTRY"


def test_a_missing_oscillator_can_never_satisfy_its_condition():
    assert trig(rsi=None, stoch=0.10, bb=0.20, macd=True, ma=True) == "NEUTRAL"


def test_the_entry_boundary_is_inclusive():
    """45 / 0.20 / 0.35 are documented as ≤, and FR-038 states them."""
    assert trig(rsi=45, stoch=0.20, bb=0.35, macd=True, ma=True) == "ENTRY"


# ── The exit side is deliberately not gated ───────────────────────────────────

def test_an_exit_alert_does_not_need_the_trend():
    """
    Never put a brake on the exit path. A trend condition here would suppress
    warnings rather than prompts, which is the wrong asymmetry — the same rule
    that keeps SELL clear of the risk gate, confirmations and dwell.
    """
    assert trig(rsi=78, bb=0.95, macd=False, ma=False) == "EXIT_ALERT"
    assert trig(rsi=78, bb=0.95) == "EXIT_ALERT"


def test_either_exit_condition_is_sufficient():
    assert trig(rsi=72, bb=0.50) == "EXIT_ALERT"
    assert trig(rsi=50, bb=0.95) == "EXIT_ALERT"


def test_an_overbought_reading_is_never_an_entry():
    assert trig(rsi=78, stoch=0.97, bb=0.97, macd=True, ma=True) == "EXIT_ALERT"


# ── trend_confirmation, the shared primitive ──────────────────────────────────

def test_trend_confirmation_distinguishes_broken_from_unknown():
    """
    The safe reading of each points the opposite way, so they must never
    collapse into one number.
    """
    assert trend_confirmation(False, False) == 0.0
    assert trend_confirmation(None, None) is None


def test_trend_confirmation_averages_what_it_has():
    assert trend_confirmation(True, False) == 0.5
    assert trend_confirmation(True, None) == 1.0
    assert trend_confirmation(True, True) == 1.0


def test_the_score_and_the_badge_read_trend_through_one_function():
    """
    The drift that caused this defect was two definitions of the same idea.
    `feature_engineering` imports this one; if it ever grows its own again,
    this fails.
    """
    import app.services.feature_engineering as fe

    assert fe.trend_confirmation is trend_confirmation


# ── The feature-document reducer ──────────────────────────────────────────────

def test_the_reducer_threads_the_trend_through():
    """
    The trigger is computed from the whole document, not from the three
    oscillators the projection used to fetch. FEATURE_PROJECTION must carry the
    trend fields or every row would read as unknown-trend and never badge.
    """
    from app.services.setup_scan import FEATURE_PROJECTION

    assert "macd_bullish" in FEATURE_PROJECTION
    assert "ma_cross_bullish" in FEATURE_PROJECTION

    pullback = setup_from_feature_doc(
        feat(rsi=24, stoch=0.10, bb=0.20, macd=True, ma=True, ma_20=100.0,
             current_price=93.0)
    )
    knife = setup_from_feature_doc(
        feat(rsi=24, stoch=0.10, bb=0.20, macd=False, ma=False, ma_20=100.0,
             current_price=93.0)
    )

    assert pullback["trigger"] == "ENTRY"
    assert knife["trigger"] == "NEUTRAL"
    # Everything else about the two rows is identical.
    assert pullback["pct_from_ma20"] == knife["pct_from_ma20"] == -7.0
