"""
Tests for the research agent orchestrator.

The properties under test are the ones the decomposition exists to provide, and
none of them were testable in the single analyst call this replaces — that call
built its API client inline, so there was no seam to test through and it has
zero tests to this day.

What matters here:

  * the four specialists actually run CONCURRENTLY, not in sequence;
  * one agent failing degrades the dossier rather than losing it;
  * an uncited claim is DROPPED, and an invented citation is dropped and
    recorded;
  * the synthesiser cannot move conviction arbitrarily away from the
    arithmetic anchor.

Run with:  pytest backend/tests -q
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.research import dossier as D  # noqa: E402
from app.services.research.evidence import Ledger  # noqa: E402


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Usage:
    input_tokens = 100
    output_tokens = 50
    cache_read_input_tokens = 0


class _Message:
    stop_reason = "end_turn"
    stop_details = None

    def __init__(self, payload):
        self.content = [_Block(json.dumps(payload))]
        self.usage = _Usage()


class _Messages:
    def __init__(self, owner):
        self._owner = owner

    async def create(self, **kwargs):
        name = self._owner.identify(kwargs)
        self._owner.started.append((name, time.perf_counter()))
        await asyncio.sleep(self._owner.delay)
        self._owner.finished.append((name, time.perf_counter()))

        if name in self._owner.fail:
            raise RuntimeError(f"{name} exploded")

        payload = self._owner.responses.get(name)
        if payload is None:
            pytest.fail(f"no canned response for agent {name!r}")
        message = _Message(payload)
        message.stop_reason = self._owner.stop_reasons.get(name, "end_turn")
        return message


class FakeClient:
    """
    Stands in for `anthropic.AsyncAnthropic`.

    Identifies which agent is calling from the schema it asked for, so the test
    does not depend on prompt wording — the prompts are prose and will change;
    the output contract is what the orchestrator actually relies on.
    """

    def __init__(self, responses, fail=(), stop_reasons=None, delay=0.05):
        self.responses = responses
        self.fail = set(fail)
        self.stop_reasons = stop_reasons or {}
        self.delay = delay
        self.started = []
        self.finished = []
        self.messages = _Messages(self)

    @staticmethod
    def identify(kwargs):
        required = set(kwargs["output_config"]["format"]["schema"]["required"])
        if "business_quality_score" in required:
            return "fundamentals"
        if "trend_regime" in required:
            return "technical"
        if "market_may_be_missing" in required:
            return "news"
        if "risk_severity" in required:
            return "risk"
        if "residual_severity" in required:
            return "risk_rebuttal"
        if "conceded" in required:
            return "defence_rebuttal"
        if "stance" in required:
            # All three stances share one schema, so they are told apart by the
            # temperament named in their system prompt rather than by shape.
            system = kwargs["system"][1]["text"]
            if "argue for conviction" in system:
                return "stance_aggressive"
            if "capital preservation" in system:
                return "stance_conservative"
            return "stance_neutral"
        if "assessment" in required:
            return "synthesiser"
        raise AssertionError(f"unrecognised schema: {sorted(required)}")


# ── Fixture data ──────────────────────────────────────────────────────────────

FUNDAMENTALS = {
    "source": "massive+alphavantage",
    "fetched_at": "2026-08-26T06:00:00+00:00",
    "company_name": "Example Corp",
    "description": "Example Corp makes widgets.",
    "sector": "Technology",
    "industry": "Semiconductors",
    "market_cap": 1.0e12,
    "profit_margin": 0.25,
    "return_on_equity": 0.30,
    "roic": 0.20,
    "debt_to_equity": 40.0,
    "debt_to_equity_basis": "long_term_debt",
    "free_cash_flow": 2.0e10,
    "revenue_growth_yoy": 0.22,
    "revenue_cagr": 0.18,
    "eps_cagr": 0.20,
    "pe_ratio": 30.0,
    "forward_pe": 24.0,
    "ev_to_ebitda": 18.0,
    "ps_ratio": 8.0,
    "statement_span_years": 4,
    "statement_periods": 5,
    "statement_newest_period": "2025-12-31",
}

ANNUAL = [
    {"period_end": "2025-12-31", "fiscal_year": "2025", "revenues": 1.0e11,
     "gross_margin": 0.60, "operating_margin": 0.35, "profit_margin": 0.25,
     "diluted_earnings_per_share": 4.0, "free_cash_flow": 2.0e10,
     "free_cash_flow_is_proxy": False, "equity": 6.0e10, "liabilities": 4.0e10,
     "current_assets": 5.0e10, "current_liabilities": 2.0e10, "roic": 0.20},
    {"period_end": "2024-12-31", "fiscal_year": "2024", "revenues": 8.0e10,
     "gross_margin": 0.57, "diluted_earnings_per_share": 3.2,
     "free_cash_flow": 1.6e10},
    {"period_end": "2023-12-31", "fiscal_year": "2023", "revenues": 6.5e10,
     "gross_margin": 0.55, "diluted_earnings_per_share": 2.5,
     "free_cash_flow": 1.2e10},
    {"period_end": "2022-12-31", "fiscal_year": "2022", "revenues": 5.0e10,
     "gross_margin": 0.53, "diluted_earnings_per_share": 2.0,
     "free_cash_flow": 9.0e9},
]

FEATURES = {"ticker": "EXMP", "current_price": 120.0, "rsi_14": 55.0,
            "ma_20": 115.0, "ma_50": 108.0, "ma_cross_bullish": True,
            "macd_bullish": True, "bb_pct": 0.62, "atr_14": 3.4,
            "volatility_20d": 0.34, "volume_anomaly": 1.4,
            "technical_score": 0.68, "composite_score": 0.63}

RAW = {"ticker": "EXMP", "current_price": 120.0, "day_change_pct": 1.2,
       "recent_headlines": [
           {"headline": "Example Corp lands large order", "source": "Reuters",
            "datetime": "2026-08-25T10:00:00+00:00", "url": "https://ex.com/1"},
       ],
       "sentiment_raw": {"article_count": 9, "bullish_pct": 0.6, "bearish_pct": 0.2},
       "macro": {"vix": 17.0, "fed_funds_rate": 4.0, "treasury_10y": 4.2,
                 "treasury_2y": 4.0, "yield_curve_spread": 0.2},
       "alternative_data": {}}

EARNINGS = {
    "quarterly_earnings": [
        {"fiscal_date_ending": "2026-09-30", "reported_date": "2026-10-28",
         "reported_eps": None, "estimated_eps": 1.10},
        {"fiscal_date_ending": "2026-06-30", "reported_date": "2026-07-29",
         "reported_eps": 1.05, "estimated_eps": 0.98, "surprise": 0.07,
         "surprise_pct": 7.14},
    ],
    "annual_earnings": [{"fiscal_date_ending": "2025-12-31", "reported_eps": 4.0}],
    "next_earnings_date": "2026-10-28",
    "earnings_beat_rate": 0.75, "earnings_beat_count": 3,
    "earnings_quarters_scored": 4, "avg_surprise_pct": 5.2,
    "fetched_at": "2026-08-26T06:00:00+00:00",
}


def _specialist_payloads():
    return {
        "fundamentals": {
            "findings": ["Gross margin has expanded every year on file [F2]."],
            "business_quality_score": 82,
            "business_quality_rationale": "Durable margins [F2] and high ROIC [F7].",
            "financial_summary": "Strong [F2].",
            "valuation_summary": "Full [V1].",
            "earnings_summary": "Consistent beats [E2].",
            "data_gaps": ["No segment disclosure"],
        },
        "technical": {
            "findings": ["Price is above both moving averages [T7]."],
            "trend_regime": "Uptrend [T9].",
            "timing_read": "Extended [T6].",
            "entry_zone": "", "invalidation_level": "",
            "data_gaps": ["Only 90 days of bars"],
        },
        "news": {
            "findings": ["A large order was reported [N1]."],
            "recent_developments": "Order win [N1].",
            "catalysts": ["Earnings on 2026-10-28 [E1]"],
            "market_may_be_missing": ["Flow ignores the near date [E1]"],
            "positioning_read": "No data [A1].",
            "data_gaps": ["No institutional ownership data"],
        },
        "risk": {
            "bear_case": "Valuation leaves no room for error [V1].",
            "key_risks": ["Multiple compression [V1]", "Margin reversal [F2]"],
            "what_would_change_my_opinion": ["Gross margin below 55% [F2]"],
            "risk_severity": 55,
            "severity_rationale": "Priced for continued growth [V1].",
            "data_gaps": ["No customer concentration disclosure"],
        },
    }


def _rebuttal_payloads():
    return {
        "risk_rebuttal": {
            "answered": ["Margin reversal is not supported by the trend [F2]"],
            "surviving": ["Multiple compression remains unaddressed [V1]"],
            "sharpened": [],
            "residual_severity": 40,
            "residual_rationale": "Most of the case rested on margins [F2].",
        },
        "defence_rebuttal": {
            "answered": ["Margin reversal [F2]"],
            "conceded": ["Nothing in the evidence bounds the multiple [V1]"],
            "overstated": [],
            "strongest_surviving_risk": "Multiple compression [V1]",
        },
    }


def _stance_payloads():
    return {
        "stance_aggressive": {
            "stance": "SIZE_UP",
            "rationale": "Margins keep expanding [F2] and price confirms [T7].",
            "what_would_change_it": "Gross margin below 55% [F2]",
        },
        "stance_conservative": {
            "stance": "SIZE_DOWN",
            "rationale": "The multiple leaves no room for error [V1].",
            "what_would_change_it": "A de-rating toward the historical band [V1]",
        },
        "stance_neutral": {
            "stance": "HOLD_SIZE",
            "rationale": "The record supports the thesis but not urgency [F2].",
            "what_would_change_it": "The earnings print [E1]",
        },
    }


def _all_payloads(**synthesis_overrides):
    """Every agent the default configuration will call, rebuttal included."""
    return (_specialist_payloads() | _rebuttal_payloads() | _stance_payloads()
            | {"synthesiser": _synthesis(**synthesis_overrides)})


def _synthesis(**overrides):
    payload = {
        "assessment": "BULLISH",
        "conviction": 70,
        "thesis": "Compounding at scale [F2].",
        "bull_case": "Margins keep expanding [F2].",
        "bear_case": "Valuation is full [V1].",
        "what_the_market_is_missing": "The near earnings date [E1].",
        "key_catalysts": ["Earnings on 2026-10-28 [E1]"],
        "key_risks": ["Multiple compression [V1]"],
        "risks_addressed": ["Margin reversal is unsupported by the trend [F2]"],
        "what_would_change_my_opinion": ["Gross margin below 55% [F2]"],
        "conclusion": "Hold through the print.",
        "conviction_rationale": "In line with the anchor.",
    }
    payload.update(overrides)
    return payload


class _FakeCollection:
    def __init__(self, doc=None):
        self._doc = doc
        self.inserted = []

    async def find_one(self, *_args, **_kwargs):
        return self._doc

    async def insert_one(self, doc):
        self.inserted.append(doc)


class _FakeDb:
    def __init__(self):
        self._collections = {
            "stocks_features": _FakeCollection(FEATURES),
            "stocks_raw": _FakeCollection(RAW),
            "research_dossiers": _FakeCollection(),
        }

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())


@pytest.fixture
def wired(monkeypatch):
    """Point the orchestrator at in-memory data and enable the feature."""
    db = _FakeDb()

    async def fake_get_db():
        return db

    async def fake_fundamentals(_ticker):
        return dict(FUNDAMENTALS)

    async def fake_statements(_ticker, timeframe="annual", limit=12):
        return list(ANNUAL) if timeframe == "annual" else []

    async def fake_earnings(_ticker):
        return dict(EARNINGS)

    monkeypatch.setattr(D, "get_db", fake_get_db)
    monkeypatch.setattr(D, "fetch_fundamentals", fake_fundamentals)
    monkeypatch.setattr(D, "fetch_statements", fake_statements)
    monkeypatch.setattr(D, "fetch_earnings", fake_earnings)

    settings = D.get_settings()
    monkeypatch.setattr(settings, "research_agents_enabled", True, raising=False)
    monkeypatch.setattr(settings, "research_extended_thinking", False, raising=False)
    # Pinned off here so every test written before the rebuttal existed keeps
    # exercising the path it was written for. The round has its own tests
    # below, which turn it on explicitly.
    monkeypatch.setattr(settings, "research_debate_rounds", 0, raising=False)
    monkeypatch.setattr(settings, "research_stance_panel_enabled", False,
                        raising=False)
    return db


def _run(client, wired_db=None):
    return asyncio.run(D.build_dossier("EXMP", client=client))


# ── Fan-out ───────────────────────────────────────────────────────────────────

def test_the_four_specialists_run_concurrently(wired):
    """
    Wall time must track the slowest agent, not the sum of all four.

    This is the whole reason for the fan-out. A regression to sequential calls
    would still produce a correct dossier, just four times slower, so nothing
    else in the suite would catch it.
    """
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses, delay=0.10)

    started = time.perf_counter()
    dossier = _run(client)
    elapsed = time.perf_counter() - started

    assert dossier is not None
    # Four specialists at 0.10s each plus one synthesis: concurrent is ~0.20s,
    # sequential would be ~0.50s. The midpoint separates them with room for
    # scheduling noise on a loaded machine.
    assert elapsed < 0.35, f"agents appear to be running sequentially ({elapsed:.2f}s)"

    specialist_starts = [t for name, t in client.started if name != "synthesiser"]
    assert max(specialist_starts) - min(specialist_starts) < 0.05


def test_synthesiser_runs_after_the_specialists(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses, delay=0.02)
    _run(client)

    synth_start = next(t for name, t in client.started if name == "synthesiser")
    last_specialist_end = max(t for name, t in client.finished if name != "synthesiser")
    assert synth_start >= last_specialist_end


# ── Degradation ───────────────────────────────────────────────────────────────

def test_one_failing_agent_leaves_the_dossier_standing(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses, fail={"news"})
    dossier = _run(client)

    assert dossier is not None
    assert dossier["agents_failed"] == ["news"]
    assert dossier["agents"]["news"]["ok"] is False
    assert dossier["agents"]["fundamentals"]["ok"] is True
    assert dossier["report"] is not None


def test_a_truncated_agent_is_recorded_not_parsed(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses, stop_reasons={"technical": "max_tokens"})
    dossier = _run(client)

    assert dossier["agents"]["technical"]["ok"] is False
    assert dossier["agents"]["technical"]["error"] == "max_tokens"


def test_a_refusal_is_recorded_not_parsed(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses, stop_reasons={"risk": "refusal"})
    dossier = _run(client)

    assert dossier["agents"]["risk"]["ok"] is False
    assert dossier["agents"]["risk"]["error"] == "refusal"


def test_every_agent_failing_still_returns_the_computed_half(wired):
    """
    The dimensions and the evidence are arithmetic, not model output.

    If all five calls fail, what survives is still a real, sourced view of the
    company — which is more than the previous analyst produced on a good day.
    """
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses,
                        fail={"fundamentals", "technical", "news", "risk"})
    dossier = _run(client)

    assert dossier is not None
    assert dossier["report"] is None
    assert dossier["evidence_count"] > 10
    assert any(d["score"] is not None for d in dossier["dimensions"])


# ── Citation enforcement ──────────────────────────────────────────────────────

def test_an_uncited_sentence_is_dropped(wired):
    responses = _specialist_payloads() | {
        "synthesiser": _synthesis(
            bull_case="Margins keep expanding [F2]. Management is world class."
        )
    }
    dossier = _run(FakeClient(responses))

    bull = dossier["report"]["bull_case"]
    assert "Margins keep expanding [F2]." in bull
    assert "world class" not in bull


def test_an_invented_citation_is_dropped_and_recorded(wired):
    """A fabricated id is the dangerous case: it survives a reader's spot-check."""
    responses = _specialist_payloads() | {
        "synthesiser": _synthesis(bear_case="Debt is unsustainable [F999].")
    }
    dossier = _run(FakeClient(responses))

    assert dossier["report"]["bear_case"] is None
    assert "F999" in dossier["citation_audit"]["invented"]


