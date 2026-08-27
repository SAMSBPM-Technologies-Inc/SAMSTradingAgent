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
from dataclasses import dataclass
from typing import Any, Optional

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

    @property
    def ok(self) -> bool:
        return self.output is not None

    @property
    def failed(self) -> bool:
        return self.output is None and not self.skipped


async def run_agent(client: Any, spec: AgentSpec, evidence_block: str,
                    model: str, effort: str,
                    extended_thinking: bool = True) -> AgentResult:
    """
    Run one agent and return its parsed output, or a recorded failure.

    The evidence block is the FIRST system block and is byte-identical across
    every agent in a dossier, with the cache breakpoint on it. Caching is a
    prefix match, so putting the shared material first is what makes it
    cacheable at all — the previous analyst put its breakpoint on a ~200-token
    system prompt, well under the minimum cacheable prefix, and by its own
    admission never got a hit.

    Note the concurrency trade-off this leaves: a cache entry only becomes
    readable once the first response has started, so four agents fired at once
    all miss it. The wall-clock saving is worth more than the read here, and
    the synthesiser — which runs after them — does get the hit.
    """
    system = [
        {
            "type": "text",
            "text": evidence_block,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": spec.system_prompt},
    ]

    kwargs: dict = {
        "model": model,
        "system": system,
        "messages": [{"role": "user", "content": spec.task}],
        "max_tokens": MAX_TOKENS,
        "output_config": {
            "format": {"type": "json_schema", "schema": spec.schema},
            "effort": effort,
        },
    }
    if extended_thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    else:
        kwargs["thinking"] = {"type": "disabled"}

    try:
        message = await client.messages.create(**kwargs)
    except Exception as exc:
        logger.warning("research_agent_call_failed", agent=spec.name, error=str(exc))
        return AgentResult(name=spec.name, output=None, error=str(exc))

    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        logger.warning("research_agent_refused", agent=spec.name,
                       category=getattr(details, "category", None))
        return AgentResult(name=spec.name, output=None, error="refusal")
    if stop_reason == "max_tokens":
        # The schema constrains the shape, so a truncated response is invalid
        # JSON rather than a short answer. Recorded as its own failure so the
        # fix (raise the ceiling, lower the effort) is obvious from the logs.
        logger.warning("research_agent_truncated", agent=spec.name,
                       max_tokens=MAX_TOKENS)
        return AgentResult(name=spec.name, output=None, error="max_tokens")

    text = _first_text_block(message)
    if not text:
        return AgentResult(name=spec.name, output=None, error="empty response")

    try:
        parsed = json.loads(text)
    except (TypeError, ValueError) as exc:
        logger.warning("research_agent_unparseable", agent=spec.name, error=str(exc))
        return AgentResult(name=spec.name, output=None, error=f"unparseable: {exc}")

    usage = getattr(message, "usage", None)
    result = AgentResult(
        name=spec.name,
        output=parsed,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )
    logger.info(
        "research_agent_done",
        agent=spec.name, model=model,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        cache_read=result.cache_read_tokens,
    )
    return result


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
