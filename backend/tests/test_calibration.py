"""
Tests for threshold calibration.

The engine wrote stocks_signal_history on every run and read it never, so
BUY_THRESHOLD stayed where it was first guessed while the evidence to place it
accumulated unused.

The load-bearing output is `score_ranks_outcomes`. If the composite does not
rank outcomes, no threshold is the right threshold and the answer is to fix the
score rather than move the line — so these tests check that the report can tell
a ranking composite from a flat one, and that it refuses to dress up thin
samples as findings.

Run with:  pytest backend/tests -q
"""
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.calibration import (  # noqa: E402
    MIN_SAMPLES_FOR_SIGNAL, confidence_buckets, score_buckets, summarise, threshold_sweep,
)


def ranking_history(n=400, seed=11):
    """A composite that works: return rises with score."""
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        s = rnd.uniform(0.15, 0.95)
        out.append({"score": s, "confidence": abs(s - 0.5) * 2, "risk_score": 2.0,
                    "return_20d": (s - 0.5) * 0.30 + rnd.gauss(0, 0.05)})
    return out


def flat_history(n=400, seed=12):
    """A composite that ranks nothing: return independent of score."""
    rnd = random.Random(seed)
    return [{"score": rnd.uniform(0.15, 0.95), "confidence": 0.5, "risk_score": 2.0,
             "return_20d": rnd.gauss(0.01, 0.09)} for _ in range(n)]


# ── The load-bearing diagnostic ───────────────────────────────────────────────

def test_detects_a_composite_that_ranks():
    assert summarise(ranking_history())["score_ranks_outcomes"] is True


def test_detects_a_composite_that_does_not_rank():
    assert summarise(flat_history())["score_ranks_outcomes"] is False


def test_ranking_is_undecidable_without_enough_buckets():
    """Two thin buckets are not evidence of a trend in either direction."""
    assert summarise([{"score": 0.8, "return_20d": 0.1}])["score_ranks_outcomes"] is None


def test_returns_rise_across_buckets_when_the_score_works():
    rows = [b for b in score_buckets(ranking_history()) if b["significant"]]
    assert all(a["avg_return"] <= b["avg_return"] for a, b in zip(rows, rows[1:]))


# ── Settlement ────────────────────────────────────────────────────────────────

def test_unsettled_records_are_excluded():
    """A signal whose 20 days have not elapsed cannot inform anything."""
    recs = [{"score": 0.8, "return_20d": None},
            {"score": 0.8, "return_20d": 0.1},
            {"score": 0.8}]
    assert summarise(recs)["settled_records"] == 1


def test_records_without_a_score_are_excluded():
    assert summarise([{"return_20d": 0.1}])["settled_records"] == 0


def test_empty_history_does_not_crash():
    r = summarise([])
    assert r["settled_records"] == 0
    assert r["base_rate"]["win_rate"] is None
    assert r["score_ranks_outcomes"] is None


# ── Honesty about sample size ─────────────────────────────────────────────────

def test_thin_buckets_are_flagged_not_hidden():
    """'We have no evidence here' is itself worth reporting."""
    rows = score_buckets([{"score": 0.75, "return_20d": 0.2}])
    populated = [b for b in rows if b["n"]]
    assert populated and all(b["significant"] is False for b in populated)


def test_significance_flips_at_the_documented_threshold():
    recs = [{"score": 0.75, "return_20d": 0.01}] * MIN_SAMPLES_FOR_SIGNAL
    row = next(b for b in score_buckets(recs) if b["n"])
    assert row["significant"] is True
    row = next(b for b in score_buckets(recs[:-1]) if b["n"])
    assert row["significant"] is False


# ── Threshold sweep ───────────────────────────────────────────────────────────

def test_sweep_selects_only_scores_above_the_cutoff():
    recs = [{"score": 0.6, "return_20d": -0.1}, {"score": 0.9, "return_20d": 0.2}]
    row = next(r for r in threshold_sweep(recs, [0.7]) if r["threshold"] == 0.7)
    assert row["n"] == 1
    assert row["avg_return"] == pytest.approx(0.2)


def test_sweep_threshold_is_strict():
    recs = [{"score": 0.70, "return_20d": 0.5}]
    assert next(r for r in threshold_sweep(recs, [0.70]))["n"] == 0


def test_risk_gate_can_be_replayed_when_history_carries_it():
    recs = [{"score": 0.9, "risk_score": 1.0, "return_20d": 0.2},
            {"score": 0.9, "risk_score": 9.0, "return_20d": -0.3}]
    ungated = next(r for r in threshold_sweep(recs, [0.7]))
    gated = next(r for r in threshold_sweep(recs, [0.7], risk_max=6.0))
    assert ungated["n"] == 2 and gated["n"] == 1
    assert gated["avg_return"] == pytest.approx(0.2)


def test_risk_coverage_reports_how_much_of_the_sample_carries_a_risk_score():
    """
    History did not store risk_score until this was written. Reading a gated
    sweep over score-only rows as if it modelled the real gate would overstate
    it, so coverage is reported rather than assumed.
    """
    recs = [{"score": 0.9, "risk_score": 1.0, "return_20d": 0.2},
            {"score": 0.9, "return_20d": 0.1}]
    assert next(r for r in threshold_sweep(recs, [0.7]))["risk_coverage"] == 0.5


def test_records_without_risk_score_survive_a_gated_sweep():
    """Old rows must not silently vanish from the sample when the gate is on."""
    recs = [{"score": 0.9, "return_20d": 0.2}]
    assert next(r for r in threshold_sweep(recs, [0.7], risk_max=6.0))["n"] == 1


# ── Confidence ────────────────────────────────────────────────────────────────

def test_confidence_buckets_span_the_unit_interval():
    rows = confidence_buckets(ranking_history(), bins=5)
    assert len(rows) == 5
    assert rows[0]["lo"] == 0.0 and rows[-1]["hi"] == 1.0


def test_confidence_of_exactly_one_is_not_dropped():
    recs = [{"score": 0.9, "confidence": 1.0, "return_20d": 0.1}]
    assert sum(b["n"] for b in confidence_buckets(recs)) == 1


def test_top_score_bucket_includes_a_perfect_score():
    assert sum(b["n"] for b in score_buckets([{"score": 1.0, "return_20d": 0.1}])) == 1


def test_win_rate_counts_only_positive_returns():
    """A flat 0.0 is not a win. Rates are reported rounded to 4dp."""
    recs = [{"score": 0.8, "return_20d": r} for r in (0.1, -0.1, 0.0)]
    assert summarise(recs)["base_rate"]["win_rate"] == pytest.approx(1 / 3, abs=5e-5)