def test_uncited_list_items_are_dropped_whole(wired):
    responses = _specialist_payloads() | {
        "synthesiser": _synthesis(
            key_risks=["Multiple compression [V1]", "A general sense of unease"]
        )
    }
    dossier = _run(FakeClient(responses))

    assert dossier["report"]["key_risks"] == ["Multiple compression [V1]"]
    assert dossier["citation_audit"]["dropped"]["key_risks"] == 1


# ── citation_audit exposure ────────────────────────────────────────────────────
# The audit used to live inside `report` under `_`-prefixed keys, which meant
# it was computed, logged, and then silently dropped at the API boundary —
# ResearchReport has no such field, so Pydantic discarded it on the way out.
# Nothing short of reading the log line or the raw Mongo document could tell
# whether a clean-looking report had actually been checked. It is now returned
# separately by `_filter_report` and stored as its own top-level field.


def test_a_clean_report_has_an_empty_but_present_audit(wired):
    """
    Present, not absent — the absence of findings must be distinguishable from
    the field never having been computed at all.
    """
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses))

    assert dossier["citation_audit"] is not None
    assert dossier["citation_audit"]["dropped"] == {}
    assert dossier["citation_audit"]["invented"] == []


def test_report_itself_carries_no_underscore_keys(wired):
    """The audit must not leak back into the narrative object it was split from."""
    responses = _specialist_payloads() | {
        "synthesiser": _synthesis(bear_case="Debt is unsustainable [F999].")
    }
    dossier = _run(FakeClient(responses))

    assert not any(k.startswith("_") for k in dossier["report"])


