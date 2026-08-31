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
from app.db import COLL_DOSSIERS, COLL_FEATURES, COLL_RAW, COLL_USERS, get_db
from app.services.fundamentals import fetch_earnings, fetch_fundamentals, fetch_statements
from app.services.prediction_markets import fetch_macro_markets
from app.services.social import fetch_social
from app.services.research import dimensions as dim
from app.services.research import earnings as earnings_evidence
from app.services.research import (
    financials, market, prediction, prior_record, profile, valuation,
)
from app.services.research import social as social_evidence
from app.services.research.agents import specs
from app.services.research.agents.base import AgentResult, AgentSpec, run_agent
from app.services.research.evidence import (
    Ledger,
    strip_uncited,
    strip_uncited_list,
    unknown_citations,
)
from app.services.risk_engine import RISK_MAX_FOR_BUY, assess_risk
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

    # The chain is resolved once, here, and threaded down — rather than each
    # agent resolving its own. Decrypting the same keys five to seven times per
    # dossier is waste, and a chain that changed mid-build would produce a
    # document whose sections came from different configurations without
    # anything recording that they had.
    chains: Optional[dict] = None
    if client is None:
        chains = await _resolve_chains(user_id)
        if not any(chains.values()):
            logger.warning("research_no_model_configured", ticker=ticker,
                           user_id=user_id)
            return None

    ticker = ticker.upper()
    context = await _load_context(ticker)
    if not context:
        logger.warning("research_insufficient_data", ticker=ticker)
        return None

    resolved = await prior_record.load_resolved(ticker, user_id)
    ledger, scores, summary = _assemble(ticker, context, watchlist, resolved)
    if ledger.substantive_count() < 5:
        # Counts facts about the company, not the "not available" lines. A
        # ledger of five declared absences would otherwise clear this guard and
        # then skip every agent underneath it.
        logger.warning("research_thin_evidence", ticker=ticker,
                       facts=ledger.substantive_count(), total=len(ledger))
        return None

    results = await _fan_out(client, ledger, settings, chains)
    debate = await _rebut(client, ledger, results, settings, chains)
    synthesis, synthesis_error = await _synthesise(
        client, ledger, results, scores, settings, debate, chains
    )

    stances = await _stance_panel(client, ledger, synthesis, scores, settings, chains)

    dossier = _compose(ticker, ledger, scores, summary, results, synthesis,
                       synthesis_error, debate, stances)
    dossier["user_id"] = str(user_id) if user_id else None
    await _persist(dossier)
    return dossier


async def _resolve_chains(user_id: Optional[str]) -> dict:
    """
    This user's ordered candidates per role, resolved once per dossier.

    A user entitled to it and with nothing configured gets a chain of exactly
    one — the server's own key — which is why a fresh trader account still
    produces dossiers and why a single-trader deployment behaves exactly as it
    did before any of this existed.

    An account on a plan that pays for its own tokens does not get that link.
    Their chain is their keys and nothing else, so a key that fails mid-dossier
    fails the dossier rather than quietly moving the bill to the operator.
    """
    from app.services.entitlements import entitlements_for
    from app.services.llm.resolver import build_chain

    llm_settings: Optional[dict] = None
    # Absent a user, this is the deployment's own work — the same reading
    # `build_chain` defaults to.
    allow_server_key = True
    if user_id:
        try:
            db = await get_db()
            from bson import ObjectId

            try:
                key = ObjectId(str(user_id))
            except Exception:
                key = user_id
            user = await db[COLL_USERS].find_one(
                {"_id": key},
                {"llm_settings": 1, "access_tier": 1, "email": 1,
                 "research_daily_allowed": 1},
            )
            llm_settings = (user or {}).get("llm_settings")
            if user is not None:
                allow_server_key = entitlements_for(user).may_use_server_key
        except Exception as exc:
            # Fall through to the server key rather than failing the build. A
            # database hiccup should cost the user their model *choice*, not
            # their dossier.
            logger.warning("research_llm_settings_read_failed",
                           user_id=user_id, error=str(exc))

    return {
        "orchestrator": build_chain(llm_settings, "orchestrator",
                                    allow_server_key=allow_server_key),
        "specialist": build_chain(llm_settings, "specialist",
                                  allow_server_key=allow_server_key),
    }


def _chain_for(spec: AgentSpec, chains: Optional[dict]) -> Optional[list]:
    """The candidate list for this agent's role, or None on the injected path."""
    if chains is None:
        return None
    return chains.get(spec.model_role) or chains.get("specialist")


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
        # The two exceptions to "cache-only". Both are off by default, both
        # fail to absent, and neither has a cache to read — chatter and market
        # prices are only worth anything current, and a stored copy would be
        # answering a question about last week.
        "social": await fetch_social(ticker),
        "markets": await fetch_macro_markets(),
    }


