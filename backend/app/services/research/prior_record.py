"""
Prior Record — this desk's own track record, as evidence
────────────────────────────────────────────────────────
What the agents are told about how they read this name before.

The obvious way to do this is the way TradingAgents does it: keep a log of past
decisions and their outcomes, and paste the last few lessons into the prompt as
prose. That works, and it has one flaw the rest of this module would never
accept — the injected text is unattributable. An agent can quote it, reason
from it, or misremember it, and nothing downstream can tell the difference
between a claim grounded in the record and a claim that merely sounds like one.

So the record enters the same door every other fact does. `Ledger.add` issues an
`O`-prefixed id for each resolved reading, the agents are shown those items in
their evidence block, and any sentence referring to the past record must cite
one — or it is deleted before storage, exactly like an uncited claim about
revenue. A fabricated `O` id is caught by the same audit that catches a
fabricated `F` id.

Three properties are load-bearing:

**Items are `meta=True`.** They describe *our reading*, not the company. That
keeps them out of `substantive_count`, which decides both whether a ticker is
researchable at all and whether an individual agent is worth calling — a name
with a long track record and no financial statements must still fail the
evidence guard, or the fan-out would run four agents over nothing but its own
history.

**Only resolved readings are shown.** A dossier with no `outcome` is a
prediction, not a record, and feeding an agent its own unsettled opinion is a
feedback loop with no ground truth in it.

**Nothing here reaches the conviction anchor.** `dim.derived_conviction` is
computed from company data alone and the synthesiser is clamped to +/-15 of it.
The record can temper a reading; it can never manufacture one. That is the same
rule the veto follows, and for the same reason: a mechanism that can only
subtract fails safe when it is wrong.
"""
from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.db import COLL_DOSSIERS, get_db
from app.services.research.evidence import Ledger
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: The prefix these items are issued under. Single letter and non-numeric, so
#: `Ledger.by_prefix`'s trailing-digit strip resolves it unambiguously.
PREFIX = "O"


def _pct(value: Any) -> Optional[str]:
    if not isinstance(value, (int, float)):
        return None
    return f"{value:+.1%}"


def _verdict_phrase(outcome: dict) -> str:
    """
    How the call is scored, in words, including when it is not scored.

    An ungraded reading must not read as a miss. NEUTRAL declined to take a
    side and an unmeasurable window has no side to take, and an agent shown
    "wrong" for either would be learning from a fact that is not one.
    """
    correct = outcome.get("assessment_correct")
    if correct is True:
        return "the call was right on alpha"
    if correct is False:
        return "the call was wrong on alpha"
    if outcome.get("alpha") is None:
        return "not gradeable — the benchmark could not be read for that window"
    return "not graded — the reading declined to take a side"


def _summarise(doc: dict, *, same_ticker: bool) -> Optional[str]:
    outcome = doc.get("outcome") or {}
    ret = _pct(outcome.get("return"))
    if ret is None:
        return None

    parts = [f"read {outcome.get('assessment') or 'UNSPECIFIED'}"]
    conviction = outcome.get("research_conviction")
    if isinstance(conviction, (int, float)):
        parts.append(f"at research conviction {conviction:.0f}/100")

    horizon = outcome.get("horizon_days")
    tail = f"over the next {horizon} days the name returned {ret}" if horizon \
        else f"the name returned {ret}"
    excess = _pct(outcome.get("alpha"))
    if excess is not None:
        tail += f", {excess} against {outcome.get('benchmark_ticker') or 'the benchmark'}"
    parts.append(tail)
    parts.append(_verdict_phrase(outcome))

    text = "; ".join(parts)
    reflection = outcome.get("reflection") or {}
    lesson = reflection.get("lesson")
    if lesson:
        # The lesson was itself citation-filtered when it was written, so what
        # is carried forward here is prose that survived the same check the
        # agents' own output has to survive.
        text += f". Lesson recorded at the time: {lesson}"
    if not same_ticker:
        text = f"[different company] {text}"
    return text


