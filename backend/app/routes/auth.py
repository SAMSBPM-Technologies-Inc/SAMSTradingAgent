"""
POST /auth/register  — create account
POST /auth/login     — get JWT token
GET  /auth/me        — current user profile
PUT  /auth/me        — update display name
"""
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.db import COLL_USERS, get_db
from app.dependencies import get_current_user, require_tier
from app.services.auth import create_access_token, hash_password, verify_password
from app.utils.logger import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


# ── Request / response models ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str = ""

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UpdateMeRequest(BaseModel):
    display_name: str

class IbkrCredentialsRequest(BaseModel):
    ibkr_host: str                  # hostname or IP of the machine running IB Gateway
    ibkr_port: int = 4003           # 4001=live, 4003=paper (IB Gateway defaults)
    ibkr_account_id: str = ""       # optional — leave blank to use IB Gateway default account

class IbkrStatusResponse(BaseModel):
    has_credentials: bool
    ibkr_host: str | None = None
    ibkr_port: int | None = None
    ibkr_account_id: str | None = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest) -> TokenResponse:
    """Create a new user account and return an access token."""
    db = await get_db()
    if await db[COLL_USERS].find_one({"email": body.email}):
        raise HTTPException(status_code=409, detail="Email already registered")

    user = {
        "email": body.email,
        "password_hash": hash_password(body.password),
        "display_name": body.display_name or body.email.split("@")[0],
        "created_at": datetime.now(tz=timezone.utc),
        "tier": 1,
        "role": "user",
    }
    result = await db[COLL_USERS].insert_one(user)
    logger.info("user_registered", email=body.email)
    return TokenResponse(access_token=create_access_token(str(result.inserted_id), body.email))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    """Authenticate and return an access token."""
    db = await get_db()
    user = await db[COLL_USERS].find_one({"email": body.email})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    logger.info("user_login", email=body.email)
    return TokenResponse(access_token=create_access_token(str(user["_id"]), user["email"]))


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)) -> dict:
    """Return the current user's profile."""
    return {
        "id": str(current_user["_id"]),
        "email": current_user["email"],
        "display_name": current_user.get("display_name", ""),
        "created_at": current_user.get("created_at"),
        "tier": current_user.get("tier", 1),
        "role": current_user.get("role", "user"),
    }


@router.put("/me/ibkr", response_model=IbkrStatusResponse)
async def save_ibkr_credentials(
    body: IbkrCredentialsRequest,
    current_user: dict = Depends(require_tier(3)),
) -> IbkrStatusResponse:
    """Store IB Gateway host and port for the current user."""
    host = body.ibkr_host.strip()
    if not host:
        raise HTTPException(status_code=422, detail="IB Gateway host must not be blank")
    if not (1 <= body.ibkr_port <= 65535):
        raise HTTPException(status_code=422, detail="Port must be between 1 and 65535")

    db = await get_db()
    account_id = body.ibkr_account_id.strip()
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": {
            "ibkr_host": host,
            "ibkr_port": body.ibkr_port,
            "ibkr_account_id": account_id,
        }},
    )
    logger.info("ibkr_gateway_saved", user_id=str(current_user["_id"]))
    return IbkrStatusResponse(
        has_credentials=True,
        ibkr_host=host,
        ibkr_port=body.ibkr_port,
        ibkr_account_id=account_id or None,
    )


@router.get("/me/ibkr/status", response_model=IbkrStatusResponse)
async def get_ibkr_status(
    current_user: dict = Depends(require_tier(3)),
) -> IbkrStatusResponse:
    """Return stored IB Gateway configuration for the current user."""
    host = current_user.get("ibkr_host")
    port = current_user.get("ibkr_port")
    has_creds = bool(host and port)
    account_id = current_user.get("ibkr_account_id") or None
    return IbkrStatusResponse(
        has_credentials=has_creds,
        ibkr_host=host if has_creds else None,
        ibkr_port=port if has_creds else None,
        ibkr_account_id=account_id if has_creds else None,
    )


@router.delete("/me/ibkr", status_code=200)
async def delete_ibkr_credentials(
    current_user: dict = Depends(require_tier(3)),
) -> dict:
    """Remove stored IB Gateway configuration for the current user."""
    db = await get_db()
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$unset": {"ibkr_host": "", "ibkr_port": "", "ibkr_account_id": ""}},
    )
    logger.info("ibkr_gateway_deleted", user_id=str(current_user["_id"]))
    return {"status": "deleted"}


@router.put("/me")
async def update_me(
    body: UpdateMeRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update the current user's display name."""
    db = await get_db()
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"display_name": body.display_name}},
    )
    return {"status": "updated", "display_name": body.display_name}
