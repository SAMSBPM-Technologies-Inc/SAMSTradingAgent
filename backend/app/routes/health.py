"""
GET /health
───────────
Liveness / readiness probe.  Returns DB connectivity status.
"""
from fastapi import APIRouter

from app.db import get_db
from app.models.stock import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Health check")
async def health_check() -> HealthResponse:
    """Return app liveness status and MongoDB connectivity."""
    db_ok = False
    try:
        db = await get_db()
        await db.command("ping")
        db_ok = True
    except Exception:
        pass

    # Reported, not merely logged: a placeholder signing key is invisible in
    # normal operation — everything works, and anyone with the source can forge
    # a token. `status` stays "ok" because the service is functioning; this is a
    # security defect, not an outage, and conflating them would make the field
    # useless for uptime checks.
    from app.config import DEFAULT_JWT_SECRET, get_settings

    secret_is_default = get_settings().jwt_secret_key == DEFAULT_JWT_SECRET

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db_connected=db_ok,
        auth_secret_is_default=secret_is_default,
    )
