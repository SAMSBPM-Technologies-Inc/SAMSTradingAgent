"""
GET  /alerts/settings  — get the current user's alert preferences
PUT  /alerts/settings  — update alert preferences
POST /alerts/test      — send a test notification via configured channels
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.db import COLL_USERS, get_db
from app.dependencies import get_current_user
from app.utils.logger import get_logger

router = APIRouter(prefix="/alerts", tags=["alerts"])
logger = get_logger(__name__)


class AlertSettings(BaseModel):
    slack_webhook_url: Optional[str] = None
    whatsapp_phone: Optional[str] = None
    whatsapp_apikey: Optional[str] = None
    notify_on_signal_flip: bool = True
    notify_on_high_conviction: bool = True
    daily_digest: bool = False
    # Sent when the agent submits an order. Defaults on: the whole point of the
    # channel is that automated trades are otherwise invisible until you happen
    # to open the dashboard.
    notify_on_trade: bool = True
    # Sent when that order actually executes, and when a position closes with
    # its realised P&L. Gated separately from submission on purpose — "tell me
    # when it happened, not when you tried" is a reasonable thing to want, and
    # one switch could not express it.
    notify_on_fill: bool = True
    # Sent when a data source stops working, or starts again. Gated separately
    # from the trade notifications for the same reason those are gated
    # separately from each other: "tell me when the engine loses an input" and
    # "tell me when it places an order" are different appetites, and one switch
    # could not express both. Defaults on — a silent degradation is the whole
    # failure mode this exists to close.
    notify_on_degraded: bool = True
    # Optional override; blank sends to the account email.
    trade_email: Optional[str] = None


@router.get("/settings", response_model=AlertSettings)
async def get_alert_settings(current_user: dict = Depends(get_current_user)) -> AlertSettings:
    prefs = current_user.get("alert_settings") or {}
    return AlertSettings(
        slack_webhook_url=prefs.get("slack_webhook_url"),
        whatsapp_phone=prefs.get("whatsapp_phone"),
        whatsapp_apikey=prefs.get("whatsapp_apikey"),
        notify_on_signal_flip=prefs.get("notify_on_signal_flip", True),
        notify_on_high_conviction=prefs.get("notify_on_high_conviction", True),
        daily_digest=prefs.get("daily_digest", False),
        notify_on_trade=prefs.get("notify_on_trade", True),
        notify_on_degraded=prefs.get("notify_on_degraded", True),
        notify_on_fill=prefs.get("notify_on_fill", True),
        trade_email=prefs.get("trade_email"),
    )


@router.put("/settings", response_model=AlertSettings)
async def update_alert_settings(
    body: AlertSettings,
    current_user: dict = Depends(get_current_user),
) -> AlertSettings:
    db = await get_db()
    prefs = {
        "slack_webhook_url": body.slack_webhook_url or None,
        "whatsapp_phone": body.whatsapp_phone or None,
        "whatsapp_apikey": body.whatsapp_apikey or None,
        "notify_on_signal_flip": body.notify_on_signal_flip,
        "notify_on_high_conviction": body.notify_on_high_conviction,
        "daily_digest": body.daily_digest,
        "notify_on_trade": body.notify_on_trade,
        "notify_on_degraded": body.notify_on_degraded,
        "notify_on_fill": body.notify_on_fill,
        "trade_email": (body.trade_email or "").strip() or None,
    }
    await db[COLL_USERS].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"alert_settings": prefs}},
    )
    logger.info("alert_settings_updated", user_id=str(current_user["_id"]))
    return AlertSettings(**prefs)


@router.post("/test")
async def send_test_alert(current_user: dict = Depends(get_current_user)) -> dict:
    """Send a test notification through all configured channels."""
    prefs = current_user.get("alert_settings") or {}
    sent: list[str] = []
    errors: dict[str, str] = {}

    # Email first — it is the channel most likely to be misconfigured, and the
    # only one whose failure reason is worth surfacing to the caller.
    from app.services.notifier import send_test_email
    to = (prefs.get("trade_email") or current_user.get("email") or "").strip()
    if to:
        reason = await send_test_email(to)
        if reason:
            errors["email"] = reason
        else:
            sent.append(f"email ({to})")

    from app.services.notifier import send_signal_alert
    slack_url = prefs.get("slack_webhook_url")
    if slack_url:
        await send_signal_alert(
            webhook_url=slack_url,
            ticker="TEST",
            old_signal="HOLD",
            new_signal="BUY",
            score=0.74,
            conviction="HIGH",
            confidence=0.81,
            price_target=35.0,
            stop_loss=28.5,
            whatsapp_phone=None,
            whatsapp_apikey=None,
        )
        sent.append("slack")

    # WhatsApp goes through the low-level sender rather than send_signal_alert,
    # because only the low-level one reports whether CallMeBot accepted it.
    # Reporting "whatsapp" as sent regardless is what let a dead API key look
    # healthy — the button said it worked, and the message never arrived.
    phone = prefs.get("whatsapp_phone")
    apikey = prefs.get("whatsapp_apikey")
    if phone and apikey:
        from app.services.notifier import _whatsapp_send
        reason = await _whatsapp_send(
            phone, apikey,
            "✅ SAMSBPM Trading Agent — WhatsApp notifications are working.\n"
            "Order placed, order filled, and position closed alerts will arrive here.",
        )
        if reason:
            errors["whatsapp"] = reason
        else:
            sent.append("whatsapp")
    elif phone or apikey:
        errors["whatsapp"] = (
            "incomplete — CallMeBot needs both a phone number and an API key"
        )

    if not sent and not errors:
        return {"status": "no_channels", "message": "No notification channels configured."}

    # A channel that was attempted and failed must not be reported as success —
    # silently "sent" email that never arrives is the failure mode this endpoint
    # exists to rule out.
    if errors:
        logger.warning("alert_test_partial_failure", errors=errors, sent=sent)
        return {
            "status": "partial" if sent else "failed",
            "channels": sent,
            "errors": errors,
        }

    return {"status": "sent", "channels": sent}
