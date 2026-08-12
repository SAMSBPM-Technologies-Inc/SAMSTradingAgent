"""
Admin Routes — require role=admin
GET  /admin/users                   — list all users
PUT  /admin/users/{user_id}/tier    — set tier (1/2/3)
PUT  /admin/users/{user_id}/role    — set role (user/admin)
"""
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import COLL_USERS, get_db
from app.dependencies import require_admin
from app.utils.logger import get_logger

router = APIRouter(prefix="/admin", tags=["admin"])
logger = get_logger(__name__)

TIER_LABELS = {1: "Starter", 2: "Pro", 3: "Elite"}


class SetTierRequest(BaseModel):
    tier: int   # 1, 2, or 3

class SetRoleRequest(BaseModel):
    role: str   # "user" or "admin"


@router.get("/users")
async def list_users(admin: dict = Depends(require_admin)) -> list[dict]:
    """Return all users with id, email, display_name, tier, role, created_at."""
    db = await get_db()
    cursor = db[COLL_USERS].find(
        {},
        {"email": 1, "display_name": 1, "tier": 1, "role": 1, "created_at": 1},
    ).sort("created_at", 1)
    users = []
    async for doc in cursor:
        users.append({
            "id": str(doc["_id"]),
            "email": doc.get("email", ""),
            "display_name": doc.get("display_name", ""),
            "tier": doc.get("tier", 1),
            "tier_label": TIER_LABELS.get(doc.get("tier", 1), "Starter"),
            "role": doc.get("role", "user"),
            "created_at": doc.get("created_at"),
        })
    return users


@router.put("/users/{user_id}/tier")
async def set_user_tier(
    user_id: str,
    body: SetTierRequest,
    admin: dict = Depends(require_admin),
) -> dict:
    """Set a user's tier (1=Starter, 2=Pro, 3=Elite)."""
    if body.tier not in (1, 2, 3):
        raise HTTPException(status_code=422, detail="Tier must be 1, 2, or 3")
    db = await get_db()
    result = await db[COLL_USERS].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"tier": body.tier}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("admin_set_tier", admin_id=str(admin["_id"]), user_id=user_id, tier=body.tier)
    return {"status": "updated", "tier": body.tier, "tier_label": TIER_LABELS[body.tier]}


@router.put("/users/{user_id}/role")
async def set_user_role(
    user_id: str,
    body: SetRoleRequest,
    admin: dict = Depends(require_admin),
) -> dict:
    """Set a user's role (user/admin). Admins cannot demote themselves."""
    if body.role not in ("user", "admin"):
        raise HTTPException(status_code=422, detail="Role must be 'user' or 'admin'")
    if user_id == str(admin["_id"]) and body.role != "admin":
        raise HTTPException(status_code=400, detail="Cannot remove your own admin role")
    db = await get_db()
    result = await db[COLL_USERS].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"role": body.role}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("admin_set_role", admin_id=str(admin["_id"]), user_id=user_id, role=body.role)
    return {"status": "updated", "role": body.role}
