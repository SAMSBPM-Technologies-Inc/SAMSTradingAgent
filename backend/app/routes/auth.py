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
from app.dependencies import get_current_user
from app.services.auth import create_access_token, hash_password, verify_password
from app.services.encryption import decrypt, encrypt
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
    ibkr_username: str
    ibkr_password: str

class IbkrStatusResponse(BaseModel):
    has_credentials: bool
    ibkr_username: str | None = None

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
    }


@router.put("/me/ibkr", response_model=IbkrStatusResponse)
async def save_ibkr_credentials(
    body: IbkrCredentialsRequest,
    current_user: dict = Depends(get_current_user),
) -> IbkrStatusResponse:
    """Encrypt and store IBKR credentials for the current user."""
    if not body.ibkr_username.strip() or not body.ibkr_password.strip():
        raise HTTPException(status_code=422, detail="Username and password must not be blank")
    try:
        password_enc = encrypt(body.ibkr_password)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    db = await get_db()
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"ibkr_username": body.ibkr_username.strip(), "ibkr_password_enc": password_enc}},
    )
    logger.info("ibkr_credentials_saved", user_id=str(current_user["_id"]))
    return IbkrStatusResponse(has_credentials=True, ibkr_username=body.ibkr_username.strip())


@router.get("/me/ibkr/status", response_model=IbkrStatusResponse)
async def get_ibkr_status(
    current_user: dict = Depends(get_current_user),
) -> IbkrStatusResponse:
    """Return whether IBKR credentials are stored. Never returns the password."""
    username = current_user.get("ibkr_username")
    has_creds = bool(username and current_user.get("ibkr_password_enc"))
    return IbkrStatusResponse(has_credentials=has_creds, ibkr_username=username if has_creds else None)


@router.delete("/me/ibkr", status_code=200)
async def delete_ibkr_credentials(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Remove stored IBKR credentials for the current user."""
    db = await get_db()
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$unset": {"ibkr_username": "", "ibkr_password_enc": ""}},
    )
    logger.info("ibkr_credentials_deleted", user_id=str(current_user["_id"]))
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
