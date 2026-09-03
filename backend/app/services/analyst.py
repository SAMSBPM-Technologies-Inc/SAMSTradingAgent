"""
AI Analyst Service
──────────────────
Uses the Claude API to produce a structured, senior-analyst-quality research
note for a given ticker. Reads all enriched data directly from MongoDB so it
can be called independently of the pipeline step order.

Requires: ANTHROPIC_API_KEY + ENABLE_AI_ANALYST=true

Degrades gracefully: returns None when the key is absent or the API call fails,
allowing pipeline.py to fall back to the rule-based signal_generator.

Output schema stored in signal doc under "analyst_output":
  signal       : BUY | SELL | HOLD
  conviction   : HIGH | MEDIUM | LOW
  price_target : float | null
  stop_loss    : float | null
  time_horizon : one of _TIME_HORIZONS, or absent
  thesis       : str  (1-2 sentences)
  bull_case    : str
  bear_case    : str
  bull_points  : list[str]  (2-3 short bullets — the scannable form of bull_case)
  bear_points  : list[str]  (2-3 short bullets — the scannable form of bear_case)
  key_risks    : list[str]
  catalysts    : list[str]
  analyst_note : str  (2-3 paragraph research note)
"""
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import get_settings
from app.db import COLL_FEATURES, COLL_RAW, COLL_SIGNALS, COLL_TRADES, get_db
from app.models.trade import TradeStatus
from app.services import source_health
from app.services.research.agents.base import AgentSpec, run_agent
from app.services.cross_section import cohort_for
from app.services.risk_engine import RISK_MAX_FOR_BUY, assess_risk
from app.services.signal_generator import (
    BUY_THRESHOLD,
    RANK_BUY_FLOOR,
    RANK_BUY_PERCENTILE,
    RANK_MIN_COHORT,
    RANK_SELL_CEILING,
    SELL_THRESHOLD,
    boundary_confidence,
    classify_signal,
)
from app.utils.helpers import utcnow
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Model config ───────────────────────────────────────────────────────────────
# Sonnet 5 reaches near-Opus quality on structured analysis at $3/$15 per MTok
# against Opus's $5/$25. Output rate is what matters: thinking tokens bill as
# output and dominate this workload — input is well under a tenth of the cost.
_MODEL = "claude-sonnet-5"

# A ceiling, not a reservation: only tokens actually generated are billed, so
# there is no cost to leaving adaptive thinking room. Too *low* is what costs —
# a truncated response fails to parse and the whole call is wasted.
_MAX_TOKENS = 12000

_SYSTEM_PROMPT = """\
You are a senior equity research analyst with 20 years of experience across multiple market cycles.
You produce institutional-grade research notes: specific, data-driven, and honest about uncertainty.

Rules:
- Reference actual numbers from the data provided; do not invent figures
- Set price_target and stop_loss as realistic levels derived from ATR or support/resistance
- thesis: 1-2 sentences capturing the core investment case
- analyst_note: 2-3 paragraphs written like a real sell-side research note
- key_risks and catalysts: 2-4 items each, specific to this ticker and the current data
- bull_points and bear_points: 2-3 items each, at most 12 words per item. These are the
  same argument as bull_case and bear_case reduced to what a reader takes in at a glance —
  one distinct claim per bullet, leading with the number or fact that carries it, no
  hedging clauses, no sentence-final punctuation. They must not introduce anything the
  corresponding case does not say.
- time_horizon: how long THIS thesis needs to resolve — not a generic investing
  horizon. Derive it from the data in front of you: an earnings date inside the
  window, a catalyst with a date, how far the price target sits from spot
  measured in ATR. A target two ATR away is weeks; one that needs a re-rating is
  months. Say the shortest horizon the thesis honestly supports, and do not
  reach for the longest bucket because the outcome is uncertain — an uncertain
  view is LOW conviction, not a distant horizon.
- Signal must be exactly one of: BUY, SELL, HOLD
- Conviction must be exactly one of: HIGH, MEDIUM, LOW
- When technicals and fundamentals conflict, reason through the dominant driver before deciding

Holding versus buying:
- When the context contains an OPEN POSITION block, you are advising on a position
  that already exists. The question is whether to KEEP it, not whether to open it.
  BUY means add or keep building, HOLD means keep what is held, SELL means close it.
- A good company at a stretched price is a reason to take a profit, not a reason to
  keep holding. Say so when the position is extended, well above its cost, and off
  its peak — being right about the business is not the same as being right about the
  price from here.
- With no OPEN POSITION block, nothing is held: judge the name on its own merits and
  SELL means "avoid or exit", not "sell short". This system never opens shorts.
"""

