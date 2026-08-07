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
