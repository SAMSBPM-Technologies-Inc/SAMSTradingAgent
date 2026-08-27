"""
Agent Orchestrator
──────────────────
Assembles the evidence, fans out four scoped agents, and merges what they
return into one dossier.

                    ┌──────────────────────┐
                    │  Agent Orchestrator  │
                    └──────────┬───────────┘
              ┌────────┬───────┴────┬─────────┐
              ▼        ▼            ▼         ▼
           ┌──────┐ ┌──────┐    ┌──────┐  ┌──────┐
           │ Fund │ │ Tech │    │ News │  │ Risk │   asyncio.gather
           └──┬───┘ └──┬───┘    └──┬───┘  └──┬───┘
              └────────┴─────┬─────┴─────────┘
                             ▼
                     ┌───────────────┐
                     │  Synthesiser  │
                     └───────┬───────┘
                             ▼
                     research_dossiers

What this replaces is a single call that was handed forty pre-computed numbers
and eight anonymous headlines and asked for institutional-grade research. The
decomposition buys three things that call could not have: each agent's output
is separately checkable, they run concurrently so four analyses cost about one
analysis in wall time, and the cheap descriptive work runs on a cheaper model
than the judgement.

Two rules hold the output honest, and both are enforced here rather than asked
for in a prompt. **Nothing uncited survives** — every sentence and every list
item is filtered against the ledger's ids before storage, so a confident
paragraph with no evidence behind it is removed rather than rendered with a
caveat. And **the synthesiser is a merge step, not a fifth source**: it may
only cite ids the ledger issued, and it must address or carry every risk the
risk agent raised.

The dossier is never required. A failed agent leaves its section absent, a
failed synthesis leaves a dossier of specialist findings, and the 5-minute
pipeline does not read any of this.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import get_settings
from app.db import COLL_DOSSIERS, COLL_FEATURES, COLL_RAW, get_db
from app.services.fundamentals import fetch_earnings, fetch_fundamentals, fetch_statements
from app.services.research import dimensions as dim
from app.services.research import earnings as earnings_evidence
from app.services.research import financials, market, profile, valuation
from app.services.research.agents import specs
from app.services.research.agents.base import AgentResult, AgentSpec, run_agent
from app.services.research.evidence import (
    Ledger,
    strip_uncited,
    strip_uncited_list,
    unknown_citations,
)
from app.services.risk_engine import assess_risk
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: How far the synthesiser may move conviction from the derived anchor. Wide
#: enough for judgement the arithmetic cannot express, narrow enough that the
#: headline number stays tethered to something reproducible.
_CONVICTION_BAND = 15.0


async def build_dossier(ticker: str, user_id: Optional[str] = None,
                        watchlist: Optional[list[dict]] = None,
                        client: Any = None) -> Optional[dict]:
    """
    Produce and persist a research dossier for *ticker*.

    Returns None when the feature is off, the key is missing, or there is not
    enough underlying data to assemble an evidence ledger worth running agents
    over. Returning None rather than an empty dossier is deliberate: an empty
    report is indistinguishable from a bad one at a glance.

    `client` is injectable so the orchestration — fan-out, failure handling,
    citation filtering, conviction clamping — can be tested without a network
    call or a monkeypatched SDK module. Those behaviours are the point of this
    module and were untestable in the analyst call this replaces, which built
    its client inline.
    """
    settings = get_settings()
    if not settings.research_agents_enabled:
        logger.info("research_disabled", ticker=ticker)
        return None
    if client is None and not settings.anthropic_api_key:
        logger.warning("research_no_api_key", ticker=ticker)
        return None

    ticker = ticker.upper()
    context = await _load_context(ticker)
    if not context:
        logger.warning("research_insufficient_data", ticker=ticker)
        return None

    ledger, scores, summary = _assemble(ticker, context, watchlist)
    if ledger.substantive_count() < 5:
        # Counts facts about the company, not the "not available" lines. A
        # ledger of five declared absences would otherwise clear this guard and
        # then skip every agent underneath it.
        logger.warning("research_thin_evidence", ticker=ticker,
                       facts=ledger.substantive_count(), total=len(ledger))
        return None

    if client is None:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    results = await _fan_out(client, ledger, settings)
    synthesis, synthesis_error = await _synthesise(client, ledger, results, scores, settings)

    dossier = _compose(ticker, ledger, scores, summary, results, synthesis, synthesis_error)
    await _persist(dossier)
    return dossier


# ── Evidence assembly ─────────────────────────────────────────────────────────

async def _load_context(ticker: str) -> Optional[dict]:
    """Gather every stored input. Cache-only — nothing here calls a provider."""
    try:
        db = await get_db()
        features = await db[COLL_FEATURES].find_one({"ticker": ticker}, {"_id": 0})
        raw = await db[COLL_RAW].find_one({"ticker": ticker}, {"_id": 0})
    except Exception as exc:
        logger.warning("research_context_read_failed", ticker=ticker, error=str(exc))
        return None

    if not features or not raw:
        return None

    fundamentals = await fetch_fundamentals(ticker)
    return {
        "features": features,
        "raw": raw,
        "fundamentals": fundamentals if fundamentals.get("source") != "pending" else {},
        "annual": await fetch_statements(ticker, "annual", limit=12),
        "quarterly": await fetch_statements(ticker, "quarterly", limit=8),
        "earnings": await fetch_earnings(ticker),
    }


def _assemble(ticker: str, context: dict,
              watchlist: Optional[list[dict]]) -> tuple[Ledger, list[dim.Dimension], dict]:
    """Build the ledger and the deterministic dimension scores."""
    features = context["features"]
    raw = context["raw"]
    fundamentals = context["fundamentals"]
    annual = context["annual"]
    price = features.get("current_price") or raw.get("current_price")

    ledger = Ledger()
    summary: dict = {}
    summary["profile"] = profile.build(ledger, ticker, fundamentals, watchlist)
    summary["financials"] = financials.build(ledger, fundamentals, annual,
                                             context["quarterly"])
    summary["valuation"] = valuation.build(ledger, fundamentals, annual, price)
    summary["earnings"] = earnings_evidence.build(ledger, context["earnings"],
                                                  fundamentals)

    risk_assessment = assess_risk(features)
    summary["technical"] = market.build_technical(ledger, features, raw, risk_assessment)
    summary["news"] = market.build_news(ledger, raw)
    market.build_macro(ledger, raw)
    market.build_alternative(ledger, raw)

    fcf_yield = _fcf_yield(fundamentals, annual)
    scores = dim.build_all(fundamentals, annual, features, risk_assessment, fcf_yield)
    return ledger, scores, summary


def _fcf_yield(fundamentals: dict, annual: list[dict]) -> Optional[float]:
    market_cap = fundamentals.get("market_cap")
    if not market_cap or market_cap <= 0:
        return None
    cash_flow = None
    if annual and annual[0].get("free_cash_flow") is not None:
        cash_flow = annual[0]["free_cash_flow"]
    elif fundamentals.get("free_cash_flow") is not None:
        cash_flow = fundamentals["free_cash_flow"]
    return None if cash_flow is None else cash_flow / market_cap


# ── Fan-out ───────────────────────────────────────────────────────────────────

async def _fan_out(client: Any, ledger: Ledger, settings) -> dict[str, AgentResult]:
    """
    Run the four specialists concurrently.

    `return_exceptions=True` is what makes one agent's failure survivable: a
    raise inside `gather` would otherwise cancel its siblings, and losing four
    analyses because the news agent timed out is the wrong trade.
    """
    results: dict[str, AgentResult] = {}

    # Skip an agent whose slice holds no facts about the company. Its meta
    # items — "no earnings history collected", "13F not available" — are real
    # and stay in the ledger, but they are statements about our data, and
    # spending a model call to have one paraphrased back is waste. On a cold
    # ticker this is not the edge case: an AVGO dossier with no fundamentals
    # provider key sent the fundamentals agent exactly two items, both of them
    # "not available", and paid full price for the paragraph that came back.
    runnable = []
    for spec in specs.SPECIALISTS:
        if ledger.substantive_count(spec.prefixes) == 0:
            reason = "no evidence collected in this area"
            logger.info("research_agent_skipped", agent=spec.name, reason=reason)
            results[spec.name] = AgentResult(
                name=spec.name, output=None, skipped=True, skip_reason=reason
            )
            continue
        runnable.append(spec)

    if not runnable:
        return results

    tasks = [
        run_agent(
            client,
            spec,
            _evidence_block(ledger, spec),
            _model_for(spec, settings),
            settings.research_effort,
            settings.research_extended_thinking,
        )
        for spec in runnable
    ]
    settled = await asyncio.gather(*tasks, return_exceptions=True)

    for spec, outcome in zip(runnable, settled):
        if isinstance(outcome, BaseException):
            logger.warning("research_agent_raised", agent=spec.name, error=str(outcome))
            results[spec.name] = AgentResult(name=spec.name, output=None,
                                             error=str(outcome))
        else:
            results[spec.name] = outcome
    return results


def _model_for(spec: AgentSpec, settings) -> str:
    if spec.model_role == "orchestrator":
        return settings.research_orchestrator_model
    return settings.research_specialist_model


def _evidence_block(ledger: Ledger, spec: AgentSpec) -> str:
    return (
        "EVIDENCE — every id below is citable. Nothing outside this block is.\n\n"
        + ledger.render(spec.prefixes)
    )


# ── Synthesis ─────────────────────────────────────────────────────────────────

async def _synthesise(client: Any, ledger: Ledger, results: dict[str, AgentResult],
                      scores: list[dim.Dimension],
                      settings) -> tuple[Optional[dict], Optional[str]]:
    """
    Merge the specialists.

    Returns `(output, error)` rather than collapsing every failure to a bare
    `None` — that is exactly what let the real bug this module first shipped
    with hide. All four specialists failing loudly (agents_failed) but the
    synthesiser also failing and reporting nothing produced a dossier whose API
    response had `report: null` and no field anywhere saying why. `error` is
    always populated when `output` is None, so the caller — and the stored
    document — can distinguish "nothing to synthesise" from "the call itself
    broke", which is the same distinction `AgentResult.skipped` draws for the
    specialists.
    """
    usable = {name: r.output for name, r in results.items() if r.ok}
    if not usable:
        reason = "no specialist agent produced usable output"
        logger.warning("research_no_agent_output")
        return None, reason

    anchor = dim.derived_conviction(scores)
    spec = AgentSpec(
        name="synthesiser",
        prefixes=tuple("PFVETNAM"),
        system_prompt=specs.SYNTHESISER_SYSTEM,
        task=_synthesis_task(usable, results, scores, anchor),
        schema=specs.SYNTHESISER_SCHEMA,
        model_role="orchestrator",
    )
    result = await run_agent(
        client, spec, _evidence_block(ledger, spec),
        settings.research_orchestrator_model,
        settings.research_effort, settings.research_extended_thinking,
    )
    if not result.ok:
        return None, result.error or "synthesis call failed"

    output = dict(result.output or {})
    output["_usage"] = {
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cache_read_tokens": result.cache_read_tokens,
    }
    output["_derived_conviction"] = anchor
    return output, None


def _synthesis_task(usable: dict[str, dict], results: dict[str, AgentResult],
                    scores: list[dim.Dimension], anchor: Optional[float]) -> str:
    """The merge brief: the specialists' reports, the scores, and the anchor."""
    parts = ["ANALYST REPORTS\n"]
    for name in ("fundamentals", "technical", "news", "risk"):
        report = usable.get(name)
        if report is None:
            # Named rather than omitted. A synthesiser that cannot see a gap
            # will write around it as though the ground were covered — and the
            # two kinds of gap call for different handling, so they are
            # labelled differently rather than both reading as a malfunction.
            result = results.get(name)
            if result is not None and result.skipped:
                parts.append(
                    f"\n## {name} — NOT RUN: {result.skip_reason}. No data was "
                    f"collected in this area, so treat every question it would "
                    f"have answered as unanswered rather than as neutral.\n"
                )
            else:
                parts.append(f"\n## {name} — DID NOT REPORT (call failed; "
                             f"treat as an open gap)\n")
            continue
        parts.append(f"\n## {name}\n{json.dumps(report, indent=2)}\n")

    parts.append("\nDIMENSION SCORES (0-100, computed from the evidence — "
                 "higher is better on all six, including risk, where higher "
                 "means safer)\n")
    for score in scores:
        payload = score.to_dict()
        if payload["score"] is None and not payload["model_judged"]:
            parts.append(f"- {payload['label']}: not scorable from available data\n")
        elif payload["model_judged"]:
            parts.append(f"- {payload['label']}: judged by the fundamentals "
                         f"analyst, not computed\n")
        else:
            thin = " (THIN — few inputs, treat with caution)" if payload["thin"] else ""
            parts.append(f"- {payload['label']}: {payload['score']}{thin}\n")

    if anchor is not None:
        parts.append(
            f"\nDERIVED CONVICTION ANCHOR: {anchor:.0f}/100. Stay within "
            f"{_CONVICTION_BAND:.0f} points of it, and explain any departure in "
            f"conviction_rationale.\n"
        )
    else:
        parts.append("\nNo conviction anchor could be derived — too little "
                     "scored data. Score conviction conservatively.\n")

    parts.append(
        "\nProduce the merged report. Every item in the risk analyst's "
        "key_risks must appear in either your key_risks or your risks_addressed."
    )
    return "".join(parts)


