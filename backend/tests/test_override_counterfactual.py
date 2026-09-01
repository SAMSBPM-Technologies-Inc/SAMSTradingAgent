"""
Tests for `calibration.override_counterfactual` — were the gate's refusals
worth making?

The gate added in 1.22.0 overrides the AI analyst in two directions and neither
had ever been measured. This is the number `_gate_analyst_signal` should be
argued from, built to the same shape as `veto_counterfactual`.

Two things here are easy to get quietly wrong, and both are fenced below.

  * **The sign.** A SELL is right when the name *falls*, so `_stats`' win rate
    reads exactly backwards on an exit. A restored-SELL group that rose four
    times in five would otherwise report an 80% win rate on an 80% failure.
  * **Absent vs null.** A row from before 1.24.0 has no `analyst_override` key
    and says nothing either way; a row with `None` means the gate ran and had
    nothing to override. Counting the first as the second loads the control
    group with every row ever written before the gate existed, which would
    drown the comparison in exactly the data that cannot speak to it.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.calibration import (  # noqa: E402
    MIN_SAMPLES_FOR_SIGNAL, override_counterfactual, summarise,
)


def row(**over):
    """A settled history row with the gate recorded."""
    base = {
        "score": 0.65,
        "return_20d": 0.0,
        "alpha_20d": 0.0,
        "analyst_override": None,
        "analyst_wanted": None,
        "rule_signal": "HOLD",
    }
    base.update(over)
    return base


def refused(alpha, n=1):
    return [row(analyst_override="buy_refused", analyst_wanted="BUY",
                rule_signal="HOLD", alpha_20d=alpha, return_20d=alpha)
            for _ in range(n)]


def allowed(alpha, n=1):
    return [row(analyst_override=None, analyst_wanted="BUY",
                rule_signal="BUY", alpha_20d=alpha, return_20d=alpha)
            for _ in range(n)]


def restored(alpha, n=1):
    return [row(analyst_override="sell_restored", analyst_wanted="HOLD",
                rule_signal="SELL", alpha_20d=alpha, return_20d=alpha)
            for _ in range(n)]


def agreed(alpha, n=1):
    return [row(analyst_override=None, analyst_wanted="SELL",
                rule_signal="SELL", alpha_20d=alpha, return_20d=alpha)
            for _ in range(n)]


# ── Grouping ──────────────────────────────────────────────────────────────────

def test_the_two_overrides_are_never_pooled():
    """
    Opposite bets on opposite sides of the book, one of them sign-inverted. A
    pooled figure would not be slow to interpret; it would be meaningless.
    """
    report = override_counterfactual(refused(-0.1, 3) + restored(-0.1, 2))

    assert report["buy_refused"]["overridden"]["n"] == 3
    assert report["sell_restored"]["overridden"]["n"] == 2
    assert "pooled" not in report


def test_each_group_gets_its_own_control():
    report = override_counterfactual(
        refused(-0.05, 2) + allowed(0.05, 4) + restored(-0.05, 3) + agreed(-0.05, 5)
    )

    assert report["buy_refused"]["control"]["n"] == 4
    assert report["sell_restored"]["control"]["n"] == 5


def test_a_cycle_with_no_analyst_belongs_to_neither_side():
    """
    `analyst_wanted` is null: there was no opinion to override, so the row is
    evidence about the score, not about the gate. Counting it as a control
    would compare the gate's refusals against rows the gate never saw.
    """
    report = override_counterfactual(
        refused(-0.1, 2) + [row(alpha_20d=0.2, return_20d=0.2) for _ in range(9)]
    )

    assert report["buy_refused"]["control"]["n"] == 0
    assert report["buy_refused"]["overridden"]["n"] == 2


def test_rows_from_before_the_gate_are_excluded_entirely():
    """
    No `analyst_override` key at all. The distinction 1.24.0 shipped to
    preserve — absent is "never recorded", not "nothing to override".
    """
    ancient = [{"score": 0.65, "return_20d": 0.3, "alpha_20d": 0.3}
               for _ in range(50)]
    report = override_counterfactual(ancient + allowed(0.01, 2))

    assert report["recorded_records"] == 2
    assert report["buy_refused"]["control"]["n"] == 2


def test_unsettled_rows_cannot_inform_it():
    report = override_counterfactual(
        refused(-0.1, 1)
        + [row(analyst_override="buy_refused", analyst_wanted="BUY",
               return_20d=None, alpha_20d=None) for _ in range(5)]
    )

    assert report["buy_refused"]["overridden"]["n"] == 1


# ── The sign convention ───────────────────────────────────────────────────────

def test_a_refused_buy_that_fell_counts_as_the_gate_being_right():
    """Long side, raw. The names we did not buy went down."""
    report = override_counterfactual(refused(-0.10, 4) + allowed(0.10, 4))
    block = report["buy_refused"]

    # Refused names lost; the control gained. Positive alpha_saved = the gate
    # refused the worse names, the only result that justifies keeping it.
    assert block["overridden"]["avg_alpha"] < 0
    assert block["alpha_saved"] > 0


def test_a_refused_buy_that_rose_counts_against_the_gate():
    report = override_counterfactual(refused(0.10, 4) + allowed(0.02, 4))

    assert report["buy_refused"]["alpha_saved"] < 0


def test_a_restored_sell_is_scored_short_side():
    """
    The trap. These names FELL 10%, which means exiting them was correct — so
    the block must report a *win*, not a loss. Raw `_stats` would call a
    negative return a failure and invert the entire finding.
    """
    block = override_counterfactual(restored(-0.10, 4))["sell_restored"]

    assert block["direction"] == "short"
    assert block["overridden"]["win_rate"] == 1.0
    assert block["overridden"]["avg_alpha"] > 0


def test_a_restored_sell_that_rallied_counts_against_the_gate():
    """The analyst wanted to stay in and was right to."""
    block = override_counterfactual(restored(0.10, 4))["sell_restored"]

    assert block["overridden"]["win_rate"] == 0.0
    assert block["overridden"]["avg_alpha"] < 0


def test_alpha_saved_reads_the_same_way_on_both_blocks():
    """
    The one figure comparable across the two blocks, and the reason `_edge` is
    called with its arguments in opposite orders: **positive always means the
    gate's intervention was justified**.

    Note what is deliberately *not* uniform. Within `buy_refused` the
    overridden group is the one the gate made us skip, so a low figure there is
    a good result; within `sell_restored` it is sign-flipped so a high one is.
    Group and control share an orientation inside a block — which is what makes
    the delta mean anything — and `alpha_saved` is what carries across.
    """
    good = override_counterfactual(
        refused(-0.2, 3) + allowed(0.2, 3) + restored(-0.2, 3) + agreed(0.0, 3)
    )
    bad = override_counterfactual(
        refused(0.2, 3) + allowed(-0.2, 3) + restored(0.2, 3) + agreed(0.0, 3)
    )

    for key in ("buy_refused", "sell_restored"):
        assert good[key]["alpha_saved"] > 0, key
        assert bad[key]["alpha_saved"] < 0, key


def test_a_missing_outcome_is_not_negated_into_a_flat_one():
    """`None` stays `None`. Negating it into 0.0 would invent a result."""
    block = override_counterfactual(
        restored(-0.1, 2) + [row(analyst_override="sell_restored",
                                 analyst_wanted="HOLD", return_20d=-0.1,
                                 alpha_20d=None) for _ in range(3)]
    )["sell_restored"]

    assert block["overridden"]["n"] == 5          # returns settled
    assert block["overridden"]["alpha_n"] == 2    # alpha did not


# ── The discipline the rest of this module keeps ──────────────────────────────

def test_an_empty_sample_reports_nothing_rather_than_zero():
    """A 0.0 edge is a claim. Absence is not a result."""
    report = override_counterfactual([])

    assert report["recorded_records"] == 0
    assert report["buy_refused"]["alpha_saved"] is None
    assert report["sell_restored"]["alpha_saved"] is None
    assert report["buy_refused"]["conclusive"] is False


def test_one_thin_side_leaves_the_edge_unstated():
    """Both halves are needed; a comparison against nothing is not a comparison."""
    report = override_counterfactual(refused(-0.1, 5))

    assert report["buy_refused"]["overridden"]["n"] == 5
    assert report["buy_refused"]["control"]["n"] == 0
    assert report["buy_refused"]["alpha_saved"] is None


def test_conclusive_needs_both_sides_past_the_sample_floor():
    thin = override_counterfactual(
        refused(-0.1, MIN_SAMPLES_FOR_SIGNAL) + allowed(0.1, 3)
    )
    assert thin["buy_refused"]["conclusive"] is False

    thick = override_counterfactual(
        refused(-0.1, MIN_SAMPLES_FOR_SIGNAL) + allowed(0.1, MIN_SAMPLES_FOR_SIGNAL)
    )
    assert thick["buy_refused"]["conclusive"] is True


def test_it_is_reachable_from_the_report_the_page_reads():
    report = summarise(refused(-0.1, 2) + allowed(0.1, 2))

    assert report["analyst_gate"]["buy_refused"]["overridden"]["n"] == 2


def test_a_generator_of_records_is_not_silently_consumed():
    """
    `summarise` takes an Iterable and settles it before this runs. Passing the
    raw argument through would hand an emptied generator to the counterfactual
    and report a clean, confident nothing.
    """
    report = summarise(r for r in refused(-0.1, 2) + allowed(0.1, 2))

    assert report["analyst_gate"]["buy_refused"]["overridden"]["n"] == 2
