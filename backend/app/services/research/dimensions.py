"""
Dimension scores — five computed, one judged.

The report shape this system was asked for leads with six 0–100 scores:
business quality, financial strength, growth, valuation, technical, risk. Five
of them are arithmetic over figures we hold, and are computed here in plain
Python rather than asked of a model. That is not a stylistic preference. A
number a model produces cannot be reproduced, cannot be regression-tested, and
cannot be argued with — and these numbers are the headline of the report.

`business_quality` is the exception and stays with the model, because moat,
customer concentration and management quality are not arithmetic. It is flagged
`model_judged` so a reader can see which of the six is a different kind of
claim, in the same spirit as `explain_score` setting `attributable: false` on
the XGBoost path rather than inventing a decomposition it cannot support.

Coverage weighting follows the rest of the codebase: a dimension built from two
inputs is pulled toward the neutral 50 rather than trusted as if built from six,
and the coverage figure is reported so thin scores are visible as thin rather
than merely low.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_NEUTRAL = 50.0

#: Below this share of the available inputs, a dimension is marked thin and the
#: UI is expected to say so rather than render a confident-looking number. The
#: same idea as `MIN_SAMPLES_FOR_SIGNAL` on the calibration page.
_THIN_COVERAGE = 0.5


@dataclass
class Dimension:
    """One scored dimension, with the inputs that produced it."""

    key: str
    label: str
    score: Optional[float]
    coverage: float = 0.0
    components: list[dict] = field(default_factory=list)
    model_judged: bool = False
    note: Optional[str] = None

    @property
    def thin(self) -> bool:
        return self.score is not None and self.coverage < _THIN_COVERAGE

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "score": None if self.score is None else round(self.score, 1),
            "coverage": round(self.coverage, 3),
            "thin": self.thin,
            "model_judged": self.model_judged,
            "components": self.components,
            "note": self.note,
        }


def _band(value: Optional[float], low: float, high: float,
          invert: bool = False) -> Optional[float]:
    """
    Map a value onto 0–100 between two anchors, clamped at both ends.

    `low` is the 0 end and `high` the 100 end; `invert` swaps them for metrics
    where less is better. Linear on purpose — a curve here would encode a view
    about how much better a 40% margin is than a 30% one that this system has
    no evidence for.
    """
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if high == low:
        return None
    position = (value - low) / (high - low)
    if invert:
        position = 1.0 - position
    return max(0.0, min(1.0, position)) * 100.0


def _combine(key: str, label: str, weighted: list[tuple[str, Optional[float], float]],
             note: Optional[str] = None) -> Dimension:
    """
    Coverage-weighted mean of whichever components could be computed.

    A component that is None is absent, not zero. Scoring an unreported margin
    as 0 would rank a company we know nothing about below one we know to be
    unprofitable, which is precisely backwards.
    """
    present = [(name, score, weight) for name, score, weight in weighted
               if score is not None]
    total_weight = sum(weight for _, _, weight in weighted)
    if not present or total_weight <= 0:
        return Dimension(key=key, label=label, score=None, coverage=0.0, note=note)

    coverage = sum(weight for _, _, weight in present) / total_weight
    raw = (sum(score * weight for _, score, weight in present)
           / sum(weight for _, _, weight in present))
    score = raw * coverage + _NEUTRAL * (1.0 - coverage)
    return Dimension(
        key=key,
        label=label,
        score=score,
        coverage=coverage,
        components=[{"name": name, "score": round(value, 1), "weight": weight}
                    for name, value, weight in present],
        note=note,
    )


def financial_strength(fundamentals: dict, annual: list[dict]) -> Dimension:
    """Balance-sheet durability and the quality of the profit it produces."""
    latest = annual[0] if annual else {}
    current_ratio = None
    if latest.get("current_assets") is not None and latest.get("current_liabilities"):
        current_ratio = latest["current_assets"] / latest["current_liabilities"]

    fcf = fundamentals.get("free_cash_flow")
    if fcf is None and latest.get("free_cash_flow") is not None:
        fcf = latest["free_cash_flow"]

    # Leverage is read on whatever basis the filing supported. The two bases
    # differ by roughly a factor of two, so they get different anchors — using
    # one set of bounds for both would penalise every company whose filing
    # happened to omit a long-term-debt line.
    basis = fundamentals.get("debt_to_equity_basis")
    de_high = 60.0 if basis == "long_term_debt" else 120.0

    return _combine(
        "financial_strength",
        "Financial strength",
        [
            ("Net margin", _band(fundamentals.get("profit_margin"), 0.0, 0.25), 0.20),
            ("Return on equity", _band(fundamentals.get("return_on_equity"), 0.05, 0.30), 0.20),
            ("Return on invested capital", _band(fundamentals.get("roic"), 0.05, 0.25), 0.20),
            ("Leverage", _band(fundamentals.get("debt_to_equity"), 0.0, de_high, invert=True), 0.20),
            ("Cash generation", None if fcf is None else (100.0 if fcf > 0 else 0.0), 0.10),
            ("Liquidity", _band(current_ratio, 0.8, 2.5), 0.10),
        ],
    )


def growth(fundamentals: dict) -> Dimension:
    """
    Direction and durability, not one good quarter.

    Margin expansion is included alongside the growth rates because revenue
    bought at a falling margin is a different kind of growth from revenue that
    drops through — and the previous scorer, having only one period, could not
    tell them apart.
    """
    return _combine(
        "growth",
        "Growth",
        [
            ("Revenue growth (latest)", _band(fundamentals.get("revenue_growth_yoy"), -0.05, 0.30), 0.25),
            ("Revenue CAGR", _band(fundamentals.get("revenue_cagr"), 0.0, 0.25), 0.25),
            ("EPS CAGR", _band(fundamentals.get("eps_cagr"), 0.0, 0.30), 0.20),
            ("Earnings growth (latest)", _band(fundamentals.get("earnings_growth_yoy"), -0.05, 0.30), 0.10),
            ("Operating margin trend", _band(fundamentals.get("operating_margin_delta"), -0.05, 0.05), 0.10),
            ("Share count trend", _band(fundamentals.get("share_count_change"), -0.05, 0.05, invert=True), 0.10),
        ],
    )


def valuation(fundamentals: dict, fcf_yield: Optional[float]) -> Dimension:
    """
    How much is being paid for it. Higher score means cheaper.

    Deliberately not sector-adjusted: this system has no sector multiple
    distribution to adjust against, and inventing one would put a false
    precision on the most subjective of the six. A software company will read
    expensive here and a bank cheap — the dossier text is where that gets
    argued, with the sector stated in evidence.
    """
    return _combine(
        "valuation",
        "Valuation",
        [
            ("Trailing P/E", _band(fundamentals.get("pe_ratio"), 10.0, 45.0, invert=True), 0.20),
            ("Forward P/E", _band(fundamentals.get("forward_pe"), 10.0, 40.0, invert=True), 0.25),
            ("EV/EBITDA", _band(fundamentals.get("ev_to_ebitda"), 6.0, 25.0, invert=True), 0.20),
            ("Price/sales", _band(fundamentals.get("ps_ratio"), 1.0, 12.0, invert=True), 0.10),
            ("PEG", _band(fundamentals.get("peg_ratio"), 0.8, 3.0, invert=True), 0.10),
            ("Free cash flow yield", _band(fcf_yield, 0.0, 0.08), 0.15),
        ],
        note="Not sector-adjusted — compare against the peer set, not across sectors",
    )


def technical(features: dict) -> Dimension:
    """
    The existing engine's technical score, rescaled.

    Not recomputed. That scorer is stance-gated, tested across three stances and
    is the strongest part of this system; a second implementation here would be
    a second answer to a question already answered.
    """
    score = features.get("technical_score")
    if score is None:
        return Dimension(key="technical", label="Technical", score=None)
    return Dimension(
        key="technical",
        label="Technical",
        score=max(0.0, min(1.0, float(score))) * 100.0,
        coverage=1.0,
        components=[{"name": "Engine technical score", "score": round(float(score) * 100, 1),
                     "weight": 1.0}],
        note="From the live scoring engine, over a 90-day price window",
    )


def risk(risk_assessment: dict, fundamentals: dict) -> Dimension:
    """
    Higher score means safer — the same direction as the other five.

    This is the dimension most likely to be misread, so the direction is worth
    stating twice: the engine's own `risk_score` runs 0–10 with 10 being
    dangerous, and it is inverted here. A dossier where every bar reads "more is
    better" except one is a dossier that will be misread eventually.

    Price volatility is only part of it. Leverage and valuation stretch are
    business risks that the engine's price-risk gate does not look at, and
    "what could make this a terrible investment" is rarely answered by
    volatility alone.
    """
    engine = risk_assessment.get("risk_score")
    engine_score = None
    if engine is not None:
        engine_score = _band(engine, 0.0, 10.0, invert=True)

    basis = fundamentals.get("debt_to_equity_basis")
    de_high = 80.0 if basis == "long_term_debt" else 160.0

    return _combine(
        "risk",
        "Risk",
        [
            ("Price risk (engine gate, inverted)", engine_score, 0.45),
            ("Leverage", _band(fundamentals.get("debt_to_equity"), 0.0, de_high, invert=True), 0.25),
            ("Valuation stretch", _band(fundamentals.get("pe_ratio"), 15.0, 70.0, invert=True), 0.15),
            ("Margin durability", _band(fundamentals.get("operating_margin_delta"), -0.08, 0.02), 0.15),
        ],
        note="Higher is safer. Price risk is the engine's 0-10 gate, inverted",
    )


def business_quality_placeholder() -> Dimension:
    """
    The one dimension left to the model, created empty for it to fill.

    Returned unscored rather than defaulted to 50: an unanswered question and a
    middling answer are different, and a placeholder 50 would show up in the UI
    as a real reading of a mediocre business.
    """
    return Dimension(
        key="business_quality",
        label="Business quality",
        score=None,
        coverage=0.0,
        model_judged=True,
        note="Judged by the model from the business description and financials — "
             "moat and customer concentration are not arithmetic",
    )


def build_all(fundamentals: dict, annual: list[dict], features: dict,
              risk_assessment: dict, fcf_yield: Optional[float] = None) -> list[Dimension]:
    """The five computed dimensions plus the placeholder, in report order."""
    return [
        business_quality_placeholder(),
        financial_strength(fundamentals, annual),
        growth(fundamentals),
        valuation(fundamentals, fcf_yield),
        technical(features),
        risk(risk_assessment, fundamentals),
    ]


def derived_conviction(dimensions: list[Dimension]) -> Optional[float]:
    """
    A 0–100 conviction blended from whichever dimensions could be scored.

    This is the anchor the model is allowed to move within a band, not a number
    the model invents. The previous `conviction` was a three-value enum mapped
    to a hardcoded {0.85, 0.55, 0.25} — a decoration with no relationship to
    anything measured.

    Weights lean toward the dimensions with the most evidence behind them.
    Business quality is excluded here because it is unscored at this point; the
    synthesiser folds it in once the model has judged it.
    """
    weights = {
        "financial_strength": 0.25,
        "growth": 0.25,
        "valuation": 0.20,
        "technical": 0.15,
        "risk": 0.15,
    }
    present = [(d, weights[d.key]) for d in dimensions
               if d.key in weights and d.score is not None]
    if not present:
        return None
    total = sum(weight for _, weight in present)
    return round(sum(d.score * weight for d, weight in present) / total, 1)