def add_prior_record(ledger: Ledger, ticker: str, resolved: list[dict]) -> dict:
    """
    Add one `O` item per resolved reading and report what was added.

    `resolved` is ordered newest first and may mix tickers; same-name readings
    are added before cross-name ones so the ids read in order of relevance.
    """
    ticker = ticker.upper()
    same = [d for d in resolved if str(d.get("ticker", "")).upper() == ticker]
    cross = [d for d in resolved if str(d.get("ticker", "")).upper() != ticker]

    added_same = added_cross = 0
    for doc in same:
        text = _summarise(doc, same_ticker=True)
        if text and ledger.add(
            PREFIX, f"This desk's prior reading of {ticker}", text,
            source="research_dossiers", as_of=str(doc.get("as_of") or ""), meta=True,
        ):
            added_same += 1

    for doc in cross:
        other = str(doc.get("ticker", "")).upper()
        text = _summarise(doc, same_ticker=False)
        if text and ledger.add(
            PREFIX, f"This desk's prior reading of {other}", text,
            source="research_dossiers", as_of=str(doc.get("as_of") or ""), meta=True,
        ):
            added_cross += 1

    return {
        "same_ticker": added_same,
        "cross_ticker": added_cross,
        "available": added_same + added_cross > 0,
    }


async def load_resolved(ticker: str,
                        user_id: Optional[str] = None) -> list[dict]:
    """
    Recent settled readings: this name first, then a few from other names.

    Cross-ticker entries are carried for the reason TradingAgents carries them
    — a mistake in how a kind of business was read tends to repeat across
    names, and a desk that only ever reviews the ticker in front of it never
    sees the pattern. They are labelled as another company in the rendered item
    so an agent cannot mistake one for history of the name it is working.

    **Scoped to one reader.** Every item this returns is rendered into the
    ledger as citable `O` evidence describing how "this desk" read a name and
    what happened. The moment the desk is a different person that sentence is
    false: the reading was made on someone else's models, graded against
    someone else's positions, and injecting it would both misattribute a
    judgement and leak one user's record into another's prompt. Unscoped, this
    function is a privacy bug wearing a correctness bug's clothes.

    A `user_id` of None reads the legacy shared series — the dossiers written
    before this was per-user, which carry no owner — and nothing else.

    Never raises. A database hiccup here must degrade to "no prior record",
    which is the state every dossier written before this existed is in anyway.
    """
    settings = get_settings()
    n_same = max(0, int(settings.research_memory_same_ticker))
    n_cross = max(0, int(settings.research_memory_cross_ticker))
    if n_same == 0 and n_cross == 0:
        return []

    ticker = ticker.upper()
    projection = {"_id": 0, "ticker": 1, "as_of": 1, "outcome": 1}
    try:
        db = await get_db()
        # `user_id: None` matches both an explicit null and a missing field,
        # which is exactly what the pre-per-user documents have.
        base = {"outcome": {"$ne": None},
                "user_id": str(user_id) if user_id else None}
        same = await (
            db[COLL_DOSSIERS].find({**base, "ticker": ticker}, projection)
            .sort("generated_at", -1).limit(n_same).to_list(length=n_same)
        ) if n_same else []
        cross = await (
            db[COLL_DOSSIERS].find({**base, "ticker": {"$ne": ticker}}, projection)
            .sort("generated_at", -1).limit(n_cross).to_list(length=n_cross)
        ) if n_cross else []
    except Exception as exc:
        logger.warning("research_prior_record_read_failed",
                       ticker=ticker, error=str(exc))
        return []

    return list(same) + list(cross)


MEMORY_PROMPT = """
YOUR OWN TRACK RECORD:
Some evidence ids may carry the prefix [On]. Those are not facts about the \
company — they record how this desk read this name (or, where marked, another \
name) before, and what happened afterwards, measured against the benchmark.

Treat them as evidence about the reading, not about the business. They are \
citable exactly like any other id and subject to the same rule: refer to the \
prior record and you must cite it, or the sentence is deleted.

Two failure modes to avoid, and the second is the more likely one. Do not \
ignore a repeated, specific mistake — that is what these items are for. And do \
not correct a score you cannot otherwise justify: a past miss is a reason to \
look harder at the evidence in front of you, never a reason on its own to move \
a number the current evidence does not support. If the record changes your \
view, say which item did and why.
"""
