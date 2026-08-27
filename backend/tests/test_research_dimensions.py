"""
Tests for the six research dimension scores and the evidence ledger.

Five of the six dimensions are computed in Python precisely so they CAN be
tested — a number a model produces is not reproducible and cannot be regression
tested, and these numbers are the headline of the report.

The properties that matter:

  * direction — more margin is better, more leverage is worse, and `risk`
    points the same way as the other five (higher is safer), because a report
    where one bar runs backwards will be misread eventually;
  * absent inputs lower COVERAGE, they never score zero. Scoring an unreported
    margin as 0 would rank a company we know nothing about below one we know to
    be unprofitable;
  * the ledger admits no fact without a value, and drops any claim without a
    citation.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.research import dimensions as D  # noqa: E402
from app.services.research.evidence import (  # noqa: E402
    Ledger,
    cited_ids,
    strip_uncited,
    strip_uncited_list,
    unknown_citations,
)

STRONG = {
    "profit_margin": 0.28, "return_on_equity": 0.32, "roic": 0.24,
    "debt_to_equity": 20.0, "debt_to_equity_basis": "long_term_debt",
    "free_cash_flow": 5.0e9,
    "revenue_growth_yoy": 0.30, "revenue_cagr": 0.24, "eps_cagr": 0.28,
    "operating_margin_delta": 0.05, "share_count_change": -0.03,
    "pe_ratio": 14.0, "forward_pe": 12.0, "ev_to_ebitda": 8.0,
    "ps_ratio": 2.0, "peg_ratio": 0.9,
}
WEAK = {
    "profit_margin": 0.01, "return_on_equity": 0.03, "roic": 0.02,
    "debt_to_equity": 140.0, "debt_to_equity_basis": "long_term_debt",
    "free_cash_flow": -1.0e9,
    "revenue_growth_yoy": -0.10, "revenue_cagr": -0.05, "eps_cagr": None,
    "operating_margin_delta": -0.08, "share_count_change": 0.09,
    "pe_ratio": 90.0, "forward_pe": 85.0, "ev_to_ebitda": 40.0,
    "ps_ratio": 20.0, "peg_ratio": 6.0,
}
LIQUID = [{"current_assets": 4.0e10, "current_liabilities": 1.0e10}]
ILLIQUID = [{"current_assets": 1.0e10, "current_liabilities": 2.0e10}]


# ── Direction ─────────────────────────────────────────────────────────────────

def test_financial_strength_separates_strong_from_weak():
    strong = D.financial_strength(STRONG, LIQUID).score
    weak = D.financial_strength(WEAK, ILLIQUID).score
    assert strong > weak
    assert strong - weak > 40


def test_growth_separates_growing_from_shrinking():
    assert D.growth(STRONG).score > D.growth(WEAK).score


def test_valuation_scores_cheap_above_expensive():
    """Higher means cheaper — the opposite of the raw multiple."""
    assert D.valuation(STRONG, 0.07).score > D.valuation(WEAK, 0.001).score


def test_risk_is_higher_for_the_safer_company():
    """
    Direction check. The engine's own risk_score runs 0-10 with 10 dangerous;
    this dimension inverts it so all six bars read "more is better".
    """
    calm = D.risk({"risk_score": 2.0}, STRONG).score
    jumpy = D.risk({"risk_score": 9.0}, WEAK).score
    assert calm > jumpy


def test_risk_inverts_the_engine_gate():
    low = D.risk({"risk_score": 1.0}, STRONG).score
    high = D.risk({"risk_score": 9.0}, STRONG).score
    assert low > high


def test_technical_rescales_the_engine_score_without_recomputing_it():
    assert D.technical({"technical_score": 0.68}).score == pytest.approx(68.0)
    assert D.technical({}).score is None


@pytest.mark.parametrize("field,better,worse", [
    ("profit_margin", 0.30, 0.02),
    ("return_on_equity", 0.35, 0.05),
    ("roic", 0.25, 0.03),
])
def test_profitability_is_monotone(field, better, worse):
    good = D.financial_strength({**STRONG, field: better}, LIQUID).score
    bad = D.financial_strength({**STRONG, field: worse}, LIQUID).score
    assert good >= bad


def test_more_leverage_scores_worse():
    light = D.financial_strength({**STRONG, "debt_to_equity": 5.0}, LIQUID).score
    heavy = D.financial_strength({**STRONG, "debt_to_equity": 200.0}, LIQUID).score
    assert light > heavy


def test_dilution_scores_worse_than_buybacks():
    buyback = D.growth({**STRONG, "share_count_change": -0.05}).score
    dilution = D.growth({**STRONG, "share_count_change": 0.05}).score
    assert buyback > dilution


def test_the_two_leverage_bases_use_different_anchors():
    """
    The bases differ by roughly a factor of two, so one set of bounds would
    penalise every company whose filing happened to omit a debt line.
    """
    filed = D.financial_strength(
        {**STRONG, "debt_to_equity": 60.0, "debt_to_equity_basis": "long_term_debt"},
        LIQUID).score
    approximated = D.financial_strength(
        {**STRONG, "debt_to_equity": 60.0,
         "debt_to_equity_basis": "total_liabilities_halved"}, LIQUID).score
    assert approximated > filed


# ── Bounds and coverage ───────────────────────────────────────────────────────

@pytest.mark.parametrize("fundamentals", [STRONG, WEAK, {}])
def test_every_score_stays_in_range(fundamentals):
    for score in D.build_all(fundamentals, LIQUID, {"technical_score": 0.5},
                             {"risk_score": 5.0}, fcf_yield=0.03):
        if score.score is not None:
            assert 0.0 <= score.score <= 100.0


def test_no_inputs_means_no_score_not_a_zero():
    """
    The distinction the whole scorer rests on. A company we know nothing about
    must not rank below one we know to be bad.
    """
    assert D.growth({}).score is None
    assert D.financial_strength({}, []).score is None


def test_a_missing_input_lowers_coverage_rather_than_the_score():
    full = D.growth(STRONG)
    partial = D.growth({"revenue_growth_yoy": 0.30, "revenue_cagr": 0.24})
    assert partial.coverage < full.coverage
    # Pulled toward neutral, not toward zero.
    assert partial.score < full.score
    assert partial.score > 50.0


def test_thin_coverage_is_flagged():
    thin = D.valuation({"pe_ratio": 20.0}, None)
    assert thin.thin is True
    assert thin.coverage < 0.5


def test_full_coverage_is_not_flagged_thin():
    assert D.financial_strength(STRONG, LIQUID).thin is False


def test_one_terrible_input_cannot_drag_a_scored_dimension_to_zero():
    """Coverage weighting means a single component never owns the whole score."""
    score = D.growth({**STRONG, "revenue_growth_yoy": -0.50}).score
    assert score > 20.0


# ── Business quality and conviction ───────────────────────────────────────────

def test_business_quality_starts_unscored_and_flagged():
    placeholder = D.business_quality_placeholder()
    assert placeholder.score is None
    assert placeholder.model_judged is True


def test_business_quality_is_the_only_model_judged_dimension():
    judged = [d.key for d in D.build_all(STRONG, LIQUID, {"technical_score": 0.5},
                                         {"risk_score": 4.0})
              if d.model_judged]
    assert judged == ["business_quality"]


def test_conviction_tracks_the_dimensions():
    strong = D.derived_conviction(
        D.build_all(STRONG, LIQUID, {"technical_score": 0.8}, {"risk_score": 2.0}, 0.07))
    weak = D.derived_conviction(
        D.build_all(WEAK, ILLIQUID, {"technical_score": 0.2}, {"risk_score": 9.0}, 0.0))
    assert strong > weak


def test_conviction_is_none_when_nothing_scored():
    assert D.derived_conviction(D.build_all({}, [], {}, {})) is None


def test_conviction_excludes_the_unscored_business_quality():
    """
    It is unscored at the point the anchor is computed; including it would
    average in a placeholder and quietly pull every anchor toward the middle.
    """
    scores = D.build_all(STRONG, LIQUID, {"technical_score": 0.8},
                         {"risk_score": 2.0}, 0.07)
    without = D.derived_conviction(scores)
    for score in scores:
        if score.key == "business_quality":
            score.score = 0.0
    assert D.derived_conviction(scores) == without


# ── Evidence ledger ───────────────────────────────────────────────────────────

def test_a_none_value_is_never_admitted():
    """
    The single most important line in the ledger. An "unknown" entry would get
    an id, and an agent would cite it — indistinguishable from a real fact.
    """
    ledger = Ledger()
    assert ledger.add("F", "Gross margin", None, "src") is None
    assert ledger.add("F", "Gross margin", "", "src") is None
    assert len(ledger) == 0


def test_ids_are_namespaced_and_sequential():
    ledger = Ledger()
    assert ledger.add("F", "a", 1, "s") == "F1"
    assert ledger.add("F", "b", 2, "s") == "F2"
    assert ledger.add("V", "c", 3, "s") == "V1"


def test_uncited_prose_is_dropped():
    valid = {"F1"}
    kept = strip_uncited("Margins rose [F1]. Management is excellent.", valid)
    assert kept == "Margins rose [F1]."


def test_everything_uncited_returns_none_not_an_empty_string():
    """An absent section reads as absent; an empty string reads as a bug."""
    assert strip_uncited("No citations at all here.", {"F1"}) is None


def test_an_invented_citation_is_dropped():
    assert strip_uncited("Debt is crushing [F99].", {"F1"}) is None
    assert unknown_citations("Debt is crushing [F99].", {"F1"}) == {"F99"}


def test_list_items_are_filtered_whole():
    kept = strip_uncited_list(["Real risk [F1]", "Vague worry"], {"F1"})
    assert kept == ["Real risk [F1]"]


def test_decimals_do_not_split_sentences():
    """A naive full-stop split would cut "12.4%" in half and drop the citation."""
    text = "Gross margin reached 62.4% in the period [F1]."
    assert strip_uncited(text, {"F1"}) == text


def test_citation_extraction_finds_every_id():
    assert cited_ids("a [F1] b [V12] c [T3]") == {"F1", "V12", "T3"}


def test_render_shows_provenance():
    ledger = Ledger()
    ledger.add("F", "Gross margin", "60.0%", "Massive", as_of="2025-12-31")
    rendered = ledger.render()
    assert "[F1]" in rendered and "Massive" in rendered and "2025-12-31" in rendered


def test_prefix_filtering_scopes_an_agent_to_its_slice():
    ledger = Ledger()
    ledger.add("F", "margin", "60%", "s")
    ledger.add("T", "rsi", "55", "s")
    assert "[T1]" not in ledger.render(("F",))
    assert "[F1]" in ledger.render(("F",))