# The shape, enforced server-side rather than requested in prose.
#
# This call used to paste a hand-written pseudo-schema into the prompt, take
# whatever came back, strip markdown fences with two regexes and hope
# `json.loads` worked. A truncated or fenced response failed to parse and wasted
# the entire call — including its thinking tokens, which are most of the bill.
# `services/research/` has used structured outputs since it was written; this is
# the same mechanism, so both paths now fail the same way and neither can
# silently return prose.
#
# Note the constraints deliberately absent: no `minimum`/`maximum`, no string
# length bounds, no array bounds. Structured outputs reject those outright with
# a 400 rather than ignoring them — the incident `tests/test_research_schemas.py`
# fences against. Bounds that matter are enforced in Python below.
#: The horizons the analyst may claim, nearest first.
#:
#: This was a bare free-text string and — uniquely among the required fields —
#: the system prompt said nothing about it at all. A required field with no
#: instruction gets the safest generic answer, so every ticker ever analysed
#: came back "3-6 months": a per-ticker judgement in shape, a constant in fact.
#:
#: Four buckets rather than free text because a horizon is only worth printing
#: if it can be compared against what happened, and free text cannot be grouped.
#: All four read naturally in every slot that renders them — "2-6 weeks
#: horizon", "Expected horizon: 2-6 weeks", "Monitor over 2-6 weeks" — which is
#: why they share one "N-M unit" shape.
#:
#: Capped at 3-6 months deliberately: signals settle at 20 trading days and
#: positions here resolve on a stop, a target or a SELL. A longer bucket would
#: be a horizon the system has no way to judge, which is the defect this
#: replaces rather than a fix for it.
_TIME_HORIZONS = ("1-2 weeks", "2-6 weeks", "1-3 months", "3-6 months")

_NUMBER_OR_NULL = {"type": ["number", "null"]}
_STRING = {"type": "string"}
_STRING_LIST = {"type": "array", "items": {"type": "string"}}

_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "signal": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "conviction": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "price_target": _NUMBER_OR_NULL,
        "stop_loss": _NUMBER_OR_NULL,
        # Enum, not free text — see `_TIME_HORIZONS`. Enums are the one
        # constraint every provider in `llm/registry.py` keeps: Gemini strips
        # `const` and `additionalProperties`, never `enum`, and `signal` and
        # `conviction` have relied on that since this schema was written.
        "time_horizon": {"type": "string", "enum": list(_TIME_HORIZONS)},
        "thesis": _STRING,
        "bull_case": _STRING,
        "bear_case": _STRING,
        # The scannable form of the two cases above. Asked of the model rather
        # than derived on the client, for the same reason `whyText` prefers the
        # model's own words: splitting a paragraph on full stops is a guess at
        # which clause carried the argument, made by the layer least equipped
        # to know. A client with no points shows the prose — it never invents
        # bullets from it. Note the absence of `maxItems`/`maxLength`: structured
        # outputs reject those with a 400 (see above), so the bounds are prose
        # in the system prompt and the client clamps what it renders.
        "bull_points": _STRING_LIST,
        "bear_points": _STRING_LIST,
        "key_risks": _STRING_LIST,
        "catalysts": _STRING_LIST,
        "analyst_note": _STRING,
    },
    "required": ["signal", "conviction", "price_target", "stop_loss",
                 "time_horizon", "thesis", "bull_case", "bear_case",
                 "bull_points", "bear_points",
                 "key_risks", "catalysts", "analyst_note"],
    "additionalProperties": False,
}


