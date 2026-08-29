"""
One model call, one shape, whichever provider answers it.

Everything above this package assumes a single call contract: send an evidence
block, a system prompt, a task and a JSON schema; get a parsed object back or a
recorded reason why not. That contract was previously written directly against
the Anthropic SDK inside `run_agent`, which meant the trader had no say in
which model read their positions.

Two things in here carry the weight.

**`ErrorKind` is the whole fallback policy.** A failure string is enough to log
and useless to decide on: "should the next key be tried?" is a different
question for a rate limit than for a schema the server rejected. Falling back
on a malformed request would spend a second key reproducing our own bug, at
double the cost and with the real error buried under the second one. So every
adapter classifies its failure into this enum and the resolver branches on
nothing else.

**A refusal is retryable; a bad request is not.** Those are the two ends of the
policy and the reasoning is asymmetric. A refusal is a property of the model —
another model may well answer, and for a dossier that is worth trying. A 400
naming a field is a property of *our* request and will fail identically
everywhere.

`provider` and `model` ride on every result, success or failure. A dossier that
does not record which model wrote it cannot be compared with one that was
written by a different model, and the research calibration arm exists to make
exactly that comparison.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol


class ErrorKind(str, Enum):
    """
    Why a call failed, in the only terms the fallback policy cares about.

    Ordered roughly by whose fault it is: the first five are the provider's or
    the network's and are worth retrying elsewhere; the last three are ours or
    the model's own considered output and are not.
    """

    #: Bad or revoked key. Retry elsewhere, and tell the user this key is dead —
    #: it will not fix itself and every future call pays the same latency.
    AUTH = "auth"
    #: 429. Retry elsewhere.
    RATE_LIMIT = "rate_limit"
    #: 5xx / capacity. Retry elsewhere.
    OVERLOADED = "overloaded"
    #: Network or deadline. Retry elsewhere.
    TIMEOUT = "timeout"
    #: The model declined. Retryable elsewhere on purpose: a refusal is a
    #: property of the model, not of the request, and another model may answer.
    REFUSAL = "refusal"
    #: Hit the output ceiling. NOT retried — the schema makes a truncated
    #: response invalid rather than short, and the same ceiling applies on the
    #: next provider. The fix is `max_tokens` or a lower effort, and silently
    #: burning another key hides which one is needed.
    TRUNCATED = "truncated"
    #: The provider rejected the request itself — usually the schema. Our bug.
    #: Never retried: it will fail identically everywhere, and the second
    #: failure buries the first.
    INVALID_REQUEST = "invalid_request"
    #: HTTP 200 with something that is not the object we asked for. Not
    #: retried, for the same reason as INVALID_REQUEST — if schema enforcement
    #: did not hold, the next provider's enforcement is not the fix.
    UNPARSEABLE = "unparseable"


#: Failures worth spending the next key on. Everything outside this set stops
#: the chain, because trying again cannot change the answer.
RETRYABLE: frozenset[ErrorKind] = frozenset({
    ErrorKind.AUTH,
    ErrorKind.RATE_LIMIT,
    ErrorKind.OVERLOADED,
    ErrorKind.TIMEOUT,
    ErrorKind.REFUSAL,
})


@dataclass
class LLMResult:
    """What one model call produced, or why it did not."""

    provider: str
    model: str
    output: Optional[dict] = None
    error: Optional[str] = None
    error_kind: Optional[ErrorKind] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.output is not None

    @property
    def retryable(self) -> bool:
        return self.error_kind in RETRYABLE


@dataclass
class Attempt:
    """
    One link in a fallback chain, kept whether it succeeded or not.

    The failures are the point. A chain that silently succeeded on its third
    key looks identical to one that succeeded on its first unless the misses
    are recorded, and "my key is not being used" is otherwise unanswerable.
    """

    provider: str
    model: str
    key_id: Optional[str]
    ok: bool
    error: Optional[str] = None
    error_kind: Optional[ErrorKind] = None


@dataclass(frozen=True)
class Candidate:
    """A resolved (key, provider, model) the chain may try."""

    provider: str
    model: str
    api_key: str
    #: None for the server's own key, which belongs to no user and cannot be
    #: reported against one in the profile.
    key_id: Optional[str] = None

    def redacted(self) -> dict:
        """Loggable form. The key never appears in it."""
        return {"provider": self.provider, "model": self.model,
                "key_id": self.key_id or "server"}


class LLMClient(Protocol):
    """
    One provider adapter.

    Deliberately not a chat interface. Every caller in this system wants the
    same thing — a schema-constrained object built from a cached evidence block
    — and narrowing the protocol to that is what makes the adapters small
    enough to reason about.
    """

    name: str

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
        ...


@dataclass
class ChainOutcome:
    """The result of walking a chain, plus every attempt it took to get there."""

    result: LLMResult
    attempts: list[Attempt] = field(default_factory=list)