# ── Composition ───────────────────────────────────────────────────────────────

def _compose(ticker: str, ledger: Ledger, scores: list[dim.Dimension],
             summary: dict, results: dict[str, AgentResult],
             synthesis: Optional[dict],
             synthesis_error: Optional[str] = None) -> dict:
    """
    Assemble the stored document, dropping every unsupported claim on the way.

    The specialists' raw output is kept alongside the filtered report, so a
    reading that looks wrong can be traced to the agent that made it rather
    than to "the model".
    """
    valid = ledger.ids()
    scored = _apply_business_quality(scores, results.get("fundamentals"))
    report, citation_audit = (
        _filter_report(synthesis, valid) if synthesis else (None, None)
    )

    conviction = None
    if report:
        conviction = _bounded_conviction(
            report.get("conviction"), synthesis.get("_derived_conviction")
        )
        report["conviction"] = conviction

    generated_at = datetime.now(tz=timezone.utc)
    return {
        "ticker": ticker,
        "as_of": generated_at.isoformat(),
        "generated_at": generated_at,
        "report": report,
        "conviction": conviction,
        "derived_conviction": (synthesis or {}).get("_derived_conviction"),
        #: What the citation filter actually did to this report — a count of
        #: dropped items per field, and any id the model cited that the ledger
        #: never issued. None when there was no synthesis to filter. This is
        #: the only way to verify the enforcement mechanism did something on a
        #: given dossier, rather than trusting that clean-looking prose means
        #: nothing was caught.
        "citation_audit": citation_audit,
        "dimensions": [s.to_dict() for s in scored],
        "evidence": ledger.to_list(),
        "evidence_count": len(ledger),
        "coverage": summary,
        "agents": {
            name: {
                "ok": result.ok,
                "error": result.error,
                "skipped": result.skipped,
                "skip_reason": result.skip_reason,
                "output": result.output,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            }
            for name, result in results.items()
        },
        "agents_failed": [name for name, r in results.items() if r.failed],
        "agents_skipped": [name for name, r in results.items() if r.skipped],
        #: Populated whenever `report` is null so a reader — and the API
        #: response — can tell "nothing to synthesise" from "the merge call
        #: itself broke" instead of both reading as an unexplained gap.
        "synthesis_error": synthesis_error if report is None else None,
        "data_gaps": _collect_gaps(results),
    }


