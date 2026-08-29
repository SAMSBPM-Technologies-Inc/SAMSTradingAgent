"""
GET/PUT /settings/llm — which models a trader's agents run on.
POST   /settings/llm/keys           — add a credential, validated on the way in
DELETE /settings/llm/keys/{key_id}  — remove one
POST   /settings/llm/keys/{key_id}/test — re-check one on demand

A key is written once and never read back. Every response here is built from
`KeyStatus`, which has no field capable of holding a credential — the guarantee
is the type, not a `del` before serialising, because the latter is one
forgotten line away from returning every key a user has.

Validation is a **real schema-constrained call**, not a regex. A well-formed
string that is not a working key is precisely the failure this route exists to
catch: without the call it would be stored happily and then skipped silently
every night, and "my key isn't being used" is close to undiagnosable from the
outside.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.db import COLL_USERS, get_db
from app.dependencies import get_current_user
from app.models.llm import (
    AddKeyRequest, KeyStatus, KeyTestResult, LLMSettingsResponse,
    LLMSettingsUpdate, RoleChains,
)
from app.services.encryption import encrypt
from app.services.llm.base import Candidate
from app.services.llm.registry import ROLES, default_model, fingerprint, get_provider
from app.services.llm.resolver import adapter_for, server_candidate
from app.utils.logger import get_logger

router = APIRouter(tags=["llm"])
logger = get_logger(__name__)

#: The probe used to validate a key. Deliberately tiny and schema-constrained:
#: it has to exercise the one capability the whole research module depends on —
#: server-side schema enforcement — while costing almost nothing. A key that
#: authenticates but cannot constrain output is not a usable key here.
_PROBE_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
_PROBE_TASK = "Reply with {\"ok\": true} and nothing else."


def _settings_of(user: dict) -> dict:
    return user.get("llm_settings") or {}


def _to_status(stored: dict) -> KeyStatus:
    """Stored → readable. The ciphertext has nowhere to go."""
    return KeyStatus(
        id=str(stored.get("id") or ""),
        provider=str(stored.get("provider") or ""),
        label=str(stored.get("label") or ""),
        fingerprint=str(stored.get("fingerprint") or ""),
        added_at=stored.get("added_at"),
        last_ok_at=stored.get("last_ok_at"),
        last_error=stored.get("last_error"),
        last_error_at=stored.get("last_error_at"),
    )


def _response(settings: dict) -> LLMSettingsResponse:
    fallback = server_candidate("specialist")
    return LLMSettingsResponse(
        keys=[_to_status(k) for k in (settings.get("keys") or [])],
        roles=RoleChains(**(settings.get("roles") or {})),
        research_enabled=bool(settings.get("research_enabled")),
        server_fallback=(
            f"{fallback.provider}/{fallback.model}" if fallback else None
        ),
    )


async def _probe(provider: str, api_key: str, model: str) -> KeyTestResult:
    """One real call. Returns a verdict; never echoes any part of the key."""
    adapter = adapter_for(provider)
    if adapter is None:
        return KeyTestResult(ok=False, provider=provider,
                             error="unknown provider", error_kind="invalid_request")
    result = await adapter.complete(
        api_key=api_key, model=model,
        evidence_block="(no evidence — connectivity probe)",
        system_prompt="You are validating an API credential.",
        task=_PROBE_TASK, schema=_PROBE_SCHEMA,
        effort="low", extended_thinking=False, max_tokens=256,
    )
    return KeyTestResult(
        ok=result.ok, provider=provider, model=model,
        error=result.error,
        error_kind=result.error_kind.value if result.error_kind else None,
    )


@router.get("/settings/llm", response_model=LLMSettingsResponse,
            summary="Which models your agents run on")
async def get_llm_settings(
    current_user: dict = Depends(get_current_user),
) -> LLMSettingsResponse:
    db = await get_db()
    user = await db[COLL_USERS].find_one(
        {"_id": current_user["_id"]}, {"llm_settings": 1}
    )
    return _response(_settings_of(user or {}))


@router.put("/settings/llm", response_model=LLMSettingsResponse,
            summary="Assign models to roles")
async def update_llm_settings(
    body: LLMSettingsUpdate,
    current_user: dict = Depends(get_current_user),
) -> LLMSettingsResponse:
    """
    Replace the role chains wholesale. Order is priority.

    Every assignment must name a key the user actually holds. Rejecting an
    unknown id here rather than skipping it at call time is the difference
    between a form that tells you it is wrong and a chain that silently drops a
    link you believe is configured.
    """
    db = await get_db()
    user = await db[COLL_USERS].find_one(
        {"_id": current_user["_id"]}, {"llm_settings": 1}
    )
    settings = _settings_of(user or {})
    known = {str(k.get("id")) for k in (settings.get("keys") or [])}

    roles = body.roles.model_dump()
    for role, entries in roles.items():
        for entry in entries:
            if entry["key_id"] not in known:
                raise HTTPException(
                    status_code=400,
                    detail=f"{role}: no such key {entry['key_id']}",
                )
            if not entry.get("model"):
                raise HTTPException(
                    status_code=400, detail=f"{role}: a model is required",
                )

    settings["roles"] = roles
    settings["research_enabled"] = body.research_enabled
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]}, {"$set": {"llm_settings": settings}},
    )
    logger.info(
        "llm_settings_updated", user_id=str(current_user["_id"]),
        research_enabled=body.research_enabled,
        assigned={r: len(e) for r, e in roles.items()},
    )
    return _response(settings)


@router.post("/settings/llm/keys", response_model=LLMSettingsResponse,
             summary="Add a provider key")
async def add_key(
    body: AddKeyRequest,
    current_user: dict = Depends(get_current_user),
) -> LLMSettingsResponse:
    """
    Validate, then store. A key that fails the probe is refused, not saved.

    Storing an unusable key would push the failure to the nightly job, where it
    shows up as a dossier that did not get built for a reason nobody can see.
    """
    spec = get_provider(body.provider)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider}")

    model = default_model(spec.name, "specialist") or ""
    verdict = await _probe(spec.name, body.api_key, model)
    if not verdict.ok:
        logger.info("llm_key_rejected", user_id=str(current_user["_id"]),
                    provider=spec.name, kind=verdict.error_kind)
        raise HTTPException(
            status_code=400,
            detail=f"That key did not work ({verdict.error_kind}): {verdict.error}",
        )

    now = datetime.now(tz=timezone.utc)
    stored = {
        "id": uuid.uuid4().hex[:12],
        "provider": spec.name,
        "label": body.label or spec.label,
        "ciphertext": encrypt(body.api_key),
        "fingerprint": fingerprint(spec.name, body.api_key),
        "added_at": now,
        "last_ok_at": now,
        "last_error": None,
        "last_error_at": None,
    }

    db = await get_db()
    user = await db[COLL_USERS].find_one(
        {"_id": current_user["_id"]}, {"llm_settings": 1}
    )
    settings = _settings_of(user or {})
    settings.setdefault("keys", []).append(stored)
    settings.setdefault("roles", RoleChains().model_dump())
    settings.setdefault("research_enabled", False)

    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]}, {"$set": {"llm_settings": settings}},
    )
    logger.info("llm_key_added", user_id=str(current_user["_id"]),
                provider=spec.name, key_id=stored["id"])
    return _response(settings)


@router.delete("/settings/llm/keys/{key_id}", response_model=LLMSettingsResponse,
               summary="Remove a provider key")
async def delete_key(
    key_id: str,
    current_user: dict = Depends(get_current_user),
) -> LLMSettingsResponse:
    """
    Remove the key and every assignment pointing at it, in one write.

    Leaving dangling assignments behind would produce a chain that resolves
    shorter than the profile shows — the same silent-skip confusion the
    validation probe exists to prevent, arrived at from the other direction.
    """
    db = await get_db()
    user = await db[COLL_USERS].find_one(
        {"_id": current_user["_id"]}, {"llm_settings": 1}
    )
    settings = _settings_of(user or {})
    before = len(settings.get("keys") or [])
    settings["keys"] = [
        k for k in (settings.get("keys") or []) if str(k.get("id")) != key_id
    ]
    if len(settings["keys"]) == before:
        raise HTTPException(status_code=404, detail="No such key")

    roles = settings.get("roles") or {}
    for role in ROLES:
        roles[role] = [
            e for e in (roles.get(role) or []) if str(e.get("key_id")) != key_id
        ]
    settings["roles"] = roles

    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]}, {"$set": {"llm_settings": settings}},
    )
    logger.info("llm_key_deleted", user_id=str(current_user["_id"]), key_id=key_id)
    return _response(settings)


@router.post("/settings/llm/keys/{key_id}/test", response_model=KeyTestResult,
             summary="Re-check a stored key")
async def test_key(
    key_id: str,
    current_user: dict = Depends(get_current_user),
) -> KeyTestResult:
    """
    Run the probe against a stored key and record the verdict.

    Worth having separately from the add-time check: keys are revoked, quotas
    lapse, and a key that worked in March is not evidence about tonight. The
    result is written back so the profile can show a status without the user
    having to press this.
    """
    from app.services.encryption import decrypt

    db = await get_db()
    user = await db[COLL_USERS].find_one(
        {"_id": current_user["_id"]}, {"llm_settings": 1}
    )
    settings = _settings_of(user or {})
    stored = next(
        (k for k in (settings.get("keys") or []) if str(k.get("id")) == key_id), None
    )
    if stored is None:
        raise HTTPException(status_code=404, detail="No such key")

    provider = str(stored.get("provider") or "")
    try:
        api_key = decrypt(str(stored.get("ciphertext") or ""))
    except Exception:
        # A rotated ENCRYPTION_KEY makes every stored key unreadable. Say so
        # plainly rather than reporting it as the provider's fault.
        return KeyTestResult(ok=False, provider=provider,
                             error="stored key could not be decrypted",
                             error_kind="auth")

    verdict = await _probe(provider, api_key, default_model(provider, "specialist") or "")

    now = datetime.now(tz=timezone.utc)
    if verdict.ok:
        stored["last_ok_at"] = now
        stored["last_error"] = None
        stored["last_error_at"] = None
    else:
        stored["last_error"] = verdict.error
        stored["last_error_at"] = now

    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]}, {"$set": {"llm_settings": settings}},
    )
    return verdict
