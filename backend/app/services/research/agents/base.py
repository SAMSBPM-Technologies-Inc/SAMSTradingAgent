"""
The shared agent call.

Each research "agent" is one scoped Anthropic request: its own system prompt,
its own slice of the evidence ledger, its own JSON schema. There is no tool
loop and no sub-agent machinery — the value of the decomposition is that each
agent's output can be checked on its own, that the four can run at once, and
that the cheap ones can run on a cheaper model.

Three things differ from the single analyst call this replaces, and each fixes
something specific:

**Structured outputs, not fence-stripping.** The old call asked for JSON in the
prompt, then stripped markdown fences with two regexes and hoped `json.loads`
worked; a truncated response failed to parse and wasted the entire call. The
schema is enforced server-side here, so the shape is a guarantee rather than an
instruction the model may or may not have followed.

**A refusal is checked before the content is read.** Current models can return
HTTP 200 with `stop_reason: "refusal"` and an empty content list. Code that
reads `content[0]` unconditionally raises an unrelated-looking error on that
path.

**One agent failing is not the dossier failing.** Every call is wrapped, and a
failure returns None so the orchestrator can render that section as absent. A
research report missing its news section is worth more than no report.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.llm.anthropic_client import AnthropicAdapter
from app.services.llm.base import Candidate
from app.services.llm.resolver import complete_with_chain

from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Generous ceiling: only tokens actually generated are billed, and too low is
#: what costs — a truncated response fails the schema and wastes the call.
#: Kept under the streaming threshold so these stay simple request/response.
MAX_TOKENS = 16000


@dataclass(frozen=True)
class AgentSpec:
    """Everything that makes one agent different from another."""

    name: str
    #: Evidence-id prefixes this agent is shown. Scoping is not just about
    #: tokens: an agent shown only what it needs cannot wander into another's
    #: territory and produce a second, quietly different reading of it.
    prefixes: tuple[str, ...]
    system_prompt: str
    task: str
    schema: dict
    #: "orchestrator" for the judgment-heavy roles, "specialist" for the rest.
    model_role: str = "specialist"


@dataclass
class AgentResult:
    """
    What one agent produced, or why it did not.

    `skipped` and a failure are deliberately different states. A failure means
    the call broke and the perspective is missing — the reader should treat the
    dossier as incomplete. A skip means there was nothing in this agent's slice
    of the evidence worth asking about, which is itself a finding about the
    data rather than a fault. Collapsing the two would make a cold ticker look
    like a broken one.
    """

    name: str
    output: Optional[dict]
    error: Optional[str] = None
    skipped: bool = False
    #: Why it was skipped, shown to the reader.
    skip_reason: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    #: Which model actually answered. Not bookkeeping: a dossier written by one
    #: model cannot be pooled with one written by another, and the research
    #: calibration arm exists to compare exactly those. Absent on a skip, since
    #: no model was asked.
    provider: Optional[str] = None
    model: Optional[str] = None
    #: Every link the chain tried, successes and failures alike. A run that
    #: quietly succeeded on its third key looks identical to one that succeeded
    #: on its first unless the misses are kept.
    attempts: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.output is not None

    @property
    def failed(self) -> bool:
        return self.output is None and not self.skipped


async def run_agent(client: Any, spec: AgentSpec, evidence_block: str,
                    model: str, effort: str,
                    extended_thinking: bool = True,
                    chain: Optional[list] = None) -> AgentResult:
    """
    Run one agent and return its parsed output, or a recorded failure.

    The request itself now lives in `services/llm/` — one adapter per provider
    behind one protocol — so a trader can put a different model on a different
    agent. What did not move is the shape of the ask, and two properties of it
    are worth restating because they are easy to lose in an adapter:

    The evidence block is the FIRST system block and, on Anthropic, carries the
    cache breakpoint. Caching is a prefix match, so putting the shared material
    first is what makes it cacheable at all — the previous analyst put its
    breakpoint on a ~200-token system prompt, well under the minimum cacheable
    prefix, and by its own admission never got a hit. No other provider lets us
    place that breakpoint by hand, so the same dossier costs more there; the
    coverage summary records which provider answered rather than letting the
    difference show up only on a bill.

    Note the concurrency trade-off this leaves: a cache entry only becomes
    readable once the first response has started, so four agents fired at once
    all miss it. The wall-clock saving is worth more than the read here, and
    the synthesiser — which runs after them — does get the hit.

    `client` and `chain` are two ways in, and only one is used at a time. A
    `chain` is the real path: an ordered list of candidates resolved from the
    user's configured keys with the server's own appended last. A bare `client`
    is the injection seam the orchestration tests have always used, and it
    still means exactly what it did — this one object, over Anthropic, with the
    model named in the call. Keeping both is what makes this change provably
    behaviour-neutral for a deployment that has configured nothing.
    """
    if chain is None:
        # Injected-client path: one candidate, this client, Anthropic's shape.
        # The api_key is unused because the factory ignores it — the caller has
        # already built an authenticated client.
        candidates = [Candidate(provider="anthropic", model=model,
                                api_key="", key_id=None)]
        adapters = {"anthropic": AnthropicAdapter(client_factory=lambda _k: client)}
    else:
        candidates = chain
        adapters = None

    outcome = await complete_with_chain(
        candidates,
        evidence_block=evidence_block,
        system_prompt=spec.system_prompt,
        task=spec.task,
        schema=spec.schema,
        effort=effort,
        extended_thinking=extended_thinking,
        max_tokens=MAX_TOKENS,
        label=spec.name,
        adapters=adapters,
    )

    result = outcome.result
    if not result.ok:
        logger.warning(
            "research_agent_call_failed", agent=spec.name,
            kind=result.error_kind.value if result.error_kind else None,
            error=result.error,
        )
        return AgentResult(
            name=spec.name, output=None, error=result.error,
            provider=result.provider, model=result.model,
            attempts=[a.__dict__ for a in outcome.attempts],
        )

    agent_result = AgentResult(
        name=spec.name,
        output=result.output,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens,
        provider=result.provider,
        model=result.model,
        attempts=[a.__dict__ for a in outcome.attempts],
    )
    logger.info(
        "research_agent_done",
        agent=spec.name, provider=result.provider, model=result.model,
        input_tokens=agent_result.input_tokens,
        output_tokens=agent_result.output_tokens,
        cache_read=agent_result.cache_read_tokens,
    )
    return agent_result


def _first_text_block(message: Any) -> str:
    """
    The response text, skipping thinking blocks.

    Adaptive thinking puts one or more thinking blocks ahead of the text, so
    indexing content[0] gets reasoning rather than the answer.
    """
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return (getattr(block, "text", "") or "").strip()
    return ""


def citation_rules(prefixes: tuple[str, ...]) -> str:
    """
    The shared citation contract, appended to every agent's system prompt.

    Spelled out rather than implied because the enforcement is unforgiving:
    an uncited sentence is deleted before storage, not flagged. A model that
    does not know that will write a good uncited paragraph and see it vanish.
    """
    visible = ", ".join(f"[{p}n]" for p in prefixes)
    return f"""
CITATION RULES — these are enforced mechanically, not by review:
- Every factual claim must cite at least one evidence id in square brackets,
  exactly as the id appears in the EVIDENCE block, e.g. [F3] or [V1].
- The ids available to you begin with: {visible}.
- Any sentence you write that cites no id is DELETED before the report is
  stored. Any sentence citing an id that does not appear in the EVIDENCE block
  is also deleted — an invented citation is worse than none, because it
  survives the check a reader would make.
- Do not restate a number the evidence does not contain. If the evidence does
  not support a point you consider important, say that the data is absent and
  cite the item that says so, rather than reasoning from memory.
- Write plainly. No preamble, no restating the question.
"""