def _assemble(ticker: str, context: dict,
              watchlist: Optional[list[dict]],
              resolved: Optional[list[dict]] = None
              ) -> tuple[Ledger, list[dim.Dimension], dict]:
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
    summary["social"] = social_evidence.build(ledger, context.get("social"))
    summary["prediction_markets"] = prediction.build(ledger, context.get("markets"))

    # This desk's own settled readings, added last so they carry the highest
    # `O` ids and read as an appendix rather than as company data. `meta=True`
    # keeps them out of `substantive_count`, so a name with a track record and
    # no financials still fails the evidence guard below.
    summary["prior_record"] = prior_record.add_prior_record(ledger, ticker, resolved or [])

    fcf_yield = _fcf_yield(fundamentals, annual)
    # Note what does NOT happen here: the prior record never reaches
    # `build_all`. The conviction anchor is arithmetic over company data, and
    # the synthesiser stays clamped to +/-15 of it — so memory can temper a
    # reading and can never manufacture one. Same rule as the veto.
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

async def _fan_out(client: Any, ledger: Ledger, settings,
                   chains: Optional[dict] = None) -> dict[str, AgentResult]:
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
            chain=_chain_for(spec, chains),
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


# ── Rebuttal ──────────────────────────────────────────────────────────────────

def _constructive(results: dict[str, AgentResult]) -> dict[str, dict]:
    """The three agents making the case for the company, where they reported."""
    return {
        name: r.output for name, r in results.items()
        if name in ("fundamentals", "technical", "news") and r.ok
    }


async def _rebut(client: Any, ledger: Ledger, results: dict[str, AgentResult],
                 settings, chains: Optional[dict] = None) -> Optional[dict]:
    """
    One exchange between the risk agent and the evidence that answers it.

    Both sides have already written independently — that property is the whole
    reason this is safe, and it is what the reference implementation gives up
    by having its bear react to a bull case from the first round. Here neither
    side saw the other while forming its view, so this round is a genuine test
    of an argument rather than a negotiation over a shared framing.

    Runs the two directions concurrently. They are independent by construction:
    the risk side answers "what survives your evidence", the defence side
    answers "what does your evidence fail to answer", and letting either read
    the other's answer would collapse the round back into a single voice.

    Skipped, not failed, whenever there is nothing to argue: the round is off,
    the risk agent did not report, or none of the constructive three did. A
    dossier without a rebuttal is a complete dossier; the fan-out and the
    synthesis are the parts that must happen.
    """
    rounds = int(getattr(settings, "research_debate_rounds", 0) or 0)
    if rounds <= 0:
        return None

    risk = results.get("risk")
    constructive = _constructive(results)
    if risk is None or not risk.ok or not constructive:
        logger.info("research_rebuttal_skipped",
                    reason="risk agent absent" if (risk is None or not risk.ok)
                    else "no constructive report to argue against")
        return None

    brief = _rebuttal_brief(risk.output or {}, constructive)
    tasks = [
        run_agent(
            client, _rebuttal_spec(spec, brief), _evidence_block(ledger, spec),
            _model_for(spec, settings), settings.research_effort,
            settings.research_extended_thinking,
            chain=_chain_for(spec, chains),
        )
        for spec in (specs.RISK_REBUTTAL, specs.DEFENCE_REBUTTAL)
    ]
    settled = await asyncio.gather(*tasks, return_exceptions=True)

    out: dict[str, Any] = {"rounds": 1}
    for spec, outcome in zip((specs.RISK_REBUTTAL, specs.DEFENCE_REBUTTAL), settled):
        if isinstance(outcome, BaseException):
            logger.warning("research_rebuttal_raised", agent=spec.name,
                           error=str(outcome))
            out[spec.name] = None
        elif not outcome.ok:
            logger.warning("research_rebuttal_failed", agent=spec.name,
                           error=outcome.error)
            out[spec.name] = None
        else:
            out[spec.name] = outcome.output

    # One side failing still leaves a usable exchange; both failing leaves
    # nothing, and a `debate` block full of nulls would read to the synthesiser
    # as an argument that produced no answers rather than as an argument that
    # never happened.
    if out.get("risk_rebuttal") is None and out.get("defence_rebuttal") is None:
        return None
    return out


def _rebuttal_spec(spec: AgentSpec, brief: str) -> AgentSpec:
    """The spec with this dossier's material bound into its task."""
    return AgentSpec(
        name=spec.name, prefixes=spec.prefixes, system_prompt=spec.system_prompt,
        task=f"{spec.task}\n\n{brief}", schema=spec.schema,
        model_role=spec.model_role,
    )