def test_citation_audit_is_none_when_there_is_no_report(wired):
    """Nothing to audit when nothing was synthesised — not an empty audit."""
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses,
                              fail={"fundamentals", "technical", "news", "risk"}))

    assert dossier["report"] is None
    assert dossier["citation_audit"] is None


def test_citation_audit_reaches_the_api_model(wired):
    from app.routes.research import _to_model

    responses = _specialist_payloads() | {
        "synthesiser": _synthesis(bear_case="Debt is unsustainable [F999].",
                                  key_risks=["Real risk [V1]", "Vague worry"])
    }
    dossier = _run(FakeClient(responses))
    payload = _to_model(dossier).model_dump()

    assert payload["citation_audit"]["invented"] == ["F999"]
    # bear_case is dropped too: its only sentence cited nothing but the
    # fabricated id, so nothing survives the filter for that field either.
    assert payload["citation_audit"]["dropped"] == {"bear_case": 1, "key_risks": 1}


def test_citation_audit_clean_property_via_the_model(wired):
    from app.models.stock import CitationAudit

    assert CitationAudit(dropped={}, invented=[]).clean is True
    assert CitationAudit(dropped={"key_risks": 1}, invented=[]).clean is False
    assert CitationAudit(dropped={}, invented=["F999"]).clean is False


