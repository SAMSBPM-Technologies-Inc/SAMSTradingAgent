"""
Tests for the BUY-gate panel's data — `routes/analysis._build_gate`.

The panel reported `score > 0.70` and nothing else, whatever had actually
produced the verdict. Two mechanisms make that wrong, and both were live:

  * the hysteresis band holds an established BUY down to 0.67, so a perfectly
    correct standing BUY rendered "✗ Score above threshold";
  * the analyst published verdicts of its own, so a BUY at 0.62 rendered the
    same ✗ — which was the truth, but the panel could not say whose decision it
    was describing.

An external review read the second case four times over and concluded the
engine was ignoring its own rules. The panel's job is to explain the verdict
beside it; one that can contradict it is worse than none.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.routes.analysis import _build_gate  # noqa: E402
from app.services.risk_engine import RISK_MAX_FOR_BUY  # noqa: E402
from app.services.signal_generator import (  # noqa: E402
    BUY_THRESHOLD, SIGNAL_HYSTERESIS,
)


def doc(**over):
    base = {
        "ticker": "EXMP",
        "score": 0.72,
        "signal": "BUY",
        "risk": {"risk_score": 2.0, "risk_level": "LOW"},
    }
    base.update(over)
    return base


def gated(**over):
    """A signal document the analyst produced and the gate refused."""
    return doc(
        score=0.62, signal="HOLD", analyst_used=True,
        analyst_gate={
            "model_signal": "BUY", "rule_signal": "HOLD",
            "published_signal": "HOLD", "overridden": True,
            "override": "buy_refused", "reason": "…under the 0.70 a BUY needs.",
        },
        **over,
    )


# ── The hysteresis band ───────────────────────────────────────────────────────

def test_a_standing_buy_is_measured_against_the_band_it_is_held_by():
    """
    0.68 does not clear 0.70 and the BUY is still correct: entering requires
    0.70, leaving requires falling under 0.67. Reporting the entry threshold
    against a verdict already in force is what printed ✗ beside BUY.
    """
    g = _build_gate(doc(score=0.68, signal="BUY"))

    assert g.effective_buy_threshold == round(BUY_THRESHOLD - SIGNAL_HYSTERESIS, 4)
    assert g.score_passes_buy is True


def test_acquiring_a_buy_still_needs_the_full_threshold():
    """The band is one-sided. Nothing standing, no discount."""
    g = _build_gate(doc(score=0.68, signal="HOLD"))

    assert g.effective_buy_threshold == BUY_THRESHOLD
    assert g.score_passes_buy is False


def test_the_raw_threshold_is_still_reported():
    """
    The panel needs both numbers to explain itself — "0.70 to open, 0.67 to
    hold" — so the entry threshold must survive alongside the effective one.
    """
    g = _build_gate(doc(score=0.68, signal="BUY"))

    assert g.buy_threshold == BUY_THRESHOLD
    assert g.hysteresis == SIGNAL_HYSTERESIS


def test_the_risk_veto_is_unchanged_by_any_of_this():
    hot = _build_gate(doc(risk={"risk_score": 6.3, "risk_level": "HIGH"}))
    assert hot.risk_passes_buy is False
    assert hot.risk_max_for_buy == RISK_MAX_FOR_BUY


# ── Who decided ───────────────────────────────────────────────────────────────

def test_a_rule_verdict_names_no_analyst():
    g = _build_gate(doc())

    assert g.decided_by == "rule"
    assert g.analyst is None


def test_an_analyst_verdict_that_passed_is_attributed_to_the_analyst():
    g = _build_gate(doc(
        analyst_used=True,
        analyst_gate={"model_signal": "BUY", "overridden": False,
                      "override": None, "reason": None},
    ))

    assert g.decided_by == "analyst"
    assert g.analyst.checked is True
    assert g.analyst.override is None


def test_an_overridden_analyst_verdict_is_attributed_to_the_rule():
    """
    The analyst asked for a BUY and did not get one. The verdict on screen is
    the rule's, and saying "decided by the analyst" would credit a decision it
    did not get to make.
    """
    g = _build_gate(gated())

    assert g.decided_by == "rule"
    assert g.analyst.wanted == "BUY"
    assert g.analyst.override == "buy_refused"
    assert "0.70" in g.analyst.reason


def test_a_restored_sell_is_reported_as_its_own_kind():
    g = _build_gate(doc(
        score=0.18, signal="SELL", analyst_used=True,
        analyst_gate={"model_signal": "HOLD", "overridden": True,
                      "override": "sell_restored", "reason": "…never held back."},
    ))

    assert g.decided_by == "rule"
    assert g.analyst.override == "sell_restored"
    assert g.analyst.wanted == "HOLD"


def test_a_document_written_before_the_gate_says_so():
    """
    `analyst_used` with no gate record is a pre-1.22.0 document: the analyst
    decided and nothing checked it. That is not the same fact as "the gate ran
    and agreed", and collapsing the two would reintroduce the exact silence
    this panel exists to break.
    """
    g = _build_gate(doc(analyst_used=True))

    assert g.decided_by == "analyst"
    assert g.analyst.checked is False
    assert g.analyst.override is None


# ── The reader's own weights ──────────────────────────────────────────────────

def test_a_personalized_score_is_the_rules_verdict_over_the_readers_weights():
    """
    `compute_personalized_score` runs `classify_signal` on the reader's own
    weights, so the number on screen is rule-derived by construction. The
    stored analyst gate describes a different score, and attributing it to this
    one would be the same category error the panel was built to fix.
    """
    g = _build_gate(gated(), personalized=True)

    assert g.decided_by == "rule"
    assert g.analyst is None