def _rebuttal_brief(risk: dict, constructive: dict[str, dict]) -> str:
    """
    The material both sides argue over, identical for each.

    Byte-identical on purpose: an asymmetry in what the two are shown would
    make the exchange a comparison of inputs rather than of arguments.
    """
    parts = ["\n\nTHE BEAR CASE\n", json.dumps(risk, indent=2),
             "\n\nTHE THREE CONSTRUCTIVE ANALYSTS\n"]
    for name in ("fundamentals", "technical", "news"):
        report = constructive.get(name)
        if report is None:
            parts.append(f"\n## {name} — DID NOT REPORT. Treat every question "
                         f"it would have answered as open; its silence answers "
                         f"nothing.\n")
        else:
            parts.append(f"\n## {name}\n{json.dumps(report, indent=2)}\n")
    return "".join(parts)


# ── Stance panel ──────────────────────────────────────────────────────────────

async def _stance_panel(client: Any, ledger: Ledger, synthesis: Optional[dict],
                        scores: list[dim.Dimension], settings,
                        chains: Optional[dict] = None) -> Optional[dict]:
    """
    Three temperaments asked the same question about the *trade*.

    Advisory in the strongest sense the word has here: nothing in
    `_prepare_entry` reads this, no quantity moves because of it, and three
    unanimous WAITs still leave the order the risk model sized. That is the one
    idea from the reference implementation this project declines — its
    portfolio-manager agent decides the position, and deterministic sizing on a
    frozen equity basis is why the same inputs produce the same order twice.

    One honest limitation, and it is the reason the panel reads a name rather
    than an account: a dossier is shared across users, so running this per-user
    would multiply its cost by the user count. The stances therefore see the
    reading and the ticker's own risk profile, and not how much of anyone's
    account is already in it. A client displaying them must not imply
    otherwise.

    Skipped when there is no report — with nothing synthesised there is no
    trade to have a stance about, and three agents would be paid to say so.
    """
    if not getattr(settings, "research_stance_panel_enabled", False):
        return None
    if not synthesis:
        logger.info("research_stances_skipped", reason="no synthesised report")
        return None

    brief = _stance_brief(synthesis, scores)
    tasks = [
        run_agent(
            client, _rebuttal_spec(spec, brief), _evidence_block(ledger, spec),
            _model_for(spec, settings), settings.research_effort,
            settings.research_extended_thinking,
            chain=_chain_for(spec, chains),
        )
        for spec in specs.STANCES
    ]
    settled = await asyncio.gather(*tasks, return_exceptions=True)

    out: dict[str, Any] = {}
    for spec, outcome in zip(specs.STANCES, settled):
        key = spec.name.replace("stance_", "")
        if isinstance(outcome, BaseException) or not getattr(outcome, "ok", False):
            error = str(outcome) if isinstance(outcome, BaseException) else outcome.error
            logger.warning("research_stance_failed", agent=spec.name, error=error)
            out[key] = None
        else:
            out[key] = outcome.output

    if not any(out.values()):
        return None
    return out


def _stance_brief(synthesis: dict, scores: list[dim.Dimension]) -> str:
    """
    What the three stances are shown, identical for each.

    The synthesised report rather than the raw specialists: they are reading a
    conclusion, not re-running the analysis, and handing them four unmerged
    reports would invite exactly the re-analysis the prompts forbid.
    """
    risk_dim = next((s for s in scores if s.key == "risk"), None)
    parts = [
        "\n\nTHE READING\n",
        json.dumps({k: v for k, v in synthesis.items()
                    if not k.startswith("_")}, indent=2),
        "\n\nTHE RISK GATE\n",
    ]
    if risk_dim is not None and risk_dim.score is not None:
        parts.append(
            f"Safety score for this name: {risk_dim.score:.0f}/100 "
            f"(higher is safer). The engine refuses an unattended BUY above a "
            f"risk reading of {RISK_MAX_FOR_BUY:.0f}/10 on its own scale.\n"
        )
    else:
        parts.append("The risk dimension could not be scored for this name. "
                     "Treat the risk profile as unmeasured, not as benign.\n")
    parts.append(
        "\nYou are not told how much of the account is already in this name — "
        "a dossier is shared, not per-account. Argue the position on the "
        "reading and this name's own risk profile, and do not assert anything "
        "about existing exposure.\n"
    )
    return "".join(parts)


# ── Synthesis ─────────────────────────────────────────────────────────────────

