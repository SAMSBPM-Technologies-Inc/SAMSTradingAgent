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
    assert "F999" in dossier["report"]["_invented_citations"]


def test_uncited_list_items_are_dropped_whole(wired):
    responses = _specialist_payloads() | {
        "synthesiser": _synthesis(
            key_risks=["Multiple compression [V1]", "A general sense of unease"]
        )
    }
    dossier = _run(FakeClient(responses))

    assert dossier["report"]["key_risks"] == ["Multiple compression [V1]"]
    assert dossier["report"]["_dropped_uncited"]["key_risks"] == 1


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

    anchor = dossier["derived_conviction"]
    assert anchor is not None
    assert dossier["conviction"] <= anchor + 15 + 1e-6
    assert dossier["conviction"] < 99


def test_conviction_within_the_band_is_left_alone(wired):
    responses = _specialist_payloads() | {"synthesiser": _synthesis()}
    dossier = _run(FakeClient(responses))
    anchor = dossier["derived_conviction"]
    assert abs(dossier["conviction"] - 70) < 1e-6 or abs(dossier["conviction"] - anchor) <= 15


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