def _apply_business_quality(scores: list[dim.Dimension],
                            fundamentals_result: Optional[AgentResult]
                            ) -> list[dim.Dimension]:
    """
    Fill the one model-judged dimension, if the agent that owns it reported.

    Left unscored otherwise. A placeholder 50 would render in the UI as a real
    reading of a mediocre business, which is a different claim from "we did not
    assess this".
    """
    if not fundamentals_result or not fundamentals_result.ok:
        return scores
    output = fundamentals_result.output or {}
    raw = output.get("business_quality_score")
    if raw is None:
        return scores
    try:
        value = max(0.0, min(100.0, float(raw)))
    except (TypeError, ValueError):
        return scores

    for score in scores:
        if score.key == "business_quality":
            score.score = value
            score.coverage = 1.0
            score.note = output.get("business_quality_rationale") or score.note
    return scores


def _filter_report(synthesis: dict, valid: set[str]) -> tuple[dict, dict]:
    """
    Strip everything the ledger cannot support, and say what was stripped.

    Prose fields lose their uncited sentences; list fields lose their uncited
    items whole, because half a risk is not a smaller risk but a different one.
    `conclusion` and `conviction_rationale` are deliberately exempt: they are
    summaries of cited material rather than new claims, and requiring a
    citation in a closing sentence produces citation noise rather than rigour.

    Returns `(report, audit)` rather than folding the audit into the report
    dict. It used to be folded in, under `_`-prefixed keys — which meant the
    one piece of evidence that the citation mechanism actually did anything on
    a given dossier was computed, logged, and then discarded on the way out:
    `ResearchReport` has no `_dropped_uncited` field, so Pydantic silently
    dropped it at the API boundary. Nothing short of reading the log line or
    the raw Mongo document could tell whether a report full of citations had
    been checked at all. `audit` is returned separately so the caller can
    store and expose it as a first-class field instead.
    """
    prose = ("thesis", "bull_case", "bear_case", "what_the_market_is_missing")
    lists = ("key_catalysts", "key_risks", "risks_addressed",
             "what_would_change_my_opinion")

    report: dict = {}
    dropped: dict[str, int] = {}
    invented: set[str] = set()

    for field in prose:
        original = synthesis.get(field)
        invented |= unknown_citations(original, valid)
        kept = strip_uncited(original, valid)
        report[field] = kept
        if original and not kept:
            dropped[field] = 1

    for field in lists:
        original = synthesis.get(field) or []
        for item in original:
            invented |= unknown_citations(str(item), valid)
        kept = strip_uncited_list(original, valid)
        report[field] = kept
        if len(original) != len(kept):
            dropped[field] = len(original) - len(kept)

    report["assessment"] = synthesis.get("assessment")
    report["conviction"] = synthesis.get("conviction")
    report["conclusion"] = synthesis.get("conclusion")
    report["conviction_rationale"] = synthesis.get("conviction_rationale")

    if dropped or invented:
        logger.warning("research_uncited_claims_dropped",
                       dropped=dropped, invented=sorted(invented))
    audit = {"dropped": dropped, "invented": sorted(invented)}
    return report, audit


