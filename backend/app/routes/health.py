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

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db_connected=db_ok,
    )
