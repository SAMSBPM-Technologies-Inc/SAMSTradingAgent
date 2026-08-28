"""
Dossier Outcomes — closing the loop
───────────────────────────────────
A dossier said something about a company. This module goes back later and asks
what happened.

Until now nothing did. `research_dossiers` was written as a retained series and
read one document at a time, newest first; no reading was ever compared to a
result, so no agent has been told it was wrong about a name, and
`RESEARCH_VETO_MIN_CONVICTION = 35` sits exactly where `BUY_THRESHOLD = 0.70`
sat before `calibration.py` existed — at a number somebody guessed.

Two things come out of that comparison, and they are used differently.

**The numbers** — forward return, benchmark return, alpha, whether the
assessment pointed the right way — are arithmetic, checkable, and what the
research calibration arm reads. They are the part that can be regression
tested.

**The lesson** is one cheap model call, and it is deliberately constrained to
the dossier's own evidence. A reflection that may say anything would put
unattributable prose into the next dossier's prompt, and the entire research
module is built on the opposite rule. So the reflection is shown the reading
and the outcome, and every claim it makes must cite an id from the ledger that
reading was built on — `unknown_citations` checks that against the ledger
stored with the document, and a lesson that cites nothing is dropped. The
numbers still stand on their own; the prose is the optional part.

**Assessment correctness is judged on alpha, not on return.** BULLISH on a name
that rose 4% in a market that rose 9% was not right. This is why Phase 1 had to
land first: settled against raw return, the loop would have taught the agents
to prefer beta, which is precisely the failure mode the benchmark work exists
to expose.

NEUTRAL is scored `None`, not scored as a miss — the same handling `was_correct`
gives HOLD in `stocks_signal_history`. A reading that declined to take a side
cannot be graded by direction, and grading it anyway would reward whichever
side the sample happened to favour.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.config import get_settings
from app.db import COLL_DOSSIERS, get_db
from app.services.benchmark import (
    alpha as compute_alpha,
    benchmark_closes,
    benchmark_ticker,
    close_on_or_before,
)
from app.services.price_providers import fetch_price_history
from app.services.research.agents.base import AgentSpec, run_agent
from app.services.research.evidence import cited_ids, unknown_citations
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: How many dossiers one settlement pass will resolve. The reflection is a
#: model call each, and the job runs daily against a watchlist — a cap keeps a
#: backlog from turning into one very expensive morning.
_MAX_PER_PASS = 40

#: Enough history to price a dossier's opening day and today. Matches the
#: benchmark series so the two windows are read from comparable spans.
_PRICE_DAYS = 400


REFLECTION_SYSTEM = """You are reviewing a research dossier this desk produced, \
now that the outcome is known.

You are not re-analysing the company and you have no new information about it. \
You have the reading that was written, the evidence it was written from, and \
what the position did afterwards. The only question is what that comparison \
teaches.

Judge the call on alpha, not on the raw return. A bullish reading of a name \
that rose 4% while the market rose 9% was not right, and recording it as a win \
is how a desk convinces itself it has skill when it has exposure.

Write for the analyst who reads this name next. What you produce is injected \
into future dossiers as evidence, which means two things: it must be short, \
and every claim in it must cite an evidence id from the ledger below in square \
brackets, exactly as the id appears. A sentence citing nothing is deleted \
before storage, and a sentence citing an id the ledger never issued is deleted \
and recorded as a fabrication. This is the same rule the dossier itself is \
filtered under.

Be specific about mechanism. "The thesis was too optimistic" teaches nothing. \
"Margin expansion [F7] was read as durable when only two periods supported it \
[F4]" teaches the next reader where to look.