def _bounded_conviction(value: Any, anchor: Optional[float]) -> Optional[float]:
    """Clamp the model's conviction to the band around the derived anchor."""
    try:
        conviction = max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return anchor
    if anchor is None:
        return round(conviction, 1)
    low, high = anchor - _CONVICTION_BAND, anchor + _CONVICTION_BAND
    clamped = max(low, min(high, conviction))
    if clamped != conviction:
        logger.info("research_conviction_clamped",
                    model_value=conviction, anchor=anchor, applied=clamped)
    return round(max(0.0, min(100.0, clamped)), 1)


def _collect_gaps(results: dict[str, AgentResult]) -> list[str]:
    """Every data gap the agents named, de-duplicated, in report order."""
    gaps: list[str] = []
    for result in results.values():
        for gap in (result.output or {}).get("data_gaps") or []:
            text = str(gap).strip()
            if text and text not in gaps:
                gaps.append(text)
    return gaps


# ── Persistence ───────────────────────────────────────────────────────────────

async def _persist(dossier: dict) -> None:
    try:
        db = await get_db()
        await db[COLL_DOSSIERS].insert_one(dict(dossier))
        dossier.pop("_id", None)
    except Exception as exc:
        logger.warning("research_dossier_write_failed",
                       ticker=dossier.get("ticker"), error=str(exc))


async def latest_dossier(ticker: str) -> Optional[dict]:
    """
    The most recent dossier for *ticker*, with a staleness flag.

    Served past its TTL rather than withheld — a day-old business assessment is
    still a business assessment — but flagged, because the veto and the UI both
    need to treat "old" differently from "current".
    """
    ticker = ticker.upper()
    try:
        db = await get_db()
        docs = await (
            db[COLL_DOSSIERS]
            .find({"ticker": ticker}, {"_id": 0})
            .sort("as_of", -1)
            .limit(1)
            .to_list(length=1)
        )
    except Exception as exc:
        logger.warning("research_dossier_read_failed", ticker=ticker, error=str(exc))
        return None

    if not docs:
        return None
    doc = docs[0]
    doc["age_hours"] = _age_hours(doc.get("as_of"))
    doc["stale"] = doc["age_hours"] > get_settings().research_dossier_ttl_hours
    return doc


def _age_hours(as_of: Any) -> float:
    if not as_of:
        return 1e9
    try:
        stamp = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 1e9
    return (datetime.now(tz=timezone.utc) - stamp).total_seconds() / 3600.0