def _gate_analyst_signal(
    model_signal: str,
    score: float,
    risk_score: float,
    previous_signal: str | None,
    cohort=None,
) -> tuple[str, dict]:
    """
    Reconcile the model's verdict with the rule that owns the thresholds.

    **The analyst may veto a BUY. It may never create one.** This is the same
    rule `services/research/` has always followed, applied to the path that
    actually places orders — and it was missing here. `run_analysis` used to
    write `analyst_output["signal"]` into the signal document verbatim, beside
    the composite score, with `classify_signal` never consulted. Neither
    `BUY_THRESHOLD` nor `RISK_MAX_FOR_BUY` reached this path, and neither is
    stated in the system prompt: the model was free to answer BUY on a name the
    engine's own rule refused, and `pipeline._execute_trades` then handed that
    verdict straight to `execute_entry`.

    That is not a theoretical hole. `analyst_gate_margin` is 0.08, so the
    analyst is called precisely on the band the rule declines — scores in
    [0.62, 0.70) — which is where every unexplained BUY in the 25–31 Aug 2026
    paper record sits: AMZN at 0.62, AVGO 0.63, NVDA 0.64, CBRS 0.66 on a risk
    score of 6.3, past a veto that is supposed to be unconditional.

    A model HOLD over a rule BUY is left alone — refusing an entry is exactly
    what a second opinion is for. **The exit is not symmetrical.** A model SELL
    publishes at any score, and a model HOLD or BUY over a *rule* SELL does
    not: the rule's SELL is restored. Suppressing an exit is a brake on the
    exit path, and this system has never allowed one — SELL skips the risk
    gate in `classify_signal`, skips confirmations and dwell in
    `signal_stability`, and is unreachable by the research veto. Letting the
    analyst alone hold a position open below the sell threshold would have made
    it the only component that can, through the one path that also places
    orders.

    So the model can talk the engine out of buying, and cannot talk it out of
    selling. Refusing to buy costs an opportunity; refusing to sell costs
    money.

    `previous_signal` engages the same hysteresis band the rule uses, so an
    established BUY the analyst still likes is not torn down the moment the
    score dips a thousandth under the threshold.

    `cohort` is passed straight through to `classify_signal` and must be the
    same one the rule-based path would have used. The gate's whole purpose is
    to reconcile the model against **the rule that publishes**; under relative
    scoring that rule accepts a BUY at 0.60 in the top quintile, and a gate
    still holding out for 0.70 would refuse it and write a `buy_refused` for a
    refusal the engine never made. That would corrupt the counterfactual as
    well as the verdict.

    Returns `(published_signal, gate_record)`. The record is written to the
    signal document whether or not anything was overridden — "the gate ran and
    agreed" and "no gate ran" are different facts, and only one of them can be
    argued from later. It is what `/performance/calibration` needs to answer
    whether these overrides were ever worth having.
    """
    rule_signal = classify_signal(score, risk_score, previous_signal, cohort)
    ranked = cohort is not None and cohort.size >= RANK_MIN_COHORT

    published = model_signal
    reason: str | None = None
    kind: str | None = None

    if rule_signal == "SELL" and model_signal != "SELL":
        # Tested first, and it outranks the BUY clause: when the rule wants out
        # and the model wants in, the exit wins. A model BUY on a name scoring
        # under the sell threshold is the single worst case this function has
        # to handle, and "publish HOLD" would be the wrong answer to it.
        published = "SELL"
        kind = "sell_restored"
        # The stated reason has to name the bar that was actually applied.
        # Printing an absolute threshold under a rank-decided verdict is the
        # same defect as the gate panel reporting `score > 0.70` beside a
        # hysteresis-held BUY — a true-sounding sentence about a rule that did
        # not run.
        reason = (
            (
                f"The analyst read this as {model_signal}; this is the weakest "
                f"{_place(cohort)} of the {cohort.size} names watched and scores "
                f"{score:.2f}, at or under the {RANK_SELL_CEILING:.2f} ceiling a "
                f"sell needs. An exit is never held back. Published as SELL."
            ) if ranked else (
                f"The analyst read this as {model_signal}; the score of {score:.2f} is "
                f"under the {SELL_THRESHOLD:.2f} that triggers a sell, and an exit is "
                f"never held back. Published as SELL."
            )
        )
    elif model_signal == "BUY" and rule_signal != "BUY":
        published = "HOLD"
        kind = "buy_refused"
        if risk_score >= RISK_MAX_FOR_BUY:
            # Named first because it is the unconditional one: no score
            # rescues a BUY above the risk veto, so reporting the score here
            # would suggest a bar this name could have cleared.
            reason = (
                f"The analyst read this as a BUY; risk {risk_score:.1f} is at or "
                f"above the {RISK_MAX_FOR_BUY:.1f} veto, which no score overrides. "
                f"Published as HOLD."
            )
        elif ranked and score < RANK_BUY_FLOOR:
            # Two ways to fail the relative rule, and they are different facts
            # a reader will act on differently: below the floor means the name
            # is not worth owning at any rank, outside the quintile means it is
            # simply not the best of what is being watched today.
            reason = (
                f"The analyst read this as a BUY; the score of {score:.2f} is under "
                f"the {RANK_BUY_FLOOR:.2f} floor a buy needs regardless of how it "
                f"ranks. Published as HOLD."
            )
        elif ranked:
            reason = (
                f"The analyst read this as a BUY; it is the {_place(cohort)} strongest "
                f"of the {cohort.size} names watched, outside the top "
                f"{1 - RANK_BUY_PERCENTILE:.0%} a buy needs. Published as HOLD."
            )
        else:
            reason = (
                f"The analyst read this as a BUY; the score of {score:.2f} is under "
                f"the {BUY_THRESHOLD:.2f} a BUY needs. Published as HOLD."
            )

    return published, {
        "model_signal": model_signal,
        "rule_signal": rule_signal,
        "published_signal": published,
        "overridden": published != model_signal,
        # Which of the two overrides fired, as a token rather than as prose to
        # be parsed. `/performance/calibration` has to be able to bucket these
        # separately: a refused BUY and a restored SELL are different bets and
        # pooling them would measure neither.
        "override": kind,
        "reason": reason,
        "score": round(score, 4),
        "risk_score": round(risk_score, 2),
        # The bar this decision was actually held to, so a record read months
        # later is not silently reinterpreted under whichever rule is current
        # then. `buy_threshold` stays the absolute one on both rules because
        # that is what the field has always meant; the rank fields are absent
        # rather than null under the absolute rule, the same absent-vs-null
        # distinction `analyst_override` draws.
        "buy_threshold": BUY_THRESHOLD,
        "risk_max_for_buy": RISK_MAX_FOR_BUY,
        **(
            {
                "rule": "relative",
                "percentile": cohort.percentile,
                "cohort_size": cohort.size,
                "rank_buy_percentile": RANK_BUY_PERCENTILE,
                "rank_buy_floor": RANK_BUY_FLOOR,
            } if ranked else {}
        ),
    }


def _place(cohort) -> str:
    """
    A cohort position as an ordinal — "3rd" of 13 — rather than a percentile.

    A reader can check "3rd of 13" against the watchlist in front of them. They
    cannot check 0.83, and a refusal nobody can verify is the kind this
    codebase spent three releases learning not to write.
    """
    place = round((1.0 - cohort.percentile) * (cohort.size - 1)) + 1
    suffix = (
        "th" if 11 <= place % 100 <= 13
        else {1: "st", 2: "nd", 3: "rd"}.get(place % 10, "th")
    )
    return f"{place}{suffix}"


