"""
The Google (Gemini) adapter.

Structured output here is `responseSchema` plus `responseMimeType:
application/json`, which enforces server-side like the other two. What differs
is the schema dialect: it is OpenAPI-flavoured and **rejects
`additionalProperties`**, which every object in every agent schema carries.
`registry._google_schema` strips it, and the cost of that is real and worth
naming — the object is no longer closed, so a key we did not ask for could come
back. Every consumer reads named fields and the citation filter runs over the
fields it knows, so this degrades rather than breaks; it is one of the reasons
the dossier records which provider produced each section.

Thinking maps to `thinkingConfig`. There is no hand-placed cache breakpoint,
so the evidence block goes into the system instruction and any caching is
whatever the provider does unprompted.
"""
from __future__ import annotations

import json
from typing import Any

from app.services.llm.anthropic_client import classify_exception
from app.services.llm.base import ErrorKind, LLMResult
from app.services.llm.registry import get_provider
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Our effort levels expressed as a thinking budget, since Gemini takes a token
#: count rather than a level. Deliberately coarse — this is an approximation of
#: an approximation and precision here would be false confidence.
_THINKING_BUDGET = {
    "low": 2048,
    "medium": 8192,
    "high": 16384,
    "xhigh": 24576,
    "max": 32768,
}


class GoogleAdapter:
    name = "google"

    def __init__(self, client_factory: Any = None) -> None:
        self._factory = client_factory

    def _client(self, api_key: str) -> Any:
        if self._factory is not None:
            return self._factory(api_key)
        from google import genai

        return genai.Client(api_key=api_key)

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
        config: dict = {
            "system_instruction": f"{evidence_block}\n\n{system_prompt}",
            "response_mime_type": "application/json",
            "response_schema": spec.normalise_schema(schema) if spec else schema,
            "max_output_tokens": max_tokens,
        }
        if extended_thinking:
            config["thinking_config"] = {
                "thinking_budget": _THINKING_BUDGET.get(effort, 16384),
            }

        try:
            client = self._client(api_key)
            response = await client.aio.models.generate_content(
                model=model, contents=task, config=config,
            )
        except Exception as exc:
            return LLMResult(provider=self.name, model=model, error=str(exc),
                             error_kind=classify_exception(exc))

        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            # A prompt blocked before generation surfaces as no candidates at
            # all, with the reason on the feedback object. That is a refusal,
            # not an empty answer, and is retryable elsewhere.
            feedback = getattr(response, "prompt_feedback", None)
            blocked = getattr(feedback, "block_reason", None) if feedback else None
            if blocked:
                return LLMResult(provider=self.name, model=model,
                                 error=f"blocked: {blocked}",
                                 error_kind=ErrorKind.REFUSAL)
            return LLMResult(provider=self.name, model=model,
                             error="no candidates", error_kind=ErrorKind.UNPARSEABLE)

        finish = str(getattr(candidates[0], "finish_reason", "") or "").upper()
        if "MAX_TOKENS" in finish:
            return LLMResult(provider=self.name, model=model, error="max_tokens",
                             error_kind=ErrorKind.TRUNCATED)
        if "SAFETY" in finish or "BLOCK" in finish or "RECITATION" in finish:
            return LLMResult(provider=self.name, model=model,
                             error=f"blocked: {finish}",
                             error_kind=ErrorKind.REFUSAL)

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            return LLMResult(provider=self.name, model=model,
                             error="empty response", error_kind=ErrorKind.UNPARSEABLE)

        try:
            parsed = json.loads(text)
        except (TypeError, ValueError) as exc:
            return LLMResult(provider=self.name, model=model,
                             error=f"unparseable: {exc}",
                             error_kind=ErrorKind.UNPARSEABLE)

        usage = getattr(response, "usage_metadata", None)
        return LLMResult(
            provider=self.name, model=model, output=parsed,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            cache_read_tokens=getattr(usage, "cached_content_token_count", 0) or 0,
        )
