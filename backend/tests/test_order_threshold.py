"""
Tests for the *second* score bar — `AutoTradeSettings.min_signal_score`, tested
at `execute_entry` rather than at classification.

The case these exist for: it shipped defaulting to 0.75 against a
`BUY_THRESHOLD` of 0.70, with nothing tying the two together. The composite's
realistic ceiling is about 0.75, so every BUY the engine actually produced
landed in the band between them and was refused — recorded as a SKIPPED row
reading "Score 0.71 below threshold 0.75", underneath a ticker page whose gate
panel showed the BUY gate passing. The panel was right about the verdict and
silent about the order.

Two things stop that recurring: the default now tracks the threshold, and the
gate panel reports the bar. A third stops it recurring *in the other units* —
under relative scoring the engine's own bar is `RANK_BUY_FLOOR`, so testing a
raw 0.70 against a rank-decided BUY at 0.60 would reproduce the identical
failure one layer down.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import _LEGACY_MIN_SIGNAL_SCORE  # noqa: E402
from app.models.trade import AutoTradeSettings  # noqa: E402
from app.routes.analysis import _build_gate, _order_threshold  # noqa: E402
from app.services.signal_generator import (  # noqa: E402
    BUY_THRESHOLD, RANK_BUY_FLOOR,
)
from app.services.trade_manager import _order_score_bar  # noqa: E402


def doc(**over):
    base = {
        "ticker": "AAPL", "score": 0.72, "signal": "BUY",
        "risk": {"risk_score": 3.0, "risk_level": "LOW"},
    }
    return {**base, **over}


# ── The default ───────────────────────────────────────────────────────────────

def test_the_order_bar_defaults_to_the_verdict_threshold():
    """
    Not to a number of its own. A default above `BUY_THRESHOLD` voids a band of
    published BUYs and says so nowhere a reader would look.
    """
    assert AutoTradeSettings().min_signal_score == BUY_THRESHOLD


def test_the_old_default_was_above_the_threshold_it_was_never_tied_to():
    """Fences the arithmetic the migration exists to undo."""
    assert _LEGACY_MIN_SIGNAL_SCORE > BUY_THRESHOLD


# ── What the panel reports ────────────────────────────────────────────────────

def test_the_gate_reports_the_order_bar_beside_the_verdict_bar():
    g = _build_gate(doc(score=0.72), order_threshold=0.75)
    assert g.order_threshold == 0.75
    assert g.score_passes_order is False
    # The verdict bar it *did* clear, unchanged — the point is that both are
    # visible, not that one replaces the other.
    assert g.score_passes_buy is True


def test_no_settings_means_no_claim_either_way():
    """
    `None`, never `True`. "Nothing checked this" and "this passed" are
    different facts — the same distinction `AnalystGate.checked` draws.
    """
    g = _build_gate(doc())
    assert g.order_threshold is None
    assert g.score_passes_order is None


def test_a_malformed_settings_document_reports_nothing_rather_than_a_default():
    """A printed threshold nobody is actually held to is worse than silence."""
    assert _order_threshold({}) is None
    assert _order_threshold({"auto_trade_settings": None}) is None
    assert _order_threshold({"auto_trade_settings": {}}) is None
    assert _order_threshold({"auto_trade_settings": {"min_signal_score": "0.8"}}) is None
    assert _order_threshold({"auto_trade_settings": {"min_signal_score": 0.8}}) == 0.8


# ── Carrying the bar across the two rules ─────────────────────────────────────

def test_the_absolute_rule_applies_the_setting_as_written():
    assert _order_score_bar(0.75, rank_decided=False) == 0.75
    assert _order_score_bar(BUY_THRESHOLD, rank_decided=False) == BUY_THRESHOLD


def test_a_default_dial_never_vetoes_a_rank_decided_buy():
    """
    The failure this whole file is about, in the units of the relative rule. An
    account sitting on the default asks for exactly the engine's own bar, so it
    is never the reason a trade does not happen.
    """
    assert _order_score_bar(BUY_THRESHOLD, rank_decided=True) == RANK_BUY_FLOOR


def test_a_deliberate_margin_carries_across_rules_rather_than_the_number():
    """
    "Five points pickier than the engine" stays five points pickier. The raw
    0.75 would refuse nearly every rank-decided BUY, since those clear a floor
    of 0.55 rather than a threshold of 0.70.
    """
    bar = _order_score_bar(BUY_THRESHOLD + 0.05, rank_decided=True)
    assert abs(bar - (RANK_BUY_FLOOR + 0.05)) < 1e-9


def test_a_dial_below_the_engine_never_loosens_the_floor():
    """
    A setting under `BUY_THRESHOLD` means "whatever the rule publishes is fine",
    not "admit things the rule refused".
    """
    assert _order_score_bar(0.10, rank_decided=True) == RANK_BUY_FLOOR