async def run_analysis(
    ticker: str, client: Any = None, previous_signal: str | None = None
) -> Optional[dict]:
    """
    Produce a full analyst signal doc for *ticker*.
    Returns a signal-doc-compatible dict (ready to upsert into stocks_signals)
    or None if analyst is disabled / API call fails.

    `previous_signal` is the verdict currently published for this ticker. It
    reaches `_gate_analyst_signal`, where it engages the hysteresis band — the
    same one the rule-based path uses, so the two cannot disagree about how
    sticky an established verdict is.
    """
    settings = get_settings()
    if client is None and not settings.anthropic_api_key:
        logger.warning("analyst_disabled", reason="ANTHROPIC_API_KEY not set")
        return None

    ticker = ticker.upper()
    db = await get_db()

    feat = await db[COLL_FEATURES].find_one({"ticker": ticker})
    raw  = await db[COLL_RAW].find_one({"ticker": ticker})
    if not feat or not raw:
        logger.warning("analyst_missing_data", ticker=ticker)
        return None

    risk = assess_risk(feat)
    # Only when the flag is on, and only ever additive: this cannot change a
    # verdict the gate would not already have accepted, because
    # `_gate_analyst_signal` still reconciles whatever comes back against the
    # rule. What it changes is the question the model is answering.
    position = (
        await position_context(ticker)
        if get_settings().analyst_position_context else None
    )
    context = _build_context(ticker, feat, raw, risk, position)

    try:
        analyst_output = await _call_claude(
            context,
            settings.anthropic_api_key,
            model=settings.analyst_model,
            extended_thinking=settings.analyst_extended_thinking,
            effort=settings.analyst_effort,
            client=client,
        )
    except Exception as exc:
        logger.warning("analyst_claude_failed", ticker=ticker, error=str(exc))
        await source_health.record_attempt(
            "analyst", source_health.FAILED, error=str(exc), ticker=ticker,
        )
        return None

    # The status page's analyst row had no writer of any kind before this: the
    # analyst does not touch `stocks_raw`, so `source_health.observe` cannot see
    # it, and nothing recorded it as a subsystem either. The row therefore read
    # "No reading yet" permanently on a server where the analyst was working —
    # which is the page reporting on its own instrumentation rather than on the
    # system.
    #
    # Recorded on a *call*, not on a cache hit. The 60-minute cache means most
    # cycles never reach Claude, and a cache hit confirms nothing about whether
    # the API would answer — the same reason `signal_stability` refuses to count
    # one as a confirmation. `last_success_at` carries the age of the last real
    # answer, which is the fact a reader is actually after.
    await source_health.record_attempt(
        "analyst", source_health.OK, ticker=ticker, model=settings.analyst_model,
    )

    # Build a signal doc compatible with stocks_signals schema
    price = feat.get("current_price", 0.0)
    score = round(float(feat.get("composite_score", 0.5) or 0.5), 4)

    # The gate must be handed the same cohort the rule-based path would use, or
    # it reconciles the model against a rule nobody publishes: under relative
    # scoring a BUY at 0.60 can be correct, and a gate still measuring 0.70
    # would refuse it and record a `buy_refused` that never happened. None when
    # ranking is off, which is the absolute rule unchanged.
    cohort = await cohort_for(ticker, score)

    published_signal, gate = _gate_analyst_signal(
        analyst_output.get("signal", "HOLD"),
        score,
        risk["risk_score"],
        previous_signal,
        cohort,
    )

    # Every derived field below describes *the verdict that was published*, not
    # the one the model asked for. Feeding the raw output to these helpers is
    # how a refused BUY would still print an entry price, a stop and a target —
    # a full buy plan under a HOLD. The model's own answer is preserved
    # untouched in `analyst_output`; it is the record of what it said, and
    # rewriting it would destroy the only evidence the override can be judged
    # from later.
    published_output = {**analyst_output, "signal": published_signal}

    signal_doc = {
        "ticker": ticker,
        "generated_at": utcnow(),
        "score": score,
        "risk": risk,
        "signal": published_signal,
        # A conviction-derived confidence describes the model's view. Once the
        # gate has refused that view, the published verdict is the rule's, so
        # the confidence has to be the rule's too — otherwise a HOLD nobody was
        # confident about is reported at the model's 0.85.
        "confidence": (
            boundary_confidence(score, published_signal, cohort) if gate["overridden"]
            else _conviction_to_confidence(analyst_output.get("conviction", "LOW"))
        ),
        "entry_suggestion": _entry_suggestion(published_output, price),
        "exit_suggestion": _exit_suggestion(published_output, price),
        "explanation": _build_explanation(ticker, published_output, feat, risk, gate),
        # Same two fields the rule-based path writes, for the same reason and
        # with the same absent-means-absolute convention. `_execute_trades`
        # reads `score_percentile` to decide which bar the order is held to, so
        # omitting it here would judge every analyst-path BUY under the
        # absolute rule while the verdict was decided under the relative one.
        **(
            {"score_percentile": cohort.percentile, "cohort_size": cohort.size}
            if cohort is not None else {}
        ),
        # Extended analyst fields
        "analyst_output": analyst_output,
        # What the gate made of the model's answer. Always written when the
        # analyst ran — see `_gate_analyst_signal`.
        "analyst_gate": gate,
        # Persisted, not merely returned. `pipeline._needs_analyst_refresh`
        # reads this field back off the stored document to decide whether a
        # cached analyst signal exists; the pipeline used to set it on the
        # in-memory dict only, so the stored document never carried it and
        # trigger 1 ("no_ai_signal") fired on every cycle. The 60-minute cache
        # therefore never hit once: Claude was re-called every ingestion cycle
        # for every ticker that passed the gate. That is what made a borderline
        # name flip BUY/HOLD eight times in an hour — each flip is a fresh
        # sampling of the model on unchanged inputs — and it is where the
        # analyst bill went. `GET /analyze` read the same missing field, so the
        # UI also reported "analyst did not run" on reports that it wrote.
        "analyst_used": True,
    }

    await db[COLL_SIGNALS].replace_one({"ticker": ticker}, signal_doc, upsert=True)

    if gate["overridden"]:
        # WARNING, not info: the model and the engine's own rule disagreed about
        # committing capital. It is a normal, expected outcome — but a run of
        # them says the analyst is being asked a question the gate will not let
        # it answer, and that is worth being able to grep for.
        logger.warning(
            "analyst_signal_gated",
            ticker=ticker,
            model_signal=gate["model_signal"],
            published=gate["published_signal"],
            score=gate["score"],
            risk_score=gate["risk_score"],
            conviction=analyst_output.get("conviction"),
        )

    logger.info(
        "analyst_complete",
        ticker=ticker,
        signal=signal_doc["signal"],
        conviction=analyst_output.get("conviction"),
        price_target=analyst_output.get("price_target"),
        gated=gate["overridden"],
    )
    return signal_doc


