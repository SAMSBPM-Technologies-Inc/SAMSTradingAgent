"""
GET  /alerts/settings  — get the current user's alert preferences
PUT  /alerts/settings  — update alert preferences
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, HttpUrl
from typing import Optional

from app.db import COLL_USERS, get_db
from app.dependencies import get_current_user
from app.utils.logger import get_logger

router = APIRouter(prefix="/alerts", tags=["alerts"])
logger = get_logger(__name__)


class AlertSettings(BaseModel):
    slack_webhook_url: Optional[str] = None
    notify_on_signal_flip: bool = True
    notify_on_high_conviction: bool = True
    daily_digest: bool = False


@router.get("/settings", response_model=AlertSettings)
async def get_alert_settings(current_user: dict = Depends(get_current_user)) -> AlertSettings:
    prefs = current_user.get("alert_settings") or {}
    return AlertSettings(
        slack_webhook_url=prefs.get("slack_webhook_url"),
        notify_on_signal_flip=prefs.get("notify_on_signal_flip", True),
        notify_on_high_conviction=prefs.get("notify_on_high_conviction", True),
        daily_digest=prefs.get("daily_digest", False),
    )


@router.put("/settings", response_model=AlertSettings)
async def update_alert_settings(
    body: AlertSettings,
    current_user: dict = Depends(get_current_user),
) -> AlertSettings:
    db = await get_db()
    prefs = {
        "slack_webhook_url": body.slack_webhook_url or None,
        "notify_on_signal_flip": body.notify_on_signal_flip,
        "notify_on_high_conviction": body.notify_on_high_conviction,
        "daily_digest": body.daily_digest,
    }
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"alert_settings": prefs}},
    )
    logger.info("alert_settings_updated", user_id=str(current_user["_id"]))
    return AlertSettings(**prefs)
