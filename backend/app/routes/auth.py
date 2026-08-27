"""
POST /auth/login     — get JWT token
GET  /auth/me        — current user profile
PUT  /auth/me        — update display name and/or scoring weights
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, model_validator

from app.db import COLL_USERS, get_db
from app.dependencies import get_current_user
from app.services import rate_limit
from app.services.auth import create_access_token, hash_password, verify_password
from app.utils.net import client_ip as _client_ip
from app.utils.logger import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


# ── Request / response models ─────────────────────────────────────────────────

class ScoringWeights(BaseModel):
    """Per-user scoring weights. The 6 base weights must sum to 1.0.
    alternative_data is an additive modifier (not part of the sum constraint)."""
    technical: float = 0.25
    fundamental: float = 0.15
    sentiment: float = 0.20
    macro: float = 0.15
    volatility: float = 0.10
    catalyst: float = 0.15
    alternative_data: float = 0.10

    @model_validator(mode="after")
    def validate_sum(self) -> "ScoringWeights":
        total = self.technical + self.fundamental + self.sentiment + self.macro + self.volatility + self.catalyst
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Base scoring weights (technical + fundamental + sentiment + macro + volatility + catalyst) "
                f"must sum to 1.0, got {total:.4f}"
            )
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UpdateMeRequest(BaseModel):
    display_name: Optional[str] = None
    scoring_weights: Optional[ScoringWeights] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    """
    Authenticate and return an access token.

    Rate limited per email and per client address. This endpoint previously had
    no limit of any kind, so a known email could be guessed against at whatever
    rate the network allowed.
    """
    client_ip = _client_ip(request)

    decision = rate_limit.check_login_allowed(body.email, client_ip)
    if not decision.allowed:
        logger.warning("login_rate_limited", email=body.email, client=client_ip)
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-in attempts. Try again shortly.",
            headers={"Retry-After": str(decision.retry_after)},
        )

    db = await get_db()
    user = await db[COLL_USERS].find_one({"email": body.email})
    if not user or not verify_password(body.password, user["password_hash"]):
        rate_limit.record_login_failure(body.email, client_ip)
        # Deliberately identical for "no such user" and "wrong password" — a
        # distinguishable response enumerates accounts.
        raise HTTPException(status_code=401, detail="Invalid email or password")

    rate_limit.record_login_success(body.email, client_ip)
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
        "scoring_weights": current_user.get("scoring_weights"),
    }


@router.put("/me")
async def update_me(
    body: UpdateMeRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update display name and/or personal scoring weights."""
    if body.display_name is None and body.scoring_weights is None:
        raise HTTPException(status_code=400, detail="Provide display_name and/or scoring_weights")

    updates: dict = {}
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.scoring_weights is not None:
        updates["scoring_weights"] = body.scoring_weights.model_dump()

    db = await get_db()
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": updates},
    )
    return {"status": "updated", **updates}