# ── Context builder ────────────────────────────────────────────────────────────

def _format_headline(article: dict) -> str:
    """One headline line, carrying whatever provenance the article has."""
    headline = (article.get("headline") or "").strip()
    parts = []
    source = (article.get("source") or "").strip()
    if source:
        parts.append(source)
    published = (article.get("datetime") or "")[:10]
    if published:
        parts.append(published)
    url = (article.get("url") or "").strip()
    if url:
        parts.append(url)
    suffix = f"  [{' | '.join(parts)}]" if parts else ""
    return f"- {headline}{suffix}"


async def position_context(ticker: str) -> dict | None:
    """
    What the desk is holding in *ticker*, or None when it is holding nothing.

    **The analyst is called on every open position precisely because "the exit
    decision is worth paying for at any score", and it was never told there was
    a position.** No holding flag, no cost basis, no working levels. So it
    answered "would I buy this?" every time, and a SELL from it meant "this is a
    bad name to own" rather than "take the profit". On a rip — where the company
    still looks excellent and only the price is extended — that is the wrong
    question, and the model's very reasonable HOLD was the wrong answer to it.

    Aggregated across holders and deliberately not scoped to a user: this call
    is shared, one per ticker per cycle, and its verdict is published to
    everyone watching. Behind `/trading` there is one brokerage account, so the
    aggregate is also the truth. Entry is cost-weighted for the same reason
    scale-in blends it — a position built in two lots has one cost basis.

    Returns None on any doubt, including a database error. A prompt that
    invents a position is worse than one that omits a real one: the first
    argues about money that is not there, the second is merely the behaviour
    every release before this had.
    """
    try:
        db = await get_db()
        rows = await db[COLL_TRADES].find({
            "ticker": ticker.upper(),
            "action": "BUY",
            "status": {"$in": list(TradeStatus.OPEN)},
            "closed_at": None,
        }).to_list(length=200)
    except Exception as exc:
        logger.warning("position_context_failed", ticker=ticker, error=str(exc))
        return None

    qty = 0.0
    cost = 0.0
    stops: list[float] = []
    targets: list[float] = []
    peak: float | None = None
    opened: datetime | None = None

    for r in rows:
        entry = r.get("entry_price") or r.get("limit_price")
        q = float(r.get("filled_qty") or r.get("qty") or 0)
        # An unfilled entry is an order, not a position. Counting it would
        # report a cost basis for shares nobody owns.
        if not entry or q <= 0 or not r.get("entry_price"):
            continue
        qty += q
        cost += q * float(entry)
        if r.get("stop_loss"):
            stops.append(float(r["stop_loss"]))
        if r.get("take_profit"):
            targets.append(float(r["take_profit"]))
        hw = r.get("high_water_price")
        if hw is not None:
            peak = float(hw) if peak is None else max(peak, float(hw))
        at = r.get("filled_at") or r.get("opened_at")
        if isinstance(at, datetime):
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            opened = at if opened is None else min(opened, at)

    if qty <= 0 or cost <= 0:
        return None

    return {
        "qty": qty,
        "entry": cost / qty,
        # The tightest stop and the nearest target are the levels that will
        # actually resolve the position first.
        "stop": max(stops) if stops else None,
        "target": min(targets) if targets else None,
        "peak": peak,
        "opened_at": opened,
    }


