"""
FastAPI dependencies — injected into protected routes via Depends().
"""
from bson import ObjectId
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import COLL_USERS, get_db
from app.services.auth import decode_token

_bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Validate the Bearer JWT and return the user document.
    Raises 401 if the token is missing, invalid, or expired.
    """
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    db = await get_db()
    user = await db[COLL_USERS].find_one({"_id": ObjectId(payload["sub"])})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_tier(min_tier: int):
    """
    Dependency factory — raises 403 if the user's tier is below min_tier.
    Usage: current_user: dict = Depends(require_tier(2))
    """
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("tier", 1) < min_tier:
            tier_names = {1: "Starter", 2: "Pro", 3: "Elite"}
            required = tier_names.get(min_tier, f"Tier {min_tier}")
            raise HTTPException(
                status_code=403,
                detail=f"{required} plan required to access this feature. Contact your administrator to upgrade.",
            )
        return current_user
    return _check


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Raises 403 if the user is not an admin."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