def test_the_conclusion_is_exempt_from_citation(wired):
    """It summarises cited material; requiring ids there produces noise, not rigour."""
    responses = _specialist_payloads() | {
        "synthesiser": _synthesis(conclusion="Hold through the print.")
    }
    dossier = _run(FakeClient(responses))
    assert dossier["report"]["conclusion"] == "Hold through the print."


# ── Conviction ────────────────────────────────────────────────────────────────

def test_conviction_is_clamped_to_the_derived_anchor(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis(conviction=99)}
    dossier = _run(FakeClient(responses))

    anchor = dossier["derived_research_conviction"]
    assert anchor is not None
    assert dossier["research_conviction"] <= anchor + 15 + 1e-6
    assert dossier["research_conviction"] < 99


def test_conviction_within_the_band_is_left_alone(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses))
    anchor = dossier["derived_research_conviction"]
    assert abs(dossier["research_conviction"] - 70) < 1e-6 or abs(dossier["research_conviction"] - anchor) <= 15


# ── Model-judged dimension ────────────────────────────────────────────────────

def test_business_quality_is_filled_by_the_fundamentals_agent(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses))

    bq = next(d for d in dossier["dimensions"] if d["key"] == "business_quality")
    assert bq["score"] == 82
    assert bq["model_judged"] is True


def test_business_quality_stays_unscored_when_its_agent_fails(wired):
    """A placeholder 50 would read as a real assessment of a mediocre business."""
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses, fail={"fundamentals"}))

    bq = next(d for d in dossier["dimensions"] if d["key"] == "business_quality")
    assert bq["score"] is None
    assert bq["model_judged"] is True


# ── Evidence scoping ──────────────────────────────────────────────────────────

def test_each_agent_sees_only_its_own_evidence_slice(wired):
    """
    Scoping is not only about tokens. An agent shown another's evidence can
    produce a second, quietly different reading of it.
    """
    seen = {}
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses)
    original = client.messages.create

    async def capture(**kwargs):
        name = FakeClient.identify(kwargs)
        seen[name] = kwargs["system"][0]["text"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    assert "[T1]" not in seen["fundamentals"]
    assert "[F1]" not in seen["technical"]
    assert "[F1]" in seen["fundamentals"]
    assert "[T1]" in seen["technical"]
    # The risk agent is the one that sees everything — it has to, to find what
    # the others' framing would let it miss.
    assert "[F1]" in seen["risk"] and "[T1]" in seen["risk"]


def test_the_evidence_block_carries_the_cache_breakpoint(wired):
    """
    Caching is a prefix match, so the shared block must come first and carry
    the breakpoint. The previous analyst put its breakpoint on a ~200-token
    system prompt, under the minimum cacheable prefix, and never got a hit.
    """
    captured = []
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses)
    original = client.messages.create

    async def capture(**kwargs):
        captured.append(kwargs["system"])
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    for system in captured:
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        assert system[0]["text"].startswith("EVIDENCE")
        assert "cache_control" not in system[1]


# ── Feature gate ──────────────────────────────────────────────────────────────