def _position_block(pos: dict | None, price: float) -> str:
    """
    The prompt section describing an open position, or an empty string.

    Everything here is a fact the record holds; nothing is inferred. The peak is
    the point of it — "up 14%, and 6% off its high since entry" is the sentence
    that makes a profit-taking question answerable at all, and no release before
    the high-water mark existed could have written it.
    """
    if not pos or price <= 0:
        return ""

    entry = pos["entry"]
    unreal = (price - entry) / entry
    lines = [
        "",
        "=== OPEN POSITION — YOU ARE HOLDING THIS ===",
        f"Position: {pos['qty']:g} shares at a blended cost of ${entry:,.2f}",
        f"Unrealised: {unreal:+.1%} at the current ${price:,.2f}",
    ]
    peak = pos.get("peak")
    if peak and peak > 0:
        off = (peak - price) / peak
        lines.append(
            f"Peak since entry: ${peak:,.2f} "
            f"({(peak - entry) / entry:+.1%} at its best; now {off:.1%} below that peak)"
        )
    if pos.get("stop"):
        lines.append(f"Working stop: ${pos['stop']:,.2f}")
    if pos.get("target"):
        lines.append(f"Working target: ${pos['target']:,.2f}")
    opened = pos.get("opened_at")
    if opened:
        days = max((datetime.now(tz=timezone.utc) - opened).days, 0)
        lines.append(f"Held for {days} day{'s' if days != 1 else ''}")
    lines.append(
        "The decision here is whether to KEEP this position, not whether to "
        "start one."
    )
    return "\n".join(lines) + "\n"


def _build_context(
    ticker: str, feat: dict, raw: dict, risk: dict, position: dict | None = None,
) -> str:
    price   = feat.get("current_price", 0.0)
    chg     = raw.get("day_change_pct", 0.0)
    date    = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # Technical
    rsi     = feat.get("rsi_14")
    rsi_str = f"{rsi:.1f} ({'overbought' if rsi and rsi > 70 else 'oversold' if rsi and rsi < 30 else 'neutral'})" if rsi else "N/A"
    macd_b  = feat.get("macd_bullish")
    macd_str = "Bullish crossover (MACD above signal)" if macd_b else ("Bearish crossover (MACD below signal)" if macd_b is False else "N/A")
    bb_pct  = feat.get("bb_pct")
    bb_str  = f"{bb_pct:.0%} (0%=lower band, 100%=upper band{', extended above upper band' if bb_pct and bb_pct > 1 else ''})" if bb_pct is not None else "N/A"
    stoch   = feat.get("stoch_rsi")
    stoch_str = f"{stoch:.2f} ({'overbought' if stoch and stoch > 0.8 else 'oversold' if stoch and stoch < 0.2 else 'neutral'})" if stoch is not None else "N/A"
    ma_20   = feat.get("ma_20")
    ma_50   = feat.get("ma_50")
    trend   = "Bullish (price > MA20 > MA50)" if feat.get("ma_cross_bullish") else "Bearish (MA20 < MA50)" if feat.get("ma_cross_bullish") is False else "Mixed"
    vol     = feat.get("volatility_20d", 0.0)
    atr     = feat.get("atr_14")
    vol_anom = feat.get("volume_anomaly", 1.0)

    # Scores
    tech_s  = feat.get("technical_score",   0.5)
    fund_s  = feat.get("fundamental_score", 0.5)
    sent_s  = feat.get("sentiment_score",   0.5)
    macro_s = feat.get("macro_score",       0.5)
    comp    = feat.get("composite_score",   0.5)

    # Fundamentals
    fund = raw.get("fundamentals") or {}
    pe      = fund.get("pe_ratio")
    rev_g   = fund.get("revenue_growth_yoy")
    fcf     = fund.get("free_cash_flow")
    de      = fund.get("debt_to_equity")
    rec     = fund.get("analyst_recommendation")
    tgt     = fund.get("analyst_target_price")
    n_earn  = fund.get("next_earnings_date")
    sector  = fund.get("sector")

    def fmt(v, suffix="", pct=False, dollar=False, scale=1):
        if v is None:
            return "N/A"
        v = float(v) * scale
        if pct:
            return f"{v:.1%}"
        if dollar:
            return f"${v:,.0f}" if abs(v) >= 1000 else f"${v:.2f}"
        return f"{v:.2f}{suffix}"

    # Macro
    macro = raw.get("macro") or {}
    fed     = macro.get("fed_funds_rate")
    t10     = macro.get("treasury_10y")
    t2      = macro.get("treasury_2y")
    spread  = macro.get("yield_curve_spread")
    cpi     = macro.get("cpi_yoy_pct")
    unemp   = macro.get("unemployment")
    vix     = macro.get("vix")
    spread_str = f"{spread:+.2f}% ({'normal' if spread and spread > 0 else 'INVERTED — recession signal'})" if spread is not None else "N/A"
    vix_str = f"{vix:.1f} ({'elevated fear' if vix and vix > 25 else 'calm' if vix and vix < 18 else 'moderate'})" if vix else "N/A"

    # Headlines. Rendered with their source, date and URL — all three were
    # already stored on every article and all three were dropped here, which is
    # why the model could reference "recent news" but never attribute a claim to
    # anything. A model asked for institutional-grade research over anonymous
    # headline text has no way to cite, however it is prompted.
    headlines = raw.get("recent_headlines") or []
    hl_str = "\n".join(_format_headline(h) for h in headlines[:8]) \
        if headlines else "No recent headlines available"

    sent_raw = raw.get("sentiment_raw") or {}

    # Alternative data
    alt    = raw.get("alternative_data") or {}
    opt    = alt.get("options_flow") or {}
    short  = alt.get("short_interest") or {}
    ins    = alt.get("insider_trades") or {}
    pcr    = opt.get("put_call_ratio")
    pcr_str  = f"{pcr:.2f} ({opt.get('sentiment', 'N/A')})" if pcr is not None else "N/A"
    si_pct   = short.get("short_percent_of_float")
    si_str   = f"{si_pct:.1%} short float | {short.get('short_ratio', 'N/A')}d to cover | squeeze risk: {short.get('squeeze_risk', 'N/A')}" if si_pct is not None else "N/A"
    ins_str  = f"{ins.get('buy_count_90d', 0)} buys / {ins.get('sell_count_90d', 0)} sells (90d) — {ins.get('net_sentiment', 'N/A')}" if ins.get("net_sentiment") else "N/A"

    return f"""Analyze {ticker} as of {date}. Current price: ${price:.2f} ({chg:+.2f}% today){f' | Sector: {sector}' if sector else ''}

=== TECHNICAL ANALYSIS ===
RSI-14: {rsi_str}
MACD: {macd_str}
Bollinger Band position: {bb_str}
Stochastic RSI: {stoch_str}
MA-20: {fmt(ma_20, dollar=True)} | MA-50: {fmt(ma_50, dollar=True)} | Trend: {trend}
ATR-14: {fmt(atr, dollar=True)} | 20-day Annualised Volatility: {vol:.0%}
Volume anomaly: {vol_anom:.1f}x 20-day average

=== SCORES (0=bearish, 1=bullish) ===
Technical Score:   {tech_s:.2f}
Fundamental Score: {fund_s:.2f}
Sentiment Score:   {sent_s:.2f}  ({sent_raw.get('article_count', 0)} articles, {sent_raw.get('bullish_pct', 0.5):.0%} bullish, source: {sent_raw.get('source', 'N/A')})
Macro Score:       {macro_s:.2f}
Composite Score:   {comp:.2f}

=== FUNDAMENTALS ===
P/E Ratio: {fmt(pe)}
Revenue Growth (YoY): {fmt(rev_g, pct=True)}
Free Cash Flow: {fmt(fcf, dollar=True)}
Debt/Equity: {fmt(de)}%
Analyst Consensus: {rec or 'N/A'}{f' | Target: ${tgt:.2f}' if tgt else ''}
Next Earnings: {n_earn or 'N/A'}

=== MACRO ENVIRONMENT ===
Fed Funds Rate: {fmt(fed)}%
10Y Treasury: {fmt(t10)}% | 2Y Treasury: {fmt(t2)}%
Yield Curve (10Y-2Y): {spread_str}
CPI YoY: {fmt(cpi)}%
Unemployment: {fmt(unemp)}%
VIX: {vix_str}

=== RECENT NEWS (last 7 days) ===
{hl_str}

=== ALTERNATIVE DATA ===
Options Flow (P/C ratio): {pcr_str}
Short Interest: {si_str}
Insider Transactions (90d): {ins_str}

{_position_block(position, price)}
=== RISK ASSESSMENT ===
Risk Score: {risk['risk_score']:.1f}/10 ({risk['risk_level']})
{risk['explanation']}

Your response shape is enforced by the API — write the content, not the \
envelope. Leave price_target or stop_loss null rather than estimating one the \
data does not support."""


