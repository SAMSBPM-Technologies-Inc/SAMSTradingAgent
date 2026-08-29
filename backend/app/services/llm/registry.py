"""
The providers a trader may choose, and what each one can actually do.

Named providers only. A user-supplied `base_url` would make this list
open-ended and is deliberately not offered: a URL the server will POST to,
chosen by a user, is a server-side request forgery vector, and schema
enforcement on an arbitrary endpoint cannot be verified — which matters more
here than anywhere else, because the whole research module assumes the object
it gets back has the shape it asked for.

**`enforces_schema` is a gate, not a hint.** `analyst.py` had its
fence-stripping regexes removed on purpose when it moved to structured
outputs; a provider that cannot constrain output server-side would put them
straight back, and the failure would show up as a parse error weeks later
rather than at the point somebody chose the provider. Every provider listed
here enforces schemas, and one that does not is not added.

**Schema legality is per provider, and this is where it is handled.** The
agent schemas in `research/agents/specs.py` were already narrowed once for
Anthropic — numeric bounds on an integer are rejected outright with a 400, not
ignored, and that failure took out three agents identically. Gemini's
`responseSchema` has a different and narrower set of rules again. So each
provider owns a `normalise_schema` and `tests/test_research_schemas.py` grows a
legality check per provider rather than one global one.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Optional

#: The role a call plays, which is what a user assigns a model to. These are
#: the split the code already makes (`AgentSpec.model_role`) plus the analyst,
#: which sits on the fast path and is a separate choice from the research
#: agents — it runs far more often and a trader may reasonably want it cheaper.
ROLES: tuple[str, ...] = ("orchestrator", "specialist", "analyst")


def _strip_keys(schema: Any, unsupported: frozenset[str]) -> Any:
    """Recursively drop keys a provider rejects, leaving structure intact."""
    if isinstance(schema, dict):
        return {
            k: _strip_keys(v, unsupported)
            for k, v in schema.items()
            if k not in unsupported
        }
    if isinstance(schema, list):
        return [_strip_keys(v, unsupported) for v in schema]
    return schema


def _anthropic_schema(schema: dict) -> dict:
    """
    Anthropic takes our schemas as written.

    They were authored against its structured-outputs rules — closed objects,
    every property required, no numeric or length bounds — so there is nothing
    to normalise. Kept as an explicit identity rather than a `None` special
    case so the call site has no branch.
    """
    return copy.deepcopy(schema)


def _openai_schema(schema: dict) -> dict:
    """
    OpenAI strict mode wants exactly what we already produce.

    `additionalProperties: false` and every property listed in `required` are
    its two hard requirements, and `_schema()` in `specs.py` emits both — the
    schemas are strict-legal unchanged. Numeric bounds would be accepted here
    but are already absent for Anthropic's sake, and adding them back per
    provider would mean two schemas to keep in step.
    """
    return copy.deepcopy(schema)


#: Gemini's `responseSchema` is OpenAPI-flavoured and rejects these outright
#: rather than ignoring them. `additionalProperties` is the one that matters:
#: it appears on every object in every agent schema.
_GEMINI_UNSUPPORTED = frozenset({"additionalProperties", "$schema", "const"})


def _google_schema(schema: dict) -> dict:
    """
    Strip what Gemini rejects, and accept what that costs.

    Losing `additionalProperties: false` means the schema no longer *closes*
    the object — Gemini may in principle return a key we did not ask for. That
    is survivable where a rejected request is not: every consumer of these
    objects reads named fields and ignores the rest, and the citation filter
    runs over the fields it knows regardless. It is still a real weakening of
    the contract and is why the coverage summary records which provider
    produced a section.
    """
    return _strip_keys(copy.deepcopy(schema), _GEMINI_UNSUPPORTED)


@dataclass(frozen=True)
class Provider:
    """One named provider and the honest limits of what it gives us."""

    name: str
    label: str
    #: Non-negotiable. A provider that cannot constrain output server-side is
    #: not listed at all; the flag exists so the gate is greppable rather than
    #: implied by absence.
    enforces_schema: bool
    #: Whether a cache breakpoint can be placed by hand on the evidence block.
    #: Only Anthropic offers this, and it is why one ledger across four agents
    #: is affordable there. Elsewhere the same dossier simply costs more —
    #: a degradation the coverage summary reports rather than hides.
    manual_prompt_caching: bool
    #: Effort levels this provider accepts, in ascending order. Ours is
    #: Anthropic-shaped (`low`..`max`); adapters map onto their nearest.
    effort_levels: tuple[str, ...]
    #: What a key looks like, for the fingerprint shown in the profile. Purely
    #: cosmetic — validation is a real call, never a regex.
    key_prefix: str
    #: Sensible starting models per role. A user may override any of them; this
    #: is what they get before they do.
    default_models: dict[str, str]
    normalise_schema: Callable[[dict], dict]


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        name="anthropic",
        label="Anthropic",
        enforces_schema=True,
        manual_prompt_caching=True,
        effort_levels=("low", "medium", "high", "xhigh", "max"),
        key_prefix="sk-ant-",
        default_models={
            "orchestrator": "claude-opus-5",
            "specialist": "claude-sonnet-5",
            "analyst": "claude-sonnet-5",
        },
        normalise_schema=_anthropic_schema,
    ),
    "openai": Provider(
        name="openai",
        label="OpenAI",
        enforces_schema=True,
        manual_prompt_caching=False,
        effort_levels=("low", "medium", "high"),
        key_prefix="sk-",
        default_models={
            "orchestrator": "gpt-5.5",
            "specialist": "gpt-5.4-mini",
            "analyst": "gpt-5.4-mini",
        },
        normalise_schema=_openai_schema,
    ),
    "google": Provider(
        name="google",
        label="Google",
        enforces_schema=True,
        manual_prompt_caching=False,
        effort_levels=("low", "medium", "high"),
        key_prefix="AIza",
        default_models={
            "orchestrator": "gemini-3-pro",
            "specialist": "gemini-3-flash",
            "analyst": "gemini-3-flash",
        },
        normalise_schema=_google_schema,
    ),
}


def get_provider(name: str) -> Optional[Provider]:
    return PROVIDERS.get((name or "").lower())


def fingerprint(provider: str, api_key: str) -> str:
    """
    A stable, non-reversible label for a stored key.

    Shows the provider's prefix and the last four characters — enough for a
    user to tell two of their own keys apart, and not enough to be a key. The
    middle is never stored in this form and never rendered.
    """
    tail = (api_key or "")[-4:]
    spec = get_provider(provider)
    head = spec.key_prefix if spec else ""
    return f"{head}…{tail}" if tail else f"{head}…"


def default_model(provider: str, role: str) -> Optional[str]:
    spec = get_provider(provider)
    if spec is None:
        return None
    return spec.default_models.get(role)


def map_effort(provider: str, effort: str) -> str:
    """
    Our effort level, expressed in the provider's own vocabulary.

    Clamps rather than errors. `xhigh` and `max` exist on Anthropic and not on
    the others, and a dossier that refuses to run because the configured effort
    has no exact twin is a worse outcome than one that runs at that provider's
    ceiling. The mapping is an approximation and is meant to be read as one.
    """
    spec = get_provider(provider)
    if spec is None or not spec.effort_levels:
        return effort
    if effort in spec.effort_levels:
        return effort
    return spec.effort_levels[-1]