def test_disabled_returns_none_and_makes_no_calls(wired, monkeypatch):
    settings = D.get_settings()
    monkeypatch.setattr(settings, "research_agents_enabled", False, raising=False)

    client = FakeClient(_specialist_payloads() | {"synthesiser": _synthesis()})
    assert _run(client) is None
    assert client.started == []


# ── Empty-slice skip ──────────────────────────────────────────────────────────
# An agent whose slice holds no facts about the company is not worth calling.
# This is not an edge case on a cold cache: a real AVGO run with no fundamentals
# provider key sent the fundamentals agent exactly two items — "no historical
# range collected" and "no earnings history collected" — and paid Opus rates for
# a paragraph restating them.


def _no_fundamentals(monkeypatch):
    """Strip the fundamentals-side inputs, leaving technicals and news."""
    async def bare_fundamentals(_ticker):
        return {}

    async def no_statements(_ticker, timeframe="annual", limit=12):
        return []

    async def no_earnings(_ticker):
        return {}

    monkeypatch.setattr(D, "fetch_fundamentals", bare_fundamentals)
    monkeypatch.setattr(D, "fetch_statements", no_statements)
    monkeypatch.setattr(D, "fetch_earnings", no_earnings)


def test_an_agent_with_no_company_facts_is_not_called(wired, monkeypatch):
    _no_fundamentals(monkeypatch)
    client = FakeClient(_specialist_payloads() | {"synthesiser": _synthesis()})
    dossier = _run(client)

    assert dossier is not None
    assert "fundamentals" in dossier["agents_skipped"]
    assert "fundamentals" not in [name for name, _ in client.started]
    # The ones that do have evidence still run.
    assert "technical" in [name for name, _ in client.started]
    assert "news" in [name for name, _ in client.started]


def test_a_skip_is_not_reported_as_a_failure(wired, monkeypatch):
    """
    The two states mean different things to a reader: a failure says the
    dossier is incomplete, a skip says there is nothing there to assess.
    """
    _no_fundamentals(monkeypatch)
    dossier = _run(FakeClient(_specialist_payloads() | {"synthesiser": _synthesis()}))

    assert dossier["agents_failed"] == []
    assert dossier["agents_skipped"] == ["fundamentals"]
    assert dossier["agents"]["fundamentals"]["skipped"] is True
    assert dossier["agents"]["fundamentals"]["error"] is None
    assert dossier["agents"]["fundamentals"]["skip_reason"]


def test_a_failure_is_still_a_failure(wired):
    """The new state must not swallow the old one."""
    dossier = _run(FakeClient(_specialist_payloads() | {"synthesiser": _synthesis()},
                              fail={"news"}))
    assert dossier["agents_failed"] == ["news"]
    assert dossier["agents_skipped"] == []
    assert dossier["agents"]["news"]["skipped"] is False


def test_meta_evidence_still_reaches_the_agents_that_do_run(wired, monkeypatch):
    """
    Skipping decides who is *called*; it does not strip the ledger. An agent
    that runs still needs the "not available" lines — knowing the boundary of
    the evidence is what stops it reasoning past it.
    """
    _no_fundamentals(monkeypatch)
    seen = {}
    client = FakeClient(_specialist_payloads() | {"synthesiser": _synthesis()})
    original = client.messages.create

    async def capture(**kwargs):
        seen[FakeClient.identify(kwargs)] = kwargs["system"][0]["text"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    # The risk agent sees everything, including the declared absences.
    assert "Not available" in seen["risk"]


def test_the_synthesiser_is_told_a_skip_is_not_a_malfunction(wired, monkeypatch):
    _no_fundamentals(monkeypatch)
    briefs = {}
    client = FakeClient(_specialist_payloads() | {"synthesiser": _synthesis()})
    original = client.messages.create

    async def capture(**kwargs):
        name = FakeClient.identify(kwargs)
        if name == "synthesiser":
            briefs["task"] = kwargs["messages"][0]["content"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    task = briefs["task"]
    assert "NOT RUN" in task
    assert "unanswered rather than as neutral" in task
    assert "call failed" not in task


def test_a_ledger_of_only_declared_absences_builds_no_dossier(wired, monkeypatch):
    """
    Five "not available" lines must not clear the thin-evidence guard and then
    skip every agent underneath it — that is a dossier of nothing.
    """
    _no_fundamentals(monkeypatch)

    async def no_features(*_a, **_k):
        return None

    # Strip technicals and news too, leaving only the meta lines.
    empty_raw = {"ticker": "EXMP", "current_price": 120.0, "recent_headlines": [],
                 "sentiment_raw": {}, "macro": {}, "alternative_data": {}}
    db = _FakeDb()
    db._collections["stocks_raw"] = _FakeCollection(empty_raw)
    db._collections["stocks_features"] = _FakeCollection({"ticker": "EXMP"})

    async def fake_get_db():
        return db

    monkeypatch.setattr(D, "get_db", fake_get_db)
    client = FakeClient(_specialist_payloads() | {"synthesiser": _synthesis()})
    assert _run(client) is None
    assert client.started == []


# ── Synthesiser failure is not a silent null ──────────────────────────────────
# `report: null` on its own does not say whether there was nothing to
# synthesise or whether the merge call itself broke — the real production run
# hit exactly this (a schema 400 took out fundamentals, risk, AND the
# synthesiser at once) and the API response gave no indication which had
# happened, or that the synthesiser had failed at all.


def test_a_synthesiser_failure_is_recorded_with_a_reason(wired):
    """All four specialists succeed; only the merge call fails."""
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses, fail={"synthesiser"})
    dossier = _run(client)

    assert dossier["report"] is None
    assert dossier["synthesis_error"] == "synthesiser exploded"
    # The specialists themselves are unaffected — this is not a fan-out failure.
    assert dossier["agents_failed"] == []
    assert dossier["agents_skipped"] == []


def test_no_usable_specialist_output_gives_a_specific_reason(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses,
                              fail={"fundamentals", "technical", "news", "risk"}))

    assert dossier["report"] is None
    assert dossier["synthesis_error"] == "no specialist agent produced usable output"