# ── Claude API call ────────────────────────────────────────────────────────────

async def _call_claude(
    context: str,
    api_key: str,
    model: str = _MODEL,
    extended_thinking: bool = True,
    effort: str = "medium",
    client: Any = None,
) -> dict:
    """
    One structured call, through the same seam the research agents use.

    This shares `agents/base.run_agent` rather than reimplementing the request,
    and that is the point of the change. The old version built its client
    inline — which is why this module has had no tests since it was written —
    asked for JSON in prose, stripped markdown fences with two regexes, and
    called `json.loads` on whatever survived. A truncated response failed to
    parse and wasted the whole call including its thinking tokens, which are
    most of the bill. `run_agent` already handles the refusal stop reason, the
    truncation stop reason, and schema enforcement, and it is covered by
    `tests/test_research_orchestrator.py`.

    `client` is injectable for the same reason it is on `build_dossier`: so
    this path can finally be tested without a network call.
    """
    if client is None:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)

    spec = AgentSpec(
        name="analyst",
        prefixes=(),
        system_prompt=_SYSTEM_PROMPT,
        task=context,
        schema=_RESPONSE_SCHEMA,
        model_role="orchestrator",
    )
    # The system prompt carries the cache breakpoint here rather than an
    # evidence block: this path has no ledger, and the prompt is the only part
    # that repeats across tickers. It is small enough that the hit is worth
    # little — the levers that matter on this call are the model, the effort
    # level, and `pipeline._analyst_worth_calling` not making it at all.
    result = await run_agent(client, spec, _SYSTEM_PROMPT, model, effort,
                             extended_thinking)
    if not result.ok:
        raise ValueError(result.error or "analyst call produced no output")

    parsed = dict(result.output or {})

    # The schema guarantees the enum members, so these two normalisations are
    # now belt-and-braces rather than the only thing standing between the model
    # and a signal doc. Kept because `_conviction_to_confidence` and the
    # trading path both key off exact strings, and a silent drift to "Buy"
    # would route through `.get(..., 0.25)` and read as low conviction.
    parsed["signal"] = str(parsed.get("signal", "HOLD")).upper()
    parsed["conviction"] = str(parsed.get("conviction", "LOW")).upper()
    if parsed["signal"] not in ("BUY", "SELL", "HOLD"):
        parsed["signal"] = "HOLD"
    if parsed["conviction"] not in ("HIGH", "MEDIUM", "LOW"):
        parsed["conviction"] = "LOW"

    # An unrecognised horizon is dropped rather than mapped to a bucket. There
    # is no conservative direction to fall back to here — LOW is the safe read
    # of an unknown conviction, but no horizon is the safe read of an unknown
    # horizon — and picking one would reinstate exactly the constant this enum
    # exists to remove. Every render site already tests the field before
    # printing it, so absent degrades to "no horizon shown".
    if parsed.get("time_horizon") not in _TIME_HORIZONS:
        parsed.pop("time_horizon", None)

    logger.info(
        "analyst_claude_usage",
        model=model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read=result.cache_read_tokens,
    )
    return parsed


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _conviction_to_confidence(conviction: str) -> float:
    return {"HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25}.get(conviction, 0.25)


def _entry_suggestion(output: dict, price: float) -> Optional[str]:
    signal = output.get("signal")
    pt = output.get("price_target")
    sl = output.get("stop_loss")
    if signal == "BUY" and price > 0:
        entry = f"${price:.2f} (current)"
        parts = [entry]
        if sl:
            parts.append(f"stop-loss ${sl:.2f}")
        if pt:
            parts.append(f"target ${pt:.2f}")
        return " | ".join(parts)
    # No entry line on a SELL. There is nothing to enter: SELL means "exit the
    # position", never "open a short" — shorting is not permitted in a TFSA and
    # `trade_manager` has no path that opens one. This used to read
    # "Short near $X | cover target $Y", describing a trade this system cannot
    # place; `signal_generator._price_suggestions` had that corrected long ago
    # and returns None here for the same reason.
    return None


def _exit_suggestion(output: dict, price: float) -> Optional[str]:
    signal = output.get("signal")
    sl = output.get("stop_loss")
    pt = output.get("price_target")
    horizon = output.get("time_horizon", "")
    if signal == "BUY":
        parts = []
        if sl:
            parts.append(f"Stop-loss ${sl:.2f}")
        if pt:
            parts.append(f"Take-profit ${pt:.2f}")
        if horizon:
            parts.append(f"Horizon: {horizon}")
        return " | ".join(parts) if parts else None
    if signal == "HOLD":
        return f"Monitor over {horizon}" if horizon else f"Monitor; re-evaluate on ±5% move from ${price:.2f}"
    if signal == "SELL" and price > 0:
        # The exit line the SELL path never had: `_exit_suggestion` returned
        # None for it, so the only text a SELL produced was the short
        # suggestion above, on the *entry* field. Mirrors the wording
        # `signal_generator` uses so the two paths read alike.
        return (
            f"Exit at ${price:.2f} (current) or limit near ${price * 1.005:.2f}. "
            f"No position — no action; this is not a short signal."
        )
    return None


def _build_explanation(
    ticker: str, output: dict, feat: dict, risk: dict, gate: dict | None = None
) -> str:
    signal    = output.get("signal", "HOLD")
    conviction = output.get("conviction", "LOW")
    thesis    = output.get("thesis", "")
    score     = feat.get("composite_score", 0.5)
    rsi       = feat.get("rsi_14")
    macd_bull = feat.get("macd_bullish")
    tech_s    = feat.get("technical_score", 0.5)
    fund_s    = feat.get("fundamental_score", 0.5)
    sent_s    = feat.get("sentiment_score", 0.5)
    macro_s   = feat.get("macro_score", 0.5)

    rsi_str  = f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A"
    macd_str = "MACD↑" if macd_bull else ("MACD↓" if macd_bull is False else "")

    indicators = " | ".join(filter(None, [rsi_str, macd_str]))
    scores_str = f"tech={tech_s:.2f} fund={fund_s:.2f} sent={sent_s:.2f} macro={macro_s:.2f}"

    text = (
        f"{ticker} → {signal} ({conviction}) | score={score:.2f} | "
        f"Risk={risk['risk_level']} ({risk['risk_score']:.1f}/10) | "
        f"{indicators} | [{scores_str}] | {thesis}"
    )

    # A refused BUY has to say so here. This string is what the ticker page
    # prints when the model wrote no thesis, what the report export carries, and
    # what a reader compares against the gate panel — and a HOLD that silently
    # drops the model's BUY reads as agreement between the two.
    if gate and gate.get("overridden") and gate.get("reason"):
        text += f" | Gate: {gate['reason']}"

    return text
