"""
Tests for the provider seam.

Every model call in this system used to go through one hardcoded credential and
one hardcoded request shape. The seam lets a trader put a different model on a
different agent — and introduces two ways to get that badly wrong, which is
what this file is about.

**The fallback policy must branch on `ErrorKind` and nothing else.** A rate
limit should spend the next key; a schema the provider rejected should not.
Retrying our own 400 costs twice as much and buries the real error under an
identical one from the next provider, which is strictly worse than failing on
the first.

**The server key is always last and belongs to nobody.** It is the only reason
"user keys pay for everything" does not mean a new account silently gets no
dossiers. It cannot be reordered out, and a failure of it must never be
reported against a user's profile — they did not configure it and cannot fix it.

Run with:  pytest backend/tests -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.llm import registry  # noqa: E402
from app.services.llm.base import (  # noqa: E402
    RETRYABLE, Candidate, ErrorKind, LLMResult,
)
from app.services.llm.resolver import (  # noqa: E402
    build_chain, complete_with_chain, server_candidate,
)


class FakeAdapter:
    """An adapter that returns a scripted result per model name."""

    def __init__(self, script: dict):
        self.script = script
        self.calls: list[str] = []

    async def complete(self, *, api_key, model, **_kw):
        self.calls.append(model)
        outcome = self.script.get(model)
        if outcome is None:
            pytest.fail(f"no scripted outcome for model {model!r}")
        if isinstance(outcome, ErrorKind):
            return LLMResult(provider="fake", model=model,
                             error=outcome.value, error_kind=outcome)
        return LLMResult(provider="fake", model=model, output=outcome)


def chain(*models) -> list[Candidate]:
    return [
        Candidate(provider="fake", model=m, api_key="k", key_id=f"key-{m}")
        for m in models
    ]


def walk(candidates, adapter):
    return asyncio.run(complete_with_chain(
        candidates, evidence_block="E", system_prompt="S", task="T",
        schema={"type": "object"}, effort="high", extended_thinking=False,
        max_tokens=100, adapters={"fake": adapter},
    ))


# ── Fallback policy ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", sorted(RETRYABLE, key=lambda k: k.value))
def test_every_retryable_kind_spends_the_next_key(kind):
    adapter = FakeAdapter({"first": kind, "second": {"ok": True}})
    outcome = walk(chain("first", "second"), adapter)

    assert adapter.calls == ["first", "second"]
    assert outcome.result.ok
    assert len(outcome.attempts) == 2


@pytest.mark.parametrize("kind", [
    ErrorKind.INVALID_REQUEST, ErrorKind.UNPARSEABLE, ErrorKind.TRUNCATED,
])
def test_a_non_retryable_kind_stops_the_chain(kind):
    """
    These three are our request, not the provider's availability. Spending a
    second key reproduces the same failure at double the cost and buries the
    first error under an identical one.
    """
    adapter = FakeAdapter({"first": kind, "second": {"ok": True}})
    outcome = walk(chain("first", "second"), adapter)

    assert adapter.calls == ["first"]
    assert not outcome.result.ok
    assert outcome.result.error_kind is kind


def test_truncation_is_not_retried_because_the_ceiling_travels():
    """
    A cut-off response is invalid against the schema rather than short, and the
    same `max_tokens` applies to the next provider. The fix is a higher ceiling
    or a lower effort — burning another key hides which one is needed.
    """
    assert ErrorKind.TRUNCATED not in RETRYABLE


def test_a_refusal_is_retried_because_it_is_the_model_not_the_request():
    assert ErrorKind.REFUSAL in RETRYABLE


def test_the_first_success_wins_and_later_keys_are_untouched():
    adapter = FakeAdapter({"first": {"ok": True}, "second": {"ok": False}})
    outcome = walk(chain("first", "second"), adapter)

    assert adapter.calls == ["first"]
    assert outcome.result.output == {"ok": True}


def test_a_chain_that_fails_everywhere_returns_the_last_failure():
    adapter = FakeAdapter({
        "first": ErrorKind.RATE_LIMIT, "second": ErrorKind.AUTH,
    })
    outcome = walk(chain("first", "second"), adapter)

    assert not outcome.result.ok
    assert outcome.result.error_kind is ErrorKind.AUTH
    assert [a.error_kind for a in outcome.attempts] == [
        ErrorKind.RATE_LIMIT, ErrorKind.AUTH,
    ]


def test_every_attempt_is_recorded_including_the_one_that_worked():
    """
    A chain that quietly succeeded on its third key is indistinguishable from
    one that succeeded on its first unless the misses are kept — and "why is my
    key not being used" is otherwise unanswerable.
    """
    adapter = FakeAdapter({
        "first": ErrorKind.RATE_LIMIT,
        "second": ErrorKind.OVERLOADED,
        "third": {"ok": True},
    })
    outcome = walk(chain("first", "second", "third"), adapter)

    assert len(outcome.attempts) == 3
    assert [a.ok for a in outcome.attempts] == [False, False, True]
    assert [a.key_id for a in outcome.attempts] == [
        "key-first", "key-second", "key-third",
    ]


def test_an_empty_chain_reports_configuration_not_model_failure():
    outcome = walk([], FakeAdapter({}))
    assert not outcome.result.ok
    assert "no model configured" in (outcome.result.error or "")


# ── Chain construction ────────────────────────────────────────────────────────

@pytest.fixture
def server_key(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-server", raising=False)
    return settings


def test_the_server_key_is_appended_last(server_key, monkeypatch):
    """
    The only reason a user who has configured nothing still gets dossiers, an
    analyst, and signals. On a single-trader deployment this is the whole chain
    and behaviour is identical to before the seam existed.
    """
    monkeypatch.setattr("app.services.llm.resolver.decrypt", lambda c: "sk-user")
    built = build_chain({
        "keys": [{"id": "k1", "provider": "anthropic", "ciphertext": "x"}],
        "roles": {"specialist": [{"key_id": "k1", "model": "claude-sonnet-5"}]},
    }, "specialist")

    assert [c.key_id for c in built] == ["k1", None]
    assert built[-1].api_key == "sk-ant-server"


def test_the_server_key_belongs_to_no_user(server_key):
    """
    `key_id` is None so a failure of it can never be reported against a user's
    profile — they did not configure it and cannot fix it.
    """
    candidate = server_candidate("specialist")
    assert candidate is not None
    assert candidate.key_id is None


def test_no_user_keys_still_yields_a_usable_chain(server_key):
    built = build_chain(None, "orchestrator")
    assert len(built) == 1
    assert built[0].key_id is None


def test_assignment_order_is_priority(server_key, monkeypatch):
    monkeypatch.setattr("app.services.llm.resolver.decrypt", lambda c: "sk-user")
    built = build_chain({
        "keys": [
            {"id": "a", "provider": "openai", "ciphertext": "x"},
            {"id": "b", "provider": "anthropic", "ciphertext": "y"},
        ],
        "roles": {"specialist": [
            {"key_id": "b", "model": "claude-sonnet-5"},
            {"key_id": "a", "model": "gpt-5.4-mini"},
        ]},
    }, "specialist")

    assert [c.key_id for c in built[:2]] == ["b", "a"]


def test_an_undecryptable_key_is_skipped_not_fatal(server_key, monkeypatch):
    """
    A rotated ENCRYPTION_KEY or a hand-edited document must not take down every
    other key the user configured — the chain has somewhere else to go.
    """
    def boom(_ciphertext):
        raise ValueError("token invalid")

    monkeypatch.setattr("app.services.llm.resolver.decrypt", boom)
    built = build_chain({
        "keys": [{"id": "k1", "provider": "anthropic", "ciphertext": "corrupt"}],
        "roles": {"specialist": [{"key_id": "k1", "model": "claude-sonnet-5"}]},
    }, "specialist")

    assert [c.key_id for c in built] == [None]


def test_an_unknown_provider_is_skipped(server_key, monkeypatch):
    monkeypatch.setattr("app.services.llm.resolver.decrypt", lambda c: "sk")
    built = build_chain({
        "keys": [{"id": "k1", "provider": "definitely-not-a-provider",
                  "ciphertext": "x"}],
        "roles": {"specialist": [{"key_id": "k1", "model": "whatever"}]},
    }, "specialist")

    assert [c.key_id for c in built] == [None]


def test_an_assignment_referencing_a_deleted_key_is_skipped(server_key):
    built = build_chain({
        "keys": [],
        "roles": {"specialist": [{"key_id": "gone", "model": "claude-sonnet-5"}]},
    }, "specialist")
    assert [c.key_id for c in built] == [None]


# ── The registry ──────────────────────────────────────────────────────────────

def test_every_listed_provider_enforces_schemas():
    """
    The gate, not a hint. `analyst.py` had its fence-stripping regexes deleted
    when it moved to structured outputs; a provider that cannot constrain
    output server-side would put them straight back — and the failure would
    surface as a parse error weeks after somebody chose the provider.
    """
    assert registry.PROVIDERS
    for provider in registry.PROVIDERS.values():
        assert provider.enforces_schema, provider.name


def test_only_anthropic_claims_hand_placed_caching():
    """
    The evidence-block breakpoint is why one ledger across four agents is
    affordable. Claiming it elsewhere would hide a real cost difference.
    """
    caching = {p.name for p in registry.PROVIDERS.values() if p.manual_prompt_caching}
    assert caching == {"anthropic"}


def test_effort_clamps_rather_than_errors():
    """
    `xhigh` exists on Anthropic and not on the others. A dossier that refuses
    to run because the configured effort has no exact twin is worse than one at
    that provider's ceiling.
    """
    assert registry.map_effort("anthropic", "xhigh") == "xhigh"
    assert registry.map_effort("openai", "xhigh") == "high"
    assert registry.map_effort("google", "max") == "high"


def test_a_fingerprint_is_not_a_key():
    fp = registry.fingerprint("anthropic", "sk-ant-api03-SECRETMIDDLE-4f2a")
    assert "SECRETMIDDLE" not in fp
    assert fp.endswith("4f2a")


def test_every_provider_has_a_default_for_every_role():
    for provider in registry.PROVIDERS.values():
        for role in registry.ROLES:
            assert provider.default_models.get(role), (provider.name, role)