def test_synthesis_error_is_absent_on_a_successful_report(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses))

    assert dossier["report"] is not None
    assert dossier["synthesis_error"] is None


def test_synthesis_error_reaches_the_api_model(wired):
    from app.routes.research import _to_model

    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses, fail={"synthesiser"}))
    payload = _to_model(dossier).model_dump()

    assert payload["report"] is None
    assert payload["synthesis_error"] == "synthesiser exploded"


# ── The prior record inside the orchestrator ──────────────────────────────────
# Memory enters as `O`-prefixed ledger evidence rather than as injected prose,
# so it is subject to every rule the rest of the module enforces. These tests
# pin the two properties that would fail silently: that the agents are actually
# shown it, and that it can never raise a conviction.

def _resolved_reading(alpha=-0.06, lesson=None, ticker="EXMP"):
    return {
        "ticker": ticker,
        "as_of": "2026-07-01T06:00:00+00:00",
        "outcome": {
            "assessment": "BULLISH", "research_conviction": 78.0,
            "horizon_days": 21, "return": 0.03, "benchmark_return": 0.09,
            "benchmark_ticker": "SPY", "alpha": alpha, "assessment_correct": False,
            "reflection": {"lesson": lesson} if lesson else None,
        },
    }


@pytest.fixture
def with_history(monkeypatch):
    """A settled prior reading of this name, plus one of another."""
    async def fake_resolved(_ticker):
        return [
            _resolved_reading(lesson="Margin durability [F2] rested on two periods."),
            _resolved_reading(ticker="OTHR", alpha=0.02),
        ]

    monkeypatch.setattr(D.prior_record, "load_resolved", fake_resolved)


def test_every_agent_is_shown_the_prior_record(wired, with_history):
    """
    The record is scoped to all four specialists and the synthesiser, unlike
    company evidence which is deliberately partitioned. A miss in how a name is
    read is not the fundamentals analyst's alone.
    """
    seen = {}
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses)
    original = client.messages.create

    async def capture(**kwargs):
        name = FakeClient.identify(kwargs)
        seen[name] = kwargs["system"][0]["text"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    for agent in ("fundamentals", "technical", "news", "risk", "synthesiser"):
        assert "[O1]" in seen[agent], f"{agent} was not shown the prior record"


def test_the_prior_record_carries_the_alpha_and_the_lesson(wired, with_history):
    seen = {}
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    client = FakeClient(responses)
    original = client.messages.create

    async def capture(**kwargs):
        seen[FakeClient.identify(kwargs)] = kwargs["system"][0]["text"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    block = seen["synthesiser"]
    assert "-6.0%" in block
    assert "wrong on alpha" in block
    assert "Margin durability [F2]" in block
    assert "[different company]" in block


def test_the_conviction_anchor_ignores_the_prior_record(wired, monkeypatch):
    """
    The single most important guarantee here. `derived_research_conviction` is
    arithmetic over company data; if the record could move it, memory would be
    able to manufacture a BUY rather than only temper one.

    The same company data is read twice — once with a run of badly wrong prior
    readings in the ledger, once with none — and the anchor must not move.
    """
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}

    async def no_history(_ticker):
        return []

    async def bad_history(_ticker):
        return [_resolved_reading(alpha=-0.30) for _ in range(5)]

    monkeypatch.setattr(D.prior_record, "load_resolved", no_history)
    without = _run(FakeClient(responses))

    monkeypatch.setattr(D.prior_record, "load_resolved", bad_history)
    with_record = _run(FakeClient(responses))

    assert with_record["coverage"]["prior_record"]["same_ticker"] == 5
    assert without["coverage"]["prior_record"]["same_ticker"] == 0
    assert (with_record["derived_research_conviction"]
            == without["derived_research_conviction"])


def test_a_lesson_cannot_push_conviction_past_the_anchor_band(wired, with_history):
    """
    A model told it was badly wrong last time may want to over-correct — in
    either direction. The clamp is what stops the record becoming a second,
    unaudited scoring input.
    """
    responses = _specialist_payloads() | {
        "synthesiser": _synthesis(
            conviction=99,
            conviction_rationale="The prior reading was badly wrong [O1].",
        )
    }
    dossier = _run(FakeClient(responses))
    anchor = dossier["derived_research_conviction"]
    assert abs(dossier["research_conviction"] - anchor) <= D._CONVICTION_BAND


def test_a_fabricated_prior_record_citation_is_stripped_like_any_other(wired):
    """
    No prior record exists in this run, so [O1] refers to nothing. It must be
    caught by the same audit that catches an invented [F99] — the record is
    evidence, not a privileged channel.
    """
    responses = _specialist_payloads() | {
        "synthesiser": _synthesis(
            thesis="We were wrong on this name before [O1].",
        )
    }
    dossier = _run(FakeClient(responses))
    assert "O1" in dossier["citation_audit"]["invented"]
    assert dossier["report"]["thesis"] is None


def test_a_name_with_only_a_track_record_still_fails_the_evidence_guard(monkeypatch):
    """
    `meta=True` keeps the record out of `substantive_count`. Without that, a
    ticker with eight settled readings and no financials would clear the guard
    and pay for four agents to read its own history back.
    """
    ledger = Ledger()
    added = D.prior_record.add_prior_record(
        ledger, "EXMP", [_resolved_reading() for _ in range(8)]
    )
    assert added["same_ticker"] == 8
    assert ledger.substantive_count() == 0


def test_no_history_leaves_the_ledger_exactly_as_it_was(wired):
    """The normal state for a name being read for the first time."""
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses))
    assert dossier["coverage"]["prior_record"] == {
        "same_ticker": 0, "cross_ticker": 0, "available": False,
    }
    assert not [e for e in dossier["evidence"] if e["id"].startswith("O")]