async def _synthesise(client: Any, ledger: Ledger, results: dict[str, AgentResult],
                      scores: list[dim.Dimension], settings,
                      debate: Optional[dict] = None,
                      chains: Optional[dict] = None
                      ) -> tuple[Optional[dict], Optional[str]]:
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
        prefixes=specs._ALL_PREFIXES,
        system_prompt=specs.SYNTHESISER_SYSTEM,
        task=_synthesis_task(usable, results, scores, anchor, debate),
        schema=specs.SYNTHESISER_SCHEMA,
        model_role="orchestrator",
    )
    result = await run_agent(
        client, spec, _evidence_block(ledger, spec),
        settings.research_orchestrator_model,
        settings.research_effort, settings.research_extended_thinking,
        chain=_chain_for(spec, chains),
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
                    scores: list[dim.Dimension], anchor: Optional[float],
                    debate: Optional[dict] = None) -> str:
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

    if debate:
        # The exchange goes between the reports and the scores: after the
        # material being argued over, before the arithmetic, because it is
        # about the former and must not read as commentary on the latter.
        parts.append(
            "\nTHE REBUTTAL — one exchange, after both sides had already "
            "written independently. The risk analyst was shown the three "
            "constructive reports for the first time and said which of its "
            "concerns they answer; a defence was asked, of the same material, "
            "which risks the evidence fails to answer.\n"
        )
        risk_side = debate.get("risk_rebuttal")
        defence_side = debate.get("defence_rebuttal")
        if risk_side is not None:
            parts.append(f"\n## risk analyst, after seeing the evidence\n"
                         f"{json.dumps(risk_side, indent=2)}\n")
        else:
            parts.append("\n## risk analyst's reply — DID NOT REPORT. Its "
                         "original risks stand unanswered and must be carried "
                         "or addressed on their own terms.\n")
        if defence_side is not None:
            parts.append(f"\n## the defence\n{json.dumps(defence_side, indent=2)}\n")
        else:
            parts.append("\n## the defence — DID NOT REPORT. No risk has been "
                         "answered on the record; do not treat any as disposed "
                         "of because this section is missing.\n")
        parts.append(
            "\nA risk both sides agree is answered may go in risks_addressed "
            "with the evidence that answered it. A risk the defence conceded, "
            "or that the risk analyst sharpened, belongs in key_risks — the "
            "concession is the part of this exchange worth the most, and "
            "quietly dropping it would waste the round.\n"
        )

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
             synthesis_error: Optional[str] = None,
             debate: Optional[dict] = None,
             stances: Optional[dict] = None) -> dict:
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
        #: Named for its module, not just for what it is. The analyst's own
        #: HIGH/MEDIUM/LOW conviction — a different scale, a different producer,
        #: and the gate on unattended execution rather than on the veto — owns
        #: the bare word `conviction` throughout the trading path. Two numbers
        #: called the same thing, one 0-100 and one categorical, is a mistake
        #: waiting on a reader who has seen only one of them.
        "research_conviction": conviction,
        "derived_research_conviction": (synthesis or {}).get("_derived_conviction"),
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
                #: Which model wrote this section, and every key the chain
                #: tried on the way. Without it, two dossiers cannot be
                #: compared and the research calibration arm is measuring a
                #: blend of producers rather than one reading.
                "provider": result.provider,
                "model": result.model,
                "attempts": result.attempts,
            }
            for name, result in results.items()
        },
        #: The distinct models behind this dossier, for the reader. A trader
        #: comparing two readings of the same company needs to know which model
        #: wrote which — it is the whole point of being able to choose one.
        "models_used": _models_used(results),
        "agents_failed": [name for name, r in results.items() if r.failed],
        "agents_skipped": [name for name, r in results.items() if r.skipped],
        #: Populated whenever `report` is null so a reader — and the API
        #: response — can tell "nothing to synthesise" from "the merge call
        #: itself broke" instead of both reading as an unexplained gap.
        "synthesis_error": synthesis_error if report is None else None,
        #: The rebuttal exchange, or None when the round did not run. Stored
        #: unfiltered alongside the filtered report, like the specialists' raw
        #: output and for the same reason: a reading that looks wrong should be
        #: traceable to the argument that produced it. The API model does not
        #: expose the raw form.
        "debate": _filter_debate(debate, valid),
        #: Advisory only. Nothing in the trading guard chain reads this, and a
        #: client rendering it must not imply the order quantity followed from
        #: it — sizing is arithmetic on a frozen equity basis and stays that way.
        "stances": _filter_stances(stances, valid),
        "data_gaps": _collect_gaps(results),
    }


