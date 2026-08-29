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


# ── Benchmark-relative measurement ────────────────────────────────────────────
# Added with `services/benchmark.py`. The engine previously had no benchmark at
# all, so a composite that ranked raw returns by preferring high-beta names in
# a rising market would have read as perfectly calibrated.

def _rec(score, ret, alpha=None):
    row = {"score": score, "return_20d": ret, "signal": "BUY", "confidence": 0.6}
    if alpha is not None:
        row["alpha_20d"] = alpha
    return row


def test_alpha_carries_its_own_sample_count():
    """
    History settled before benchmark measurement existed has a return and no
    alpha. Reporting one `n` for both would let a three-record alpha inherit a
    three-hundred-record confidence.
    """
    rows = [_rec(0.8, 0.05) for _ in range(50)] + [_rec(0.8, 0.05, 0.01) for _ in range(3)]
    stats = summarise(rows)["base_rate"]
    assert stats["n"] == 53
    assert stats["alpha_n"] == 3
    assert stats["significant"] is True
    assert stats["alpha_significant"] is False


def test_alpha_is_absent_not_zero_when_no_record_carries_one():
    rows = [_rec(0.8, 0.05) for _ in range(50)]
    stats = summarise(rows)["base_rate"]
    assert stats["avg_alpha"] is None
    assert stats["alpha_win_rate"] is None
    assert stats["alpha_n"] == 0


def test_a_composite_that_ranks_returns_but_not_alpha_is_caught():
    """
    The case this whole column exists for: returns rise with score purely
    because the high buckets hold more market exposure. Raw ranking says the
    composite works; alpha says it picked beta.
    """
    rows = []
    for i in range(MIN_SAMPLES_FOR_SIGNAL + 5):
        # Low bucket: +1% return in a +1% market. High bucket: +9% in a +9%
        # market. Raw return rises steeply; alpha is flat at zero throughout.
        rows.append(_rec(0.35, 0.01, 0.0))
        rows.append(_rec(0.75, 0.09, 0.0))

    report = summarise(rows)
    assert report["score_ranks_outcomes"] is True
    # Flat alpha is still weakly monotonic, but the averages tell the story and
    # both must be present for a reader to see it.
    lows = [b for b in report["score_buckets"] if b["lo"] == 0.3][0]
    highs = [b for b in report["score_buckets"] if b["lo"] == 0.7][0]
    assert highs["avg_return"] > lows["avg_return"]
    assert highs["avg_alpha"] == lows["avg_alpha"] == 0.0


def test_summary_names_the_benchmark_so_the_client_does_not_have_to():
    report = summarise([_rec(0.8, 0.05, 0.01)])
    assert report["benchmark_ticker"]
    assert report["alpha_records"] == 1


# ── The research arm ──────────────────────────────────────────────────────────
# Whether the agent path is worth its cost. The reference implementation this
# system is measured against has no equivalent — it publishes backtest figures
# its own README says are not replicable, and never asks whether its debate
# improved anything.

from app.services.calibration import (  # noqa: E402
    assessment_accuracy, conviction_buckets, summarise_research,
    veto_counterfactual,
)


def _dossier(conviction, alpha, assessment="BULLISH", ret=None, correct=None,
             lesson=None):
    if correct is None and alpha is not None and assessment in ("BULLISH", "BEARISH"):
        correct = (alpha > 0) if assessment == "BULLISH" else (alpha < 0)
    return {
        "ticker": "EXMP",
        "outcome": {
            "research_conviction": conviction,
            "assessment": assessment,
            "return": ret if ret is not None else (alpha or 0.0) + 0.02,
            "alpha": alpha,
            "assessment_correct": correct,
            "reflection": {"lesson": lesson} if lesson else None,
        },
    }


def test_a_conviction_that_ranks_alpha_is_recognised():
    rows = []
    for _ in range(MIN_SAMPLES_FOR_SIGNAL + 5):
        rows.append(_dossier(10, -0.06))
        rows.append(_dossier(90, 0.06))
    report = summarise_research(rows)
    assert report["conviction_ranks_alpha"] is True
    assert report["graded_dossiers"] == len(rows)


def test_a_flat_conviction_curve_is_not_dressed_up():
    """
    If conviction separates nothing, no veto floor is the right floor and the
    answer is to fix the reading rather than move the line.
    """
    rows = [_dossier(c, 0.01) for c in (10, 30, 50, 70, 90)] * 20
    buckets = conviction_buckets(rows)
    alphas = [b["avg_alpha"] for b in buckets if b["avg_alpha"] is not None]
    assert len(set(alphas)) == 1


def test_ungraded_readings_are_excluded_from_accuracy_not_counted_as_misses():
    """
    NEUTRAL declined to take a side; an unmeasurable window has no side to
    take. Counting either as wrong makes the number describe the sample's
    direction instead of the reading's quality.
    """
    rows = (
        [_dossier(70, 0.05)] * 10                                   # right
        + [_dossier(70, -0.05)] * 10                                # wrong
        + [_dossier(50, None, correct=None)] * 40                   # unmeasurable
        + [_dossier(50, 0.05, assessment="NEUTRAL", correct=None)] * 40
    )
    bullish = [r for r in assessment_accuracy(rows) if r["assessment"] == "BULLISH"][0]
    neutral = [r for r in assessment_accuracy(rows) if r["assessment"] == "NEUTRAL"][0]

    assert bullish["graded"] == 20
    assert bullish["accuracy"] == pytest.approx(0.5)
    assert neutral["graded"] == 0
    assert neutral["accuracy"] is None


