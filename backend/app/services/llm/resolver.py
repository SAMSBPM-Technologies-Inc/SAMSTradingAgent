"""
Which key answers this call, and what happens when it does not.

Two jobs. Build the ordered candidate list for a (user, role), and walk it.

**The server's own key is last, for whoever is entitled to reach it.** It is
appended rather than offered as a choice: it belongs to the deployment, not to
the user, so it cannot be reordered, relabelled, or deleted from a profile —
and on a single-trader deployment with one server key, the behaviour is
identical to before this package existed.

`allow_server_key=False` withholds it, and that is what makes the PRO tier's
economics real: an account that pays for its own tokens must not silently fall
through to the operator's key when it has configured nothing, or when its own
key rate-limits mid-dossier. The default stays True, so every caller that has
no user behind it — the pipeline's analyst call, which writes one shared
`stocks_signals` document per ticker and belongs to the deployment however it
was triggered — is unchanged. Only `research/dossier._resolve_chains` passes it,
because that is the one path resolved per user.

**The walk stops on a failure that retrying cannot fix.** `ErrorKind` carries
that judgement (see `base.py`); nothing here re-derives it. The distinction
that matters in practice: a rate-limited key should fall through, and a schema
the provider rejected should not — spending a second key to reproduce our own
400 costs twice as much and buries the real error under an identical one.

**Every attempt is recorded, including the ones that worked.** A chain that
quietly succeeded on its third key is indistinguishable from one that succeeded
on its first unless the misses are kept, and "why is my key not being used" is
otherwise a question nobody can answer.
"""
from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.services.encryption import decrypt
from app.services.llm.anthropic_client import AnthropicAdapter
from app.services.llm.base import Attempt, Candidate, ChainOutcome, ErrorKind, LLMResult
from app.services.llm.google_client import GoogleAdapter
from app.services.llm.openai_client import OpenAIAdapter
from app.services.llm.registry import default_model, get_provider
from app.utils.logger import get_logger

logger = get_logger(__name__)

_ADAPTERS: dict[str, Any] = {
    "anthropic": AnthropicAdapter(),
    "openai": OpenAIAdapter(),
    "google": GoogleAdapter(),
}


def adapter_for(provider: str) -> Optional[Any]:
    return _ADAPTERS.get((provider or "").lower())


def server_candidate(role: str) -> Optional[Candidate]:
    """
    The deployment's own key, as the last link in every chain.

    `key_id` is None precisely so nothing can report a failure of this key
    against a user's profile — it is not theirs and they cannot fix it.
    """
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        return None
    model = (
        settings.research_orchestrator_model if role == "orchestrator"
        else settings.analyst_model if role == "analyst"
        else settings.research_specialist_model
    )
    return Candidate(provider="anthropic", model=model, api_key=api_key, key_id=None)


def build_chain(llm_settings: Optional[dict], role: str,
                *, allow_server_key: bool = True) -> list[Candidate]:
    """
    The ordered candidates for one role, user keys first and the server last.

    A key that cannot be decrypted is skipped rather than raising: one corrupt
    entry — a rotated `ENCRYPTION_KEY`, a hand-edited document — must not take
    down every other key the user configured, and the chain has somewhere else
    to go by construction.

    `allow_server_key=False` drops that last link. The chain can then come back
    empty, which `complete_with_chain` reports as a configuration failure rather
    than a model one — but callers should refuse earlier than that where they
    can, so the user hears "add a key" instead of "the model did not answer".
    `POST /research/{ticker}` does exactly that.
    """
    chain: list[Candidate] = []
    settings = llm_settings or {}
    keys = {str(k.get("id")): k for k in (settings.get("keys") or []) if k.get("id")}
    assignments = (settings.get("roles") or {}).get(role) or []

    for entry in assignments:
        key_id = str(entry.get("key_id") or "")
        stored = keys.get(key_id)
        if not stored:
            continue
        provider = str(stored.get("provider") or "")
        if get_provider(provider) is None:
            logger.warning("llm_unknown_provider", provider=provider, key_id=key_id)
            continue
        try:
            api_key = decrypt(str(stored.get("ciphertext") or ""))
        except Exception as exc:
            logger.warning("llm_key_undecryptable", key_id=key_id, error=str(exc))
            continue
        model = str(entry.get("model") or "") or default_model(provider, role) or ""
        if not model:
            continue
        chain.append(Candidate(provider=provider, model=model,
                               api_key=api_key, key_id=key_id))

    if allow_server_key:
        fallback = server_candidate(role)
        if fallback is not None:
            chain.append(fallback)
    return chain


async def complete_with_chain(
    chain: list[Candidate],
    *,
    evidence_block: str,
    system_prompt: str,
    task: str,
    schema: dict,
    effort: str,
    extended_thinking: bool,
    max_tokens: int,
    label: str = "agent",
    adapters: Optional[dict] = None,
) -> ChainOutcome:
    """
    Try each candidate in order; return the first success and every attempt.

    `adapters` overrides the provider map for this call only. It exists for the
    injected-client path in `run_agent`, and it is a parameter rather than a
    swapped module global on purpose: a dossier fans four agents out under
    `asyncio.gather`, so anything that mutates shared state for the duration of
    a call is a race waiting for the day two agents hold different adapters.

    An empty chain is a configuration failure rather than a model failure, and
    is reported as one — this happens only when a user has configured nothing
    *and* the deployment has no server key, which is a state somebody has to
    have created deliberately.
    """
    registry = adapters if adapters is not None else _ADAPTERS
    attempts: list[Attempt] = []
    last: Optional[LLMResult] = None

    if not chain:
        result = LLMResult(
            provider="none", model="none",
            error="no model configured for this role and no server key available",
            error_kind=ErrorKind.AUTH,
        )
        return ChainOutcome(result=result, attempts=attempts)

    for candidate in chain:
        adapter = registry.get((candidate.provider or "").lower())
        if adapter is None:
            attempts.append(Attempt(
                provider=candidate.provider, model=candidate.model,
                key_id=candidate.key_id, ok=False,
                error="no adapter", error_kind=ErrorKind.INVALID_REQUEST,
            ))
            continue

        result = await adapter.complete(
            api_key=candidate.api_key,
            model=candidate.model,
            evidence_block=evidence_block,
            system_prompt=system_prompt,
            task=task,
            schema=schema,
            effort=effort,
            extended_thinking=extended_thinking,
            max_tokens=max_tokens,
        )
        last = result
        attempts.append(Attempt(
            provider=candidate.provider, model=candidate.model,
            key_id=candidate.key_id, ok=result.ok,
            error=result.error, error_kind=result.error_kind,
        ))

        if result.ok:
            if len(attempts) > 1:
                logger.info("llm_chain_recovered", label=label,
                            attempts=len(attempts), **candidate.redacted())
            return ChainOutcome(result=result, attempts=attempts)

        logger.warning(
            "llm_attempt_failed", label=label,
            kind=result.error_kind.value if result.error_kind else None,
            error=result.error, **candidate.redacted(),
        )
        if not result.retryable:
            # Our request, or an answer another provider cannot improve on.
            # Stopping here keeps the real error visible instead of burying it
            # under an identical one from the next key.
            break

    return ChainOutcome(result=last, attempts=attempts)  # type: ignore[arg-type]