def _models_used(results: dict[str, AgentResult]) -> list[dict]:
    """
    Distinct (provider, model) pairs that produced this dossier, with the
    agents each one wrote.

    Sorted so the same set of models always renders in the same order — a list
    whose order changed between two otherwise identical dossiers would look
    like a change when nothing changed.
    """
    seen: dict[tuple, list[str]] = {}
    for name, result in results.items():
        if not result.ok or not result.model:
            continue
        seen.setdefault((result.provider or "", result.model), []).append(name)
    return [
        {"provider": provider, "model": model, "agents": sorted(agents)}
        for (provider, model), agents in sorted(seen.items())
    ]


def _filter_debate(debate: Optional[dict], valid: set[str]) -> Optional[dict]:
    """
    Apply the citation rule to the exchange.

    The rebuttals are the one place a model is arguing rather than reporting,
    which is exactly where an unsupported assertion is most persuasive and
    least noticed. Every list here is filtered whole-item, the same treatment
    `key_risks` gets — a concession that cites nothing is not a smaller
    concession, it is an unsupported one.
    """
    if not debate:
        return None

    out: dict[str, Any] = {"rounds": debate.get("rounds", 1)}
    _LISTS = {
        "risk_rebuttal": ("answered", "surviving", "sharpened"),
        "defence_rebuttal": ("answered", "conceded", "overstated"),
    }
    for side, fields in _LISTS.items():
        payload = debate.get(side)
        if not payload:
            out[side] = None
            continue
        cleaned = {f: strip_uncited_list(payload.get(f), valid) for f in fields}
        for prose in ("residual_rationale", "strongest_surviving_risk"):
            if prose in payload:
                cleaned[prose] = strip_uncited(payload.get(prose), valid)
        if "residual_severity" in payload:
            cleaned["residual_severity"] = payload["residual_severity"]
        out[side] = cleaned
    return out


def _filter_stances(stances: Optional[dict], valid: set[str]) -> Optional[dict]:
    """
    Citation-filter the panel's prose, keeping the stance itself.

    The verdict is a closed enum and survives on its own; the argument for it
    is prose and is deleted if unsupported, leaving a stance whose reasoning
    reads as absent. That is the correct outcome and a deliberate one — a
    recommendation nobody can check is worse than a recommendation with a
    visible gap where the reasoning should be.
    """
    if not stances:
        return None
    out: dict[str, Any] = {}
    for key, payload in stances.items():
        if not payload:
            out[key] = None
            continue
        out[key] = {
            "stance": payload.get("stance"),
            "rationale": strip_uncited(payload.get("rationale"), valid),
            "what_would_change_it": strip_uncited(
                payload.get("what_would_change_it"), valid),
        }
    return out


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


async def latest_dossier(ticker: str,
                         user_id: Optional[str] = None) -> Optional[dict]:
    """
    The most recent dossier for *ticker*, for *this reader*, with a staleness flag.

    Served past its TTL rather than withheld — a day-old business assessment is
    still a business assessment — but flagged, because the veto and the UI both
    need to treat "old" differently from "current".

    Scoped to the user because dossiers are now built with the user's own keys
    and their own chosen models. Two readers on different models genuinely have
    different readings of the same company, and handing one person the other's
    would misattribute a judgement they did not make — and, through the veto,
    refuse their order on it.

    The fallback is deliberately narrow: **the legacy shared series only**, the
    documents written before dossiers were per-user, which carry no `user_id`
    at all. It is never another user's reading. That keeps every dossier
    already on disk readable and gives a user who has not built their own
    something to look at, without inventing cross-user visibility.
    """
    ticker = ticker.upper()
    try:
        db = await get_db()
        docs: list = []
        if user_id:
            docs = await (
                db[COLL_DOSSIERS]
                .find({"ticker": ticker, "user_id": str(user_id)}, {"_id": 0})
                .sort("as_of", -1)
                .limit(1)
                .to_list(length=1)
            )
        if not docs:
            # Pre-per-user documents. `user_id: None` matches both an explicit
            # null and a missing field, which is what those documents have.
            docs = await (
                db[COLL_DOSSIERS]
                .find({"ticker": ticker, "user_id": None}, {"_id": 0})
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

    # Dossiers written before the rename carry `conviction`/`derived_conviction`.
    # Normalised here, on the single read path, so the veto and the API see one
    # name and neither has to know the collection has history. Dossiers are a
    # retained series — old documents are still the newest one for any ticker
    # the daily job has not reached since.
    for legacy, current in (("conviction", "research_conviction"),
                            ("derived_conviction", "derived_research_conviction")):
        if doc.get(current) is None and doc.get(legacy) is not None:
            doc[current] = doc.pop(legacy)
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
