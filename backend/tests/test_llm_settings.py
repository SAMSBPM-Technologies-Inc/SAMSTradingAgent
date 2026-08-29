"""
Tests for per-user model configuration.

This is the first feature in the codebase to store a third-party credential per
user — `services/encryption.py` existed for a release with no callers — so the
handling rules are being established here rather than inherited, and these
tests are where they are pinned.

The one that must never regress: **a key is written once and never read back.**
The guarantee is structural — `KeyStatus` has no field capable of holding a
credential — rather than a `del` before serialising, because the latter is one
forgotten line away from returning every key a user has. There is a test below
that asserts the type itself cannot carry one, so the guarantee survives
somebody adding a field in good faith.

Run with:  pytest backend/tests -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.llm import (  # noqa: E402
    AddKeyRequest, KeyStatus, LLMSettingsResponse, RoleChains, StoredKey,
)
from app.services.llm.registry import PROVIDERS, fingerprint  # noqa: E402


SECRET = "sk-ant-api03-THISISTHESECRETMIDDLE-4f2a"


# ── The credential never comes back ───────────────────────────────────────────

def test_the_readable_type_cannot_hold_a_credential():
    """
    Structural, not procedural. If someone adds a `ciphertext` or `api_key`
    field to `KeyStatus` in good faith, this fails — which is the point, since
    the alternative is discovering it from a client that renders one.
    """
    forbidden = {"ciphertext", "api_key", "key", "secret", "token", "plaintext"}
    assert not (set(KeyStatus.model_fields) & forbidden)


def test_the_settings_response_carries_no_credential_field():
    forbidden = {"ciphertext", "api_key", "key", "secret", "token"}
    assert not (set(LLMSettingsResponse.model_fields) & forbidden)


def test_the_stored_type_does_hold_the_ciphertext():
    """The other half of the split — if this ever stops being true the key is
    not being persisted at all."""
    assert "ciphertext" in StoredKey.model_fields


def test_a_serialised_response_contains_no_part_of_the_key():
    stored = StoredKey(
        id="k1", provider="anthropic", label="mine",
        ciphertext="gAAAAA-ciphertext", fingerprint=fingerprint("anthropic", SECRET),
    )
    status = KeyStatus(
        id=stored.id, provider=stored.provider, label=stored.label,
        fingerprint=stored.fingerprint,
    )
    blob = LLMSettingsResponse(keys=[status]).model_dump_json()

    assert "THISISTHESECRETMIDDLE" not in blob
    assert "gAAAAA-ciphertext" not in blob
    assert "4f2a" in blob   # the fingerprint tail is meant to be there


def test_a_fingerprint_shows_enough_to_tell_two_keys_apart_and_no_more():
    a = fingerprint("anthropic", "sk-ant-api03-AAAAAAAAAAAA-1111")
    b = fingerprint("anthropic", "sk-ant-api03-BBBBBBBBBBBB-2222")
    assert a != b
    assert "AAAAAAAAAAAA" not in a and "BBBBBBBBBBBB" not in b


# ── Redaction on the logging path ─────────────────────────────────────────────

def test_the_loggable_form_of_a_candidate_omits_the_key():
    """
    Every log line in the seam takes `candidate.redacted()`. A key reaching a
    log is as bad as one reaching a response and much harder to notice.
    """
    from app.services.llm.base import Candidate

    candidate = Candidate(provider="anthropic", model="claude-opus-5",
                          api_key=SECRET, key_id="k1")
    payload = candidate.redacted()

    assert SECRET not in str(payload)
    assert payload == {"provider": "anthropic", "model": "claude-opus-5",
                       "key_id": "k1"}


def test_the_server_key_logs_as_server_not_as_a_user_key():
    """
    `key_id` is None for the deployment's own key, so nothing can attribute its
    failure to a user who did not configure it and cannot fix it.
    """
    from app.services.llm.base import Candidate

    payload = Candidate(provider="anthropic", model="m", api_key=SECRET).redacted()
    assert payload["key_id"] == "server"


def test_no_route_or_seam_module_logs_a_raw_key_field():
    """
    A grep-level fence. Every logger call in these modules takes provider,
    model, and key_id; a call passing the credential itself would be caught
    here rather than in a production log.
    """
    import re

    root = Path(__file__).resolve().parents[1] / "app"
    files = [
        root / "routes" / "llm.py",
        root / "services" / "llm" / "resolver.py",
        root / "services" / "llm" / "anthropic_client.py",
        root / "services" / "llm" / "openai_client.py",
        root / "services" / "llm" / "google_client.py",
    ]
    for path in files:
        text = path.read_text()
        for line in text.splitlines():
            if "logger." not in line:
                continue
            assert not re.search(r"\b(api_key|ciphertext|plaintext)\s*=", line), \
                f"{path.name}: {line.strip()}"


# ── Role chains ───────────────────────────────────────────────────────────────

def test_role_chains_default_to_empty_not_to_a_guess():
    """
    An empty chain means "use the server key", which is a real and correct
    state. Pre-populating a guess would spend a user's key on a model they
    never chose.
    """
    chains = RoleChains()
    assert chains.orchestrator == []
    assert chains.specialist == []
    assert chains.analyst == []


def test_a_role_chain_preserves_the_order_it_was_given():
    """Order is the priority. There is no separate rank field, because two
    representations of the same fact drift."""
    chains = RoleChains(**{"specialist": [
        {"key_id": "b", "model": "m2"},
        {"key_id": "a", "model": "m1"},
    ]})
    assert [e.key_id for e in chains.specialist] == ["b", "a"]


def test_research_stays_off_until_asked():
    """
    Five to seven calls per ticker per day, multiplied by users, is the one
    number in this system that can run away. A user who turns it on is
    spending their own key.
    """
    from app.models.llm import LLMSettingsUpdate

    assert LLMSettingsUpdate().research_enabled is False
    assert LLMSettingsResponse().research_enabled is False


# ── Provider validation at the boundary ───────────────────────────────────────

def test_a_key_request_names_a_provider_we_actually_support():
    request = AddKeyRequest(provider="anthropic", api_key=SECRET)
    assert request.provider in PROVIDERS


def test_an_empty_key_is_rejected_before_any_network_call():
    """Cheap guard only — a well-formed string that is not a working key is
    caught by the probe, which is a real call."""
    with pytest.raises(Exception):
        AddKeyRequest(provider="anthropic", api_key="")
