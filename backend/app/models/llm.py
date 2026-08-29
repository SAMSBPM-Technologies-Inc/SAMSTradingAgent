"""
Per-user model configuration: which keys a trader has, and what each one runs.

Two shapes, and the split between them is the whole feature. A **key** is a
credential the user owns. A **role assignment** is an ordered list of (key,
model) pairs — ordered, because the order *is* the priority, and a list because
a rate-limited or dead key should fall through rather than cost a section of
the dossier.

**Nothing here ever returns a key.** The stored model carries the ciphertext;
the response model carries a fingerprint and a status and has no field capable
of holding one. That is deliberately a type-level distinction rather than a
`del` before serialising — the latter is one forgotten line away from leaking
every key a user has, and this codebase already had a case where a field the
API model had no room for was silently dropped by Pydantic and nobody noticed
for a release.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

#: Kept in step with `services/llm/registry.ROLES`. A literal rather than a
#: free string so an assignment to a role that does not exist is a validation
#: error at the boundary instead of a chain that silently resolves to nothing.
Role = Literal["orchestrator", "specialist", "analyst"]


class StoredKey(BaseModel):
    """
    A credential as it lives on the user document. Never leaves the server.

    `last_error` / `last_error_at` are written by the resolver when a chain
    walks past this key. A key that is quietly being skipped every night is the
    single most confusing state this feature can produce, and this is what lets
    the profile say so.
    """

    id: str
    provider: str
    label: str = ""
    ciphertext: str
    fingerprint: str
    added_at: Optional[datetime] = None
    last_ok_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None


class KeyStatus(BaseModel):
    """
    A credential as the client sees it.

    There is no `ciphertext` and no `api_key` field, and there must never be
    one: the type is the guarantee. A client that wants to know a key works
    calls the test endpoint, which returns a verdict rather than a secret.
    """

    id: str
    provider: str
    label: str = ""
    #: e.g. `sk-ant-…4f2a` — enough to tell two of your own keys apart, and not
    #: enough to be a key.
    fingerprint: str
    added_at: Optional[datetime] = None
    last_ok_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None


class RoleEntry(BaseModel):
    """One link in a role's chain: a key the user owns, and a model to run."""

    key_id: str
    model: str


class RoleChains(BaseModel):
    """
    The ordered chain per role. Order is priority; there is no separate rank
    field, because two representations of the same fact drift.
    """

    orchestrator: list[RoleEntry] = []
    specialist: list[RoleEntry] = []
    analyst: list[RoleEntry] = []


class LLMSettingsUpdate(BaseModel):
    """What a client may change. Keys are added and removed on their own routes."""

    roles: RoleChains = RoleChains()
    #: Gates the per-user daily research job. Defaults false and stays false
    #: until asked: research is five to seven calls per ticker per day, and
    #: multiplied across users it is the one number in this system that can run
    #: away. A user who turns it on is spending their own key.
    research_enabled: bool = False


class LLMSettingsResponse(BaseModel):
    """The full readable state of a user's model configuration."""

    keys: list[KeyStatus] = []
    roles: RoleChains = RoleChains()
    research_enabled: bool = False
    #: What the deployment will fall back to when a user's chain is exhausted
    #: or empty. Surfaced because a trader who configures nothing still gets
    #: dossiers, and ought to be able to see what produced them.
    server_fallback: Optional[str] = None


class AddKeyRequest(BaseModel):
    """
    Adding a key. The plaintext arrives once, here, and is never returned.

    `min_length` is a courtesy check only — validation is a real
    schema-constrained call against the provider, because a well-formed string
    that is not a working key is exactly the failure this route exists to catch
    before it becomes a silent nightly skip.
    """

    provider: str
    api_key: str = Field(min_length=8, max_length=512)
    label: str = Field(default="", max_length=64)


class KeyTestResult(BaseModel):
    """The verdict from a real call. Carries no part of the key."""

    ok: bool
    provider: str
    model: Optional[str] = None
    error: Optional[str] = None
    #: The classified failure — `auth` reads very differently from
    #: `rate_limit`, and a user deciding whether to re-paste a key needs to
    #: know which one they are looking at.
    error_kind: Optional[str] = None