# ── The rebuttal round ────────────────────────────────────────────────────────
# One exchange, after both sides have already written independently. The
# property that makes this safe — and that the reference implementation gives
# up by having its bear react to a bull case from round one — is that neither
# side saw the other while forming its view.

@pytest.fixture
def debating(wired, monkeypatch):
    monkeypatch.setattr(D.get_settings(), "research_debate_rounds", 1, raising=False)
    return wired


def test_the_rebuttal_runs_after_both_sides_have_written(debating):
    """
    Ordering is the whole design. If either rebuttal started before the four
    specialists finished, one side would be arguing against a view the other
    had not yet formed, and the round would be the anchoring failure it exists
    to avoid.
    """
    client = FakeClient(_all_payloads())
    _run(client)

    finished = {name: t for name, t in client.finished}
    started = {name: t for name, t in client.started}
    last_specialist = max(finished[n] for n in
                          ("fundamentals", "technical", "news", "risk"))
    for side in ("risk_rebuttal", "defence_rebuttal"):
        assert started[side] >= last_specialist


def test_the_two_sides_run_concurrently_and_cannot_read_each_other(debating):
    """
    Letting either read the other's answer would collapse the round into a
    single voice agreeing with itself.
    """
    client = FakeClient(_all_payloads(), delay=0.05)
    _run(client)

    started = {name: t for name, t in client.started}
    finished = {name: t for name, t in client.finished}
    assert started["defence_rebuttal"] < finished["risk_rebuttal"]
    assert started["risk_rebuttal"] < finished["defence_rebuttal"]


