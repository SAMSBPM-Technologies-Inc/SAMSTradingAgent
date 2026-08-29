"""
The Anthropic adapter — today's call, moved rather than rewritten.

Every line of the request shape below was already in `run_agent`; the point of
this file is that it is now one implementation of a protocol instead of the
only way to call a model. Behaviour must be identical with a single key
configured, and there is a test that builds a dossier and diffs the stored
document to prove it.

The three things worth not losing in the move:

**The evidence block is the first system block and carries the cache
breakpoint.** Caching is a prefix match, so the shared material has to come
first to be cacheable at all — the analyst this replaced put its breakpoint on
a ~200-token prompt, under the minimum cacheable prefix, and never got a hit.
This is also the capability no other provider gives us by hand.

**A refusal is checked before the content is read.** A model can return HTTP
200 with `stop_reason: "refusal"` and an empty content list; code that indexes
`content[0]` raises something unrelated-looking on that path.

**Truncation is its own failure.** The schema makes a cut-off response invalid
JSON rather than a short answer, so it is worth distinguishing from a parse
failure — the fix is a higher ceiling or a lower effort, and the log should say
which.
"""
from __future__ import annotations

import json
from typing import Any

from app.services.llm.base import ErrorKind, LLMResult
from app.services.llm.registry import get_provider, map_effort
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, client_factory: Any = None) -> None:
        #: Injectable so the orchestration can be tested without the SDK — the
        #: same seam `build_dossier(client=)` already relies on.
        self._factory = client_factory

    def _client(self, api_key: str) -> Any:
        if self._factory is not None:
            return self._factory(api_key)
        import anthropic

        return anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(
        self,
        *,
        api_key: str,
        model: str,
        evidence_block: str,
        system_prompt: str,
        task: str,
        schema: dict,
        effort: str,
        extended_thinking: bool,
        max_tokens: int,
    ) -> LLMResult:
        spec = get_provider(self.name)
        system = [
            {
                "type": "text",
                "text": evidence_block,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": system_prompt},
        ]
        kwargs: dict = {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": task}],
            "max_tokens": max_tokens,
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": spec.normalise_schema(schema) if spec else schema,
                },
                "effort": map_effort(self.name, effort),
            },
        }
        kwargs["thinking"] = (
            {"type": "adaptive"} if extended_thinking else {"type": "disabled"}
        )

        try:
            message = await self._client(api_key).messages.create(**kwargs)
        except Exception as exc:
            return LLMResult(provider=self.name, model=model, error=str(exc),
                             error_kind=classify_exception(exc))

        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "refusal":
            # The category is worth carrying: it is the difference between a
            # model that will refuse this request everywhere and one whose
            # classifier happened to fire, and the chain reports it per attempt.
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            return LLMResult(
                provider=self.name, model=model,
                error=f"refusal: {category}" if category else "refusal",
                error_kind=ErrorKind.REFUSAL,
            )
        if stop_reason == "max_tokens":
            return LLMResult(provider=self.name, model=model, error="max_tokens",
                             error_kind=ErrorKind.TRUNCATED)

        text = _first_text_block(message)
        if not text:
            return LLMResult(provider=self.name, model=model,
                             error="empty response", error_kind=ErrorKind.UNPARSEABLE)

        try:
            parsed = json.loads(text)
        except (TypeError, ValueError) as exc:
            return LLMResult(provider=self.name, model=model,
                             error=f"unparseable: {exc}",
                             error_kind=ErrorKind.UNPARSEABLE)

        usage = getattr(message, "usage", None)
        return LLMResult(
            provider=self.name, model=model, output=parsed,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )


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


def classify_exception(exc: Exception) -> ErrorKind:
    """
    Sort an SDK exception into the one thing the chain needs to know.

    Reads the HTTP status where the SDK exposes one and falls back to the
    message otherwise, because the adapters must not import provider exception
    hierarchies — that would make every provider's package a hard dependency of
    the seam, including for deployments that use none of them.

    An unrecognised failure is classified OVERLOADED rather than
    INVALID_REQUEST, and the asymmetry is deliberate: guessing "transient"
    spends one more key on something that may well succeed, while guessing
    "our bug" abandons a chain that would have worked. The first error is
    cheap and recoverable; the second is a dossier that silently did not get
    built.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int):
        if status in (401, 403):
            return ErrorKind.AUTH
        if status == 429:
            return ErrorKind.RATE_LIMIT
        if status == 408:
            return ErrorKind.TIMEOUT
        if status >= 500:
            return ErrorKind.OVERLOADED
        if status == 400:
            return ErrorKind.INVALID_REQUEST
        if 400 < status < 500:
            return ErrorKind.INVALID_REQUEST

    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return ErrorKind.TIMEOUT
    if "rate limit" in text or "429" in text:
        return ErrorKind.RATE_LIMIT
    if "api key" in text or "unauthor" in text or "authentication" in text:
        return ErrorKind.AUTH
    if "overloaded" in text:
        return ErrorKind.OVERLOADED
    return ErrorKind.OVERLOADED
