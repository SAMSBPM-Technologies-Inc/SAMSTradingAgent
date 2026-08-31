"""
Tests for the risk gate and position sizing.

These two are one subject. Volatility used to be charged to the composite AND
to the risk gate; removing it from the score was right — a stock is not a better
opportunity for being quiet — but it left the gate carrying weight it was never
calibrated for, and left sizing, where volatility genuinely belongs, ignoring it
entirely.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.risk_engine import RISK_MAX_FOR_BUY, assess_risk  # noqa: E402
from app.services.signal_generator import (  # noqa: E402
    BUY_THRESHOLD, SELL_THRESHOLD, _price_suggestions, classify_signal,
)
from app.services.trade_manager import _calculate_qty, _volatility_size_factor  # noqa: E402


def clean(vol):
    """A name whose only risk factor is its volatility."""
    return {"volatility_20d": vol, "rsi_14": 45, "composite_score": 0.85,
            "ma_cross_bullish": True}


# ── The volatility curve ──────────────────────────────────────────────────────

def test_the_knee_lands_exactly_on_the_buy_veto():
    """
    100% annualised is the veto point by construction, so "refused on
    volatility alone" and "moves more than 100% annualised" are one statement.
    """
    assert assess_risk(clean(1.00))["risk_score"] == pytest.approx(RISK_MAX_FOR_BUY)


def test_a_130_percent_name_is_now_refused():
    """It scored 5.88 under the old curve and passed — roughly ±8% a day."""
    assert assess_risk(clean(1.30))["risk_score"] >= RISK_MAX_FOR_BUY


def test_ordinary_growth_volatility_still_passes():
    """The gate must not become so tight it excludes what the tool is for."""
    for vol in (0.30, 0.45, 0.60, 0.80):
        assert assess_risk(clean(vol))["risk_score"] < RISK_MAX_FOR_BUY


def test_risk_rises_monotonically_with_volatility():
    prev = -1.0
    for i in range(0, 201, 5):
        score = assess_risk(clean(i / 100))["risk_score"]
        assert score >= prev, f"risk fell at vol {i}%"
        prev = score


def test_volatility_alone_leaves_headroom_for_other_factors():
    """Capped at 8.0 so a broken name can still be scored worse than a wild one."""
    wild = assess_risk(clean(2.0))["risk_score"]
    wild_and_broken = assess_risk({
        "volatility_20d": 2.0, "rsi_14": 80, "composite_score": 0.2,
        "ma_cross_bullish": False,
    })["risk_score"]
    assert wild_and_broken > wild


# ── Label and gate cannot disagree ────────────────────────────────────────────

def test_high_label_means_blocked_everywhere():
    """
    A score of 6.2 used to report MEDIUM while silently refusing the trade.
    Checked across the whole volatility range, not at a sample point.
    """
    for i in range(0, 201):
        r = assess_risk(clean(i / 100))
        blocked = r["risk_score"] >= RISK_MAX_FOR_BUY
        assert blocked == (r["risk_level"] == "HIGH"), (
            f"vol {i}%: risk {r['risk_score']} labelled {r['risk_level']}"
        )


# ── Single-sourced thresholds ─────────────────────────────────────────────────

def test_classify_signal_is_the_only_rule():
    assert classify_signal(BUY_THRESHOLD + 0.01, 1.0) == "BUY"
    assert classify_signal(BUY_THRESHOLD + 0.01, RISK_MAX_FOR_BUY) == "HOLD"
    assert classify_signal(SELL_THRESHOLD - 0.01, 1.0) == "SELL"
    assert classify_signal(0.5, 1.0) == "HOLD"


def test_exactly_on_a_threshold_does_not_trigger():
    """Both bounds are strict; a score of exactly 0.70 is not a BUY."""
    assert classify_signal(BUY_THRESHOLD, 1.0) == "HOLD"
    assert classify_signal(SELL_THRESHOLD, 1.0) == "HOLD"


def test_sell_is_not_gated_on_risk():
    """Refusing to exit because conditions are dangerous would be backwards."""
    assert classify_signal(0.1, 9.9) == "SELL"


# ── SELL means exit, not short ────────────────────────────────────────────────

def test_sell_advice_does_not_suggest_shorting():
    """
    Shorting is not permitted in a TFSA and trade_manager has no path that opens
    one — it only ever sells to close what the broker actually holds.
    """
    entry, exit_s = _price_suggestions("SELL", 100.0, {"volatility_20d": 0.4})
    assert entry is None
    assert "short" not in exit_s.lower() or "not a short" in exit_s.lower()
    assert "cover" not in exit_s.lower()


# ── Position sizing ───────────────────────────────────────────────────────────

def test_wilder_names_get_less_capital():
    quiet = _calculate_qty(100.0, 100_000, 0.05, 0.15)
    wild = _calculate_qty(100.0, 100_000, 0.05, 1.00)
    assert quiet > wild


def test_risk_per_position_is_roughly_equalised_in_the_normal_range():
    """
    Between the bounds, dollar exposure x volatility should be close to constant
    — that is the whole point of scaling. Flat sizing varies it by 6x.
    """
    exposures = []
    for vol in (0.25, 0.35, 0.50, 0.70):
        qty = _calculate_qty(100.0, 100_000, 0.05, vol)
        exposures.append(qty * 100.0 * vol)
    assert max(exposures) / min(exposures) < 1.15


def test_pivot_volatility_gives_exactly_the_configured_size():
    assert _volatility_size_factor(0.35) == pytest.approx(1.0)
    assert _calculate_qty(100.0, 100_000, 0.05, 0.35) == 50


def test_factor_is_bounded_both_ways():
    """No position several times the intended size, none too small to be worth commission."""
    for vol in (0.001, 0.01, 0.05, 1.0, 3.0, 50.0):
        assert 0.30 <= _volatility_size_factor(vol) <= 1.60


def test_unknown_volatility_reproduces_flat_sizing():
    """A missing feature document must not guess."""
    assert _volatility_size_factor(None) == 1.0
    assert _volatility_size_factor(0) == 1.0
    assert _calculate_qty(100.0, 100_000, 0.05, None) == _calculate_qty(100.0, 100_000, 0.05)


def test_degenerate_inputs_return_zero():
    assert _calculate_qty(0, 100_000, 0.05, 0.3) == 0
    assert _calculate_qty(100.0, 0, 0.05, 0.3) == 0


# ── The risk gate reaches the order path, not just the verdict ────────────────
#
# RISK_MAX_FOR_BUY lived only inside `classify_signal`, so it guarded the rule's
# verdict and nothing else. Any BUY that arrived at `execute_entry` without
# having been produced by that rule was never risk-checked — and the analyst
# path published exactly such BUYs. CBRS was bought at risk 6.3 on 30 Aug 2026,
# past a veto documented as unconditional.

import asyncio  # noqa: E402

from app.services import trade_manager as TM  # noqa: E402


class _FeatColl:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, *_a, **_k):
        return self._doc


class _FeatDb:
    def __init__(self, doc):
        self._doc = doc

    def __getitem__(self, _name):
        return _FeatColl(self._doc)


def _wire_features(monkeypatch, doc):
    async def fake_get_db():
        return _FeatDb(doc)

    monkeypatch.setattr(TM, "get_db", fake_get_db)


def test_the_order_path_refuses_a_name_past_the_veto(monkeypatch):
    _wire_features(monkeypatch, clean(1.30))
    reason = asyncio.run(TM._risk_veto("EXMP"))

    assert reason is not None
    assert "Risk gate" in reason


def test_the_order_path_allows_an_ordinary_name(monkeypatch):
    _wire_features(monkeypatch, clean(0.45))
    assert asyncio.run(TM._risk_veto("EXMP")) is None


def test_an_unassessable_ticker_is_allowed_through(monkeypatch):
    """
    Same instinct as the research veto: a guard that halts buying because a
    document is missing is a worse failure than one that occasionally lets a
    trade through. Without features there is no signal to act on either.
    """
    _wire_features(monkeypatch, None)
    assert asyncio.run(TM._risk_veto("EXMP")) is None


def test_a_database_failure_is_allowed_through(monkeypatch):
    async def boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(TM, "get_db", boom)
    assert asyncio.run(TM._risk_veto("EXMP")) is None


def test_the_agent_path_consults_the_risk_gate(monkeypatch):
    """
    Wiring, not arithmetic: the guard has to be *in* the shared chain.
    `pipeline._execute_trades` reaches `execute_entry` on the 5-minute cycle
    with no request behind it, so a check that lives anywhere else is skippable.
    """
    async def allow(_user_id):
        return True

    async def veto(_ticker):
        return "Risk gate: refused"

    monkeypatch.setattr(TM, "_may_trade", allow)
    monkeypatch.setattr(TM, "_risk_veto", veto)

    plan, reason = asyncio.run(TM._prepare_entry(
        "u1", "EXMP", TM.AutoTradeSettings(), 100.0, None, None,
    ))

    assert plan is None
    assert reason == "Risk gate: refused"


def test_a_hand_placed_order_is_not_risk_gated(monkeypatch):
    """
    The order ticket tells the user in as many words that the risk gate
    restricts what the *agent* may pick and that they may place the order
    anyway. The research veto is the one that refuses a person too — see
    CLAUDE.md on which guards are shared and which are the agent's.
    """
    seen = {}

    async def fake_settings(_user_id):
        return TM.AutoTradeSettings()

    async def fake_price(_ticker):
        return 100.0

    async def fake_prepare(*_a, **kw):
        seen.update(kw)
        return None, "stopped here"

    monkeypatch.setattr(TM, "_get_user_settings", fake_settings)
    monkeypatch.setattr(TM, "_last_known_price", fake_price)
    monkeypatch.setattr(TM, "_prepare_entry", fake_prepare)

    asyncio.run(TM.execute_manual_entry("u1", "EXMP"))

    assert seen["enforce_risk_gate"] is False
    # The whitelist is the agent's too, and the research veto is not opted out
    # of anywhere — it must stay absent from this list.
    assert seen["enforce_whitelist"] is False
    assert "enforce_research_veto" not in seen