def test_both_sides_argue_over_byte_identical_material(debating):
    """
    An asymmetry in what the two are shown would make the exchange a
    comparison of inputs rather than of arguments.
    """
    seen = {}
    client = FakeClient(_all_payloads())
    original = client.messages.create

    async def capture(**kwargs):
        name = FakeClient.identify(kwargs)
        if name.endswith("_rebuttal"):
            seen[name] = kwargs["messages"][0]["content"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    risk_brief = seen["risk_rebuttal"].split("THE BEAR CASE", 1)[1]
    defence_brief = seen["defence_rebuttal"].split("THE BEAR CASE", 1)[1]
    assert risk_brief == defence_brief


def test_the_synthesiser_is_shown_the_exchange(debating):
    seen = {}
    client = FakeClient(_all_payloads())
    original = client.messages.create

    async def capture(**kwargs):
        seen[FakeClient.identify(kwargs)] = kwargs["messages"][0]["content"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    brief = seen["synthesiser"]
    assert "THE REBUTTAL" in brief
    assert "Nothing in the evidence bounds the multiple [V1]" in brief


def test_the_exchange_is_citation_filtered_like_everything_else(debating):
    """
    The rebuttals are the one place a model is arguing rather than reporting,
    which is exactly where an unsupported assertion is most persuasive and
    least noticed.
    """
    payloads = _all_payloads()
    payloads["defence_rebuttal"] = {
        "answered": ["Margins are clearly fine",          # uncited — dropped
                     "Margin reversal [F2]"],             # cited — kept
        "conceded": ["The multiple is unbounded [V99]"],  # fabricated — dropped
        "overstated": [],
        "strongest_surviving_risk": "Multiple compression [V1]",
    }
    dossier = _run(FakeClient(payloads))

    defence = dossier["debate"]["defence_rebuttal"]
    assert defence["answered"] == ["Margin reversal [F2]"]
    assert defence["conceded"] == []
    assert defence["strongest_surviving_risk"] == "Multiple compression [V1]"


def test_rounds_zero_restores_the_previous_path_exactly(wired):
    """
    The escape hatch has to be real: a deployment that turns the round off must
    get the dossier it got before the round existed, not a degraded one.
    """
    client = FakeClient(_all_payloads())
    dossier = _run(client)

    assert dossier["debate"] is None
    called = {name for name, _ in client.started}
    assert "risk_rebuttal" not in called
    assert "defence_rebuttal" not in called


def test_a_failed_risk_agent_skips_the_round_rather_than_failing_the_dossier(debating):
    """A dossier without a rebuttal is a complete dossier."""
    client = FakeClient(_all_payloads(), fail=("risk",))
    dossier = _run(client)

    assert dossier["debate"] is None
    assert dossier["report"] is not None
    assert "risk" in dossier["agents_failed"]
    assert "risk_rebuttal" not in {name for name, _ in client.started}


def test_one_side_failing_still_leaves_a_usable_exchange(debating):
    client = FakeClient(_all_payloads(), fail=("defence_rebuttal",))
    dossier = _run(client)

    assert dossier["debate"] is not None
    assert dossier["debate"]["defence_rebuttal"] is None
    assert dossier["debate"]["risk_rebuttal"]["surviving"]


def test_both_sides_failing_reads_as_no_round_not_as_an_empty_one(debating):
    """
    A `debate` block full of nulls would read to the synthesiser as an argument
    that produced no answers, rather than as an argument that never happened.
    """
    dossier = _run(FakeClient(_all_payloads(),
                              fail=("risk_rebuttal", "defence_rebuttal")))
    assert dossier["debate"] is None
    assert dossier["report"] is not None


def test_the_rebuttal_runs_on_the_orchestrator_model(debating):
    """Judgement-heavy roles get the stronger model; this is one."""
    models = {}
    client = FakeClient(_all_payloads())
    original = client.messages.create

    async def capture(**kwargs):
        models[FakeClient.identify(kwargs)] = kwargs["model"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    settings = D.get_settings()
    assert models["risk_rebuttal"] == settings.research_orchestrator_model
    assert models["defence_rebuttal"] == settings.research_orchestrator_model


# ── The stance panel ──────────────────────────────────────────────────────────
# Three temperaments reading the trade rather than the company. The property
# worth defending is what they must NOT do: the reference implementation lets
# its portfolio-manager agent decide the position, and deterministic sizing is
# why the same inputs here produce the same order twice.

@pytest.fixture
def with_stances(wired, monkeypatch):
    monkeypatch.setattr(D.get_settings(), "research_stance_panel_enabled", True,
                        raising=False)
    return wired


def test_all_three_stances_run_and_are_stored(with_stances):
    dossier = _run(FakeClient(_all_payloads()))
    stances = dossier["stances"]
    assert stances["aggressive"]["stance"] == "SIZE_UP"
    assert stances["conservative"]["stance"] == "SIZE_DOWN"
    assert stances["neutral"]["stance"] == "HOLD_SIZE"


def test_the_three_run_concurrently(with_stances):
    """They are asked the same question independently; sequencing them would
    cost three round trips for no added information."""
    client = FakeClient(_all_payloads(), delay=0.05)
    _run(client)

    started = {n: t for n, t in client.started}
    finished = {n: t for n, t in client.finished}
    assert started["stance_conservative"] < finished["stance_aggressive"]
    assert started["stance_neutral"] < finished["stance_aggressive"]


def test_the_panel_runs_after_synthesis_and_reads_the_merged_report(with_stances):
    """
    They read a conclusion, not four unmerged reports — handing them the raw
    specialists would invite the re-analysis their prompts forbid.
    """
    seen = {}
    client = FakeClient(_all_payloads())
    original = client.messages.create

    async def capture(**kwargs):
        name = FakeClient.identify(kwargs)
        if name.startswith("stance_"):
            seen[name] = kwargs["messages"][0]["content"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)

    brief = seen["stance_aggressive"]
    assert "THE READING" in brief
    assert "Compounding at scale [F2]" in brief   # the synthesised thesis
    assert "THE RISK GATE" in brief


def test_the_panel_is_told_it_cannot_see_account_exposure(with_stances):
    """
    A dossier is shared across users, so the panel reads a name and not an
    account. Saying so in the brief is what stops a stance asserting something
    about exposure it was never given.
    """
    seen = {}
    client = FakeClient(_all_payloads())
    original = client.messages.create

    async def capture(**kwargs):
        name = FakeClient.identify(kwargs)
        if name.startswith("stance_"):
            seen[name] = kwargs["messages"][0]["content"]
        return await original(**kwargs)

    client.messages.create = capture
    _run(client)
    assert "not told how much of the account" in seen["stance_neutral"]


def test_an_uncited_rationale_is_stripped_but_the_stance_survives(with_stances):
    """
    The verdict is a closed enum, not a claim. Leaving it with a visible hole
    where the reasoning should be is the intended outcome — better than a
    recommendation nobody can check.
    """
    payloads = _all_payloads()
    payloads["stance_aggressive"] = {
        "stance": "SIZE_UP",
        "rationale": "This one just feels like a winner.",
        "what_would_change_it": "A change of heart",
    }
    dossier = _run(FakeClient(payloads))

    aggressive = dossier["stances"]["aggressive"]
    assert aggressive["stance"] == "SIZE_UP"
    assert aggressive["rationale"] is None


def test_one_stance_failing_leaves_the_other_two(with_stances):
    dossier = _run(FakeClient(_all_payloads(), fail=("stance_conservative",)))
    assert dossier["stances"]["conservative"] is None
    assert dossier["stances"]["aggressive"]["stance"] == "SIZE_UP"


def test_all_three_failing_reads_as_no_panel(with_stances):
    dossier = _run(FakeClient(
        _all_payloads(),
        fail=("stance_aggressive", "stance_conservative", "stance_neutral"),
    ))
    assert dossier["stances"] is None
    assert dossier["report"] is not None


def test_the_panel_is_skipped_when_there_is_no_report(with_stances):
    """With nothing synthesised there is no trade to have a stance about."""
    client = FakeClient(_all_payloads(), fail=("synthesiser",))
    dossier = _run(client)

    assert dossier["stances"] is None
    assert not [n for n, _ in client.started if n.startswith("stance_")]


def test_disabled_by_default_and_makes_no_calls(wired):
    client = FakeClient(_all_payloads())
    dossier = _run(client)

    assert dossier["stances"] is None
    assert not [n for n, _ in client.started if n.startswith("stance_")]


def test_the_stances_never_reach_the_trading_guard_chain():
    """
    The line this project does not cross. `_prepare_entry` holds every guard
    that can refuse or resize an order; if a stance could reach it, sizing
    would stop being reproducible from the account and the risk model alone.
    """
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "app/services/trade_manager.py"
    text = source.read_text()
    # Word-bounded: `isinstance` contains the substring and is everywhere.
    for token in (r"\bstances?\b", r"\bSIZE_UP\b", r"\bSIZE_DOWN\b",
                  r"\bHOLD_SIZE\b", r"research_stance"):
        assert not re.search(token, text), f"{token} reached the trading path"