If the evidence does not let you say why the call went the way it did, say so \
plainly and cite the item that shows the gap. An honest "the record does not \
explain this" is worth more than a plausible story."""


REFLECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "lesson": {"type": "string"},
        "what_held": {"type": "array", "items": {"type": "string"}},
        "what_failed": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["lesson", "what_held", "what_failed"],
    "additionalProperties": False,
}


def assessment_correct(assessment: Optional[str],
                       excess: Optional[float]) -> Optional[bool]:
    """
    Did the reading point the right way, measured against the benchmark?

    None for NEUTRAL and for an unmeasurable window — both are "cannot say",
    and the caller must not collapse them into False. A miss and an ungraded
    reading look identical in an average and mean opposite things.
    """
    if excess is None or not assessment:
        return None
    verdict = str(assessment).upper()
    if verdict == "BULLISH":
        return excess > 0
    if verdict == "BEARISH":
        return excess < 0
    return None


def _as_of(doc: dict) -> Optional[datetime]:
    raw = doc.get("generated_at") or doc.get("as_of")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _price_at(series, when: datetime) -> Optional[float]:
    return close_on_or_before(series, when) if series is not None else None


def measure(doc: dict, price_series, bench_series,
            settled_at: datetime) -> Optional[dict]:
    """
    The arithmetic half: what the name did after this dossier was written.

    Returns None when the window cannot be priced at all. A partially priced
    outcome — a return with no benchmark — is returned with `alpha: None`
    rather than withheld, because the return is still a fact and the caller
    reports the two on separate denominators.
    """
    opened = _as_of(doc)
    if opened is None:
        return None

    open_price = _price_at(price_series, opened)
    close_price = _price_at(price_series, settled_at)
    if not open_price or not close_price:
        return None

    ret = (close_price - open_price) / open_price

    bench_ret = None
    bench_open = _price_at(bench_series, opened)
    bench_close = _price_at(bench_series, settled_at)
    if bench_open and bench_close:
        bench_ret = (bench_close - bench_open) / bench_open

    excess = compute_alpha(ret, bench_ret)
    report = doc.get("report") or {}
    assessment = report.get("assessment")

    return {
        "settled_at": settled_at,
        "horizon_days": max(1, (settled_at - opened).days),
        "price_at_dossier": round(open_price, 4),
        "price_at_settlement": round(close_price, 4),
        "return": round(ret, 6),
        "benchmark_ticker": benchmark_ticker(),
        "benchmark_return": round(bench_ret, 6) if bench_ret is not None else None,
        "alpha": round(excess, 6) if excess is not None else None,
        "assessment": assessment,
        "research_conviction": doc.get("research_conviction"),
        "assessment_correct": assessment_correct(assessment, excess),
    }


def _reflection_task(doc: dict, measured: dict) -> str:
    report = doc.get("report") or {}
    lines = [
        "THE READING (written {}):".format(doc.get("as_of")),
        f"  assessment: {report.get('assessment')}",
        f"  research conviction: {doc.get('research_conviction')}/100",
        f"  thesis: {report.get('thesis') or '(none recorded)'}",
        f"  bear case: {report.get('bear_case') or '(none recorded)'}",
    ]
    invalidators = report.get("what_would_change_my_opinion") or []
    if invalidators:
        lines.append("  stated invalidation conditions:")
        lines.extend(f"    - {item}" for item in invalidators[:6])

    bench = measured.get("benchmark_return")
    excess = measured.get("alpha")
    lines += [
        "",
        f"WHAT HAPPENED over the following {measured['horizon_days']} days:",
        f"  the name returned {measured['return']:+.2%}",
        (f"  {measured['benchmark_ticker']} returned {bench:+.2%}"
         if bench is not None else
         "  the benchmark could not be read for this window"),
        (f"  alpha: {excess:+.2%}" if excess is not None else
         "  alpha: unmeasurable — judge on the raw return and say so"),
        (f"  by that measure the assessment was "
         f"{'right' if measured['assessment_correct'] else 'wrong'}"
         if measured["assessment_correct"] is not None else
         "  the assessment was NEUTRAL or ungradeable — do not force a verdict"),
        "",
        "Write the lesson. Cite evidence ids from the ledger below.",
    ]
    return "\n".join(lines)


def _evidence_block(doc: dict) -> tuple[str, set[str]]:
    """
    The ledger this dossier was built from, as the reflection's citable set.

    Rendered from the stored document rather than rebuilt: the reflection is
    reviewing what was known *then*, and re-assembling the ledger today would
    show it facts the original reading never had.
    """
    items = doc.get("evidence") or []
    valid = {str(i.get("id")) for i in items if i.get("id")}
    if not items:
        return "(no evidence recorded with this dossier)", valid

    rendered = []
    for item in items:
        head = f"[{item.get('id')}] {item.get('claim')}: {item.get('value')}"
        provenance = [p for p in (item.get("source"), item.get("as_of")) if p]
        if provenance:
            head += f" ({' — '.join(provenance)})"
        rendered.append(head)
    block = ("EVIDENCE — the ledger this reading was built from. Every id below "
             "is citable. Nothing outside this block is.\n\n" + "\n".join(rendered))
    return block, valid


async def reflect(client: Any, doc: dict, measured: dict,
                  settings) -> Optional[dict]:
    """
    The written half. Returns None when the call fails or nothing survives
    filtering — the numbers stand on their own and the caller stores them
    either way.
    """
    block, valid = _evidence_block(doc)
    spec = AgentSpec(
        name="reflection",
        prefixes=(),
        system_prompt=REFLECTION_SYSTEM,
        task=_reflection_task(doc, measured),
        schema=REFLECTION_SCHEMA,
        model_role="specialist",
    )
    result = await run_agent(
        client, spec, block,
        settings.research_specialist_model,
        settings.research_effort,
        settings.research_extended_thinking,
    )
    if not result.ok:
        logger.warning("research_reflection_failed",
                       ticker=doc.get("ticker"), error=result.error)
        return None

    output = result.output or {}
    lesson = str(output.get("lesson") or "").strip()
    fabricated = sorted(unknown_citations(lesson, valid))
    supported = bool(cited_ids(lesson) & valid)

    if not supported:
        # Same rule the report is filtered under, applied to the one piece of
        # prose that would otherwise be injected into future prompts unchecked.
        logger.info("research_reflection_uncited", ticker=doc.get("ticker"),
                    fabricated=fabricated)
        return {"lesson": None, "uncited": True, "fabricated_citations": fabricated}

    def _kept(items: Any) -> list[str]:
        return [str(i).strip() for i in (items or [])
                if str(i).strip() and (cited_ids(str(i)) & valid)]

    return {
        "lesson": lesson,
        "what_held": _kept(output.get("what_held")),
        "what_failed": _kept(output.get("what_failed")),
        "uncited": False,
        "fabricated_citations": fabricated,
        "model": settings.research_specialist_model,
    }


async def settle_dossiers(client: Any = None, limit: int = _MAX_PER_PASS) -> dict:
    """
    Resolve every dossier old enough to have an outcome and not yet settled.

    Failures are per-dossier and swallowed, like the daily refresh job: one
    ticker whose price series cannot be read must not stop the rest, and an
    unsettled dossier is simply one the next pass picks up.
    """
    settings = get_settings()
    summary = {"examined": 0, "measured": 0, "reflected": 0, "skipped": 0}

    if not settings.research_agents_enabled:
        logger.info("research_outcomes_disabled")
        return summary

    horizon = int(settings.research_outcome_horizon_days)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=horizon)

    try:
        db = await get_db()
        pending = await db[COLL_DOSSIERS].find({
            "generated_at": {"$lte": cutoff},
            "outcome": None,
            "report": {"$ne": None},
        }).sort("generated_at", 1).limit(limit).to_list(length=limit)
    except Exception as exc:
        logger.warning("research_outcomes_read_failed", error=str(exc))
        return summary

    if not pending:
        logger.debug("research_outcomes_nothing_to_settle")
        return summary

    summary["examined"] = len(pending)
    settled_at = datetime.now(tz=timezone.utc)
    bench_series = await benchmark_closes()

    if client is None and settings.anthropic_api_key:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # One price series per ticker, reused across every dossier for that name.
    price_cache: dict[str, Any] = {}

    for doc in pending:
        ticker = str(doc.get("ticker") or "").upper()
        try:
            if ticker not in price_cache:
                try:
                    frame = await fetch_price_history(ticker, _PRICE_DAYS)
                    price_cache[ticker] = (
                        frame["Close"].dropna().sort_index()
                        if frame is not None and not frame.empty
                        and "Close" in frame.columns else None
                    )
                except Exception as exc:
                    logger.warning("research_outcome_price_failed",
                                   ticker=ticker, error=str(exc))
                    price_cache[ticker] = None

            measured = measure(doc, price_cache[ticker], bench_series, settled_at)
            if measured is None:
                summary["skipped"] += 1
                continue

            reflection = None
            if client is not None:
                reflection = await reflect(client, doc, measured, settings)
                if reflection and reflection.get("lesson"):
                    summary["reflected"] += 1

            outcome = dict(measured)
            outcome["reflection"] = reflection
            await db[COLL_DOSSIERS].update_one(
                {"_id": doc["_id"]}, {"$set": {"outcome": outcome}}
            )
            summary["measured"] += 1
            logger.info(
                "research_outcome_settled",
                ticker=ticker, ret=measured["return"], alpha=measured["alpha"],
                correct=measured["assessment_correct"],
            )
        except Exception as exc:
            logger.warning("research_outcome_failed", ticker=ticker, error=str(exc))
            summary["skipped"] += 1

    logger.info("research_outcomes_done", **summary)
    return summary
