"""
The OpenAI adapter.

Strict structured outputs (`response_format.json_schema` with `strict: true`)
are the reason this provider is eligible at all. Its two hard requirements —
every property listed in `required`, and `additionalProperties: false` — are
already satisfied by every schema in `research/agents/specs.py`, which
`_schema()` there emits by construction. So the schemas cross unchanged and
`registry._openai_schema` is an identity.

Two mappings are approximations and are commented as such at the point they
happen: reasoning effort has three levels here against Anthropic's five, and
there is no hand-placed cache breakpoint — the evidence block still goes first
in the system message so any automatic prefix caching has the best chance of
catching it, but nothing is guaranteed and the dossier costs more.
"""
from __future__ import annotations

import json
from typing import Any

from app.services.llm.anthropic_client import classify_exception
from app.services.llm.base import ErrorKind, LLMResult
from app.services.llm.registry import get_provider, map_effort
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OpenAIAdapter:
    name = "openai"

    def __init__(self, client_factory: Any = None) -> None:
        self._factory = client_factory

    def _client(self, api_key: str) -> Any:
        if self._factory is not None:
            return self._factory(api_key)
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key)

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
        # Evidence first, prompt second — the same ordering Anthropic needs for
        # its breakpoint. Here it buys only whatever automatic prefix caching
        # the provider does on its own, which is not something to depend on.
        system = f"{evidence_block}\n\n{system_prompt}"

        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": task},
            ],
            "max_completion_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_output",
                    "strict": True,
                    "schema": spec.normalise_schema(schema) if spec else schema,
                },
            },
        }
        if extended_thinking:
            # Three levels against our five. `map_effort` clamps rather than
            # errors — a dossier that refuses to run because `xhigh` has no
            # exact twin here is a worse outcome than one at this provider's
            # ceiling.
            kwargs["reasoning_effort"] = map_effort(self.name, effort)

        try:
            response = await self._client(api_key).chat.completions.create(**kwargs)
        except Exception as exc:
            return LLMResult(provider=self.name, model=model, error=str(exc),
                             error_kind=classify_exception(exc))

        choice = (getattr(response, "choices", None) or [None])[0]
        if choice is None:
            return LLMResult(provider=self.name, model=model,
                             error="no choices in response",
                             error_kind=ErrorKind.UNPARSEABLE)

        finish = getattr(choice, "finish_reason", None)
        if finish == "length":
            return LLMResult(provider=self.name, model=model, error="max_tokens",
                             error_kind=ErrorKind.TRUNCATED)
        if finish == "content_filter":
            return LLMResult(provider=self.name, model=model, error="content_filter",
                             error_kind=ErrorKind.REFUSAL)

        message = getattr(choice, "message", None)
        # A refusal here is a first-class field rather than a stop reason, but
        # it means the same thing and maps to the same retryable kind.
        refusal = getattr(message, "refusal", None) if message else None
        if refusal:
            return LLMResult(provider=self.name, model=model,
                             error=f"refusal: {refusal}",
                             error_kind=ErrorKind.REFUSAL)

        text = (getattr(message, "content", None) or "").strip() if message else ""
        if not text:
            return LLMResult(provider=self.name, model=model,
                             error="empty response", error_kind=ErrorKind.UNPARSEABLE)

        try:
            parsed = json.loads(text)
        except (TypeError, ValueError) as exc:
            return LLMResult(provider=self.name, model=model,
                             error=f"unparseable: {exc}",
                             error_kind=ErrorKind.UNPARSEABLE)

        usage = getattr(response, "usage", None)
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        return LLMResult(
            provider=self.name, model=model, output=parsed,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cache_read_tokens=cached,
        )