def test_the_veto_counterfactual_separates_blocked_from_allowed():
    """
    The number `RESEARCH_VETO_ENABLED` should be argued from, and that nobody
    has ever had. A blocked group that performed in line with the rest means
    the guard is refusing trades for no return.
    """
    rows = (
        [_dossier(20, -0.08)] * 40                              # under the floor
        + [_dossier(80, 0.04)] * 40                             # well over it
        + [_dossier(90, -0.03, assessment="BEARISH")] * 40      # bearish, blocked
    )
    got = veto_counterfactual(rows, floor=35.0)

    assert got["would_block"]["n"] == 80
    assert got["allowed"]["n"] == 40
    assert got["alpha_saved"] > 0
    assert got["conclusive"] is True


def test_a_veto_that_saves_nothing_reports_a_negative_saving():
    """The result that should stop the flag being switched on."""
    rows = [_dossier(20, 0.06)] * 40 + [_dossier(80, 0.01)] * 40
    got = veto_counterfactual(rows, floor=35.0)
    assert got["alpha_saved"] < 0


def test_thin_evidence_is_flagged_rather_than_shown_as_a_finding():
    rows = [_dossier(80, 0.05)] * 3
    got = veto_counterfactual(rows, floor=35.0)
    assert got["conclusive"] is False
    assert summarise_research(rows)["conviction_ranks_alpha"] is None


def test_ungraded_dossiers_are_ignored_entirely():
    rows = [_dossier(80, 0.05), {"ticker": "EXMP", "outcome": None},
            {"ticker": "EXMP"}]
    assert summarise_research(rows)["graded_dossiers"] == 1


def test_lessons_recorded_separates_a_quiet_loop_from_a_filtered_one():
    """
    A high graded count with few lessons means reflection is running and being
    citation-filtered away — a different problem from the loop not running.
    """
    rows = [_dossier(80, 0.05, lesson="Margins [F2] held.")] * 5 + [_dossier(80, 0.05)] * 15
    report = summarise_research(rows)
    assert report["graded_dossiers"] == 20
    assert report["lessons_recorded"] == 5


def test_the_research_arm_reports_and_does_not_tune():
    """
    Same standing refusal as the signal arm. Auto-fitting a floor to its own
    history is how a system talks itself into whatever the last few months
    happened to reward.
    """
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "app/services/calibration.py"
    text = source.read_text()
    for token in (r"update_one", r"\$set", r"settings\.\w+\s*="):
        assert not re.search(token, text), f"{token} — calibration must not write"


# ── Provenance segmentation ───────────────────────────────────────────────────
# Dossiers are now built on the trader's own key and their own chosen models,
# so the research arm can no longer assume one producer. Bucketing conviction
# against alpha across a mixture measures the mixture: a strong model and a
# weak one average into a middling curve that describes neither, and the
# conclusion drawn from it would be wrong about both.

from app.services.calibration import _model_label  # noqa: E402


def _graded(model=None, conviction=80, alpha=0.05):
    doc = {
        "ticker": "EXMP",
        "outcome": {
            "research_conviction": conviction, "assessment": "BULLISH",
            "return": alpha + 0.02, "alpha": alpha,
            "assessment_correct": alpha > 0, "reflection": None,
        },
    }
    if model is not None:
        doc["models_used"] = [{"provider": model[0], "model": model[1],
                               "agents": ["risk"]}]
    return doc


def test_a_dossier_is_labelled_by_the_model_that_wrote_it():
    label = _model_label(_graded(model=("anthropic", "claude-opus-5")))
    assert label == "anthropic/claude-opus-5"


def test_a_pre_provenance_dossier_is_labelled_unknown_not_guessed():
    """
    Those documents were in fact all Anthropic, but a bucket labelled with an
    assumption is exactly what gets read as measured a release later.
    """
    assert _model_label(_graded(model=None)) == "unknown"


def test_a_multi_model_dossier_labels_every_producer():
    doc = _graded()
    doc["models_used"] = [
        {"provider": "openai", "model": "gpt-5.5", "agents": ["news"]},
        {"provider": "anthropic", "model": "claude-opus-5", "agents": ["risk"]},
    ]
    label = _model_label(doc)
    assert "anthropic/claude-opus-5" in label and "openai/gpt-5.5" in label


def test_the_label_is_order_independent():
    """
    Two dossiers with the same models must land in the same bucket regardless
    of the order the agents happened to finish in.
    """
    a, b = _graded(), _graded()
    a["models_used"] = [
        {"provider": "openai", "model": "gpt-5.5", "agents": ["news"]},
        {"provider": "anthropic", "model": "claude-opus-5", "agents": ["risk"]},
    ]
    b["models_used"] = list(reversed(a["models_used"]))
    assert _model_label(a) == _model_label(b)


def test_a_strong_and_a_weak_model_do_not_average_into_one_curve():
    """
    The failure this segmentation prevents. Pooled, these two producers cancel
    into a flat curve and read as "conviction does not rank alpha" — which is
    false about both of them.
    """
    strong = [_graded(("a", "good"), conviction=90, alpha=0.08)] * 40
    strong += [_graded(("a", "good"), conviction=10, alpha=-0.08)] * 40
    weak = [_graded(("b", "bad"), conviction=90, alpha=-0.08)] * 40
    weak += [_graded(("b", "bad"), conviction=10, alpha=0.08)] * 40

    good = summarise_research(strong)
    bad = summarise_research(weak)
    pooled = summarise_research(strong + weak)

    assert good["conviction_ranks_alpha"] is True
    assert bad["conviction_ranks_alpha"] is False
    # Pooled, the signal is gone — which is why it is context and not the answer.
    assert pooled["base_rate"]["avg_alpha"] == pytest.approx(0.0, abs=1e-9)
