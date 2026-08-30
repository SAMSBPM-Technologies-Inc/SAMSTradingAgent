"""
GET /system/status
──────────────────
What is working, what is not, and what each answer costs a trading decision.

**Authenticated, deliberately.** `/health` is the unauthenticated liveness
probe and stays that way — uptime checkers hit it. This is a different thing:
it names environment variables, provider error text and infrastructure state,
which is deployment-shape disclosure and not something a stranger should be
able to enumerate. The one field on `/health` that *is* a secret-adjacent
disclosure (`auth_secret_is_default`) is there for a stated reason — a forgeable
signing key makes authentication meaningless, so hiding it behind authentication
would be theatre. That reasoning does not generalise to the rest of this.
"""
from fastapi import APIRouter, Depends

from app.config import get_settings
from app.models.system import SystemStatusResponse
from app.services import source_health
from app.dependencies import get_current_user
from app.services.system_status import build_status
from app.utils.logger import get_logger

router = APIRouter(prefix="/system", tags=["system"])
logger = get_logger(__name__)


@router.get(
    "/status",
    response_model=SystemStatusResponse,
    summary="Which data sources and subsystems are working",
)
async def system_status(
    current_user: dict = Depends(get_current_user),
) -> SystemStatusResponse:
    """
    Report every capability's last observed state.

    Nothing is probed. Each row is what the source actually did on the last
    pipeline cycle, read from records the fetches themselves wrote — see
    `services/source_health.py` for why a probe would be both more expensive
    and less true.
    """
    health = await source_health.read_all()
    return SystemStatusResponse(**build_status(get_settings(), health))
