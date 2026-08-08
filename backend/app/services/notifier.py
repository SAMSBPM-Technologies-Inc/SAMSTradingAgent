"""
Notification Service
────────────────────
Sends Slack webhook messages and WhatsApp messages (via CallMeBot) for signal
alerts and daily digests.
All functions are fire-and-forget — failures are logged but never raise.
"""
import urllib.parse

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

_SIGNAL_EMOJI = {"BUY": "📈", "SELL": "📉", "HOLD": "📊"}
_CONVICTION_LABEL = {"HIGH": "Strong Signal", "MEDIUM": "Moderate", "LOW": "Weak Signal"}


async def send_signal_alert(
    webhook_url: str | None,
    ticker: str,
    old_signal: str | None,
    new_signal: str,
    score: float,
    conviction: str | None,
    confidence: float,
    price_target: float | None,
    stop_loss: float | None,
    whatsapp_phone: str | None = None,
    whatsapp_apikey: str | None = None,
) -> None:
    """Send a signal-flip / high-conviction alert via Slack and/or WhatsApp."""
    emoji = _SIGNAL_EMOJI.get(new_signal, "📊")
    conv_label = _CONVICTION_LABEL.get(conviction or "", "")
    score_pct = round(score * 100)
    conf_pct = round(confidence * 100)

    if old_signal and old_signal != new_signal:
        header = f"{emoji} {ticker} signal flipped: {old_signal} -> {new_signal}"
    else:
        header = f"{emoji} {ticker} - {new_signal} (High Conviction)"

    lines = [header, f"Score: {score_pct} | {conv_label} | Confidence: {conf_pct}%"]
    if price_target or stop_loss:
        parts = []
        if price_target:
            parts.append(f"Target: ${price_target:.2f}")
        if stop_loss:
            parts.append(f"Stop: ${stop_loss:.2f}")
        lines.append(" | ".join(parts))
    lines.append("SAMSBPM Trading - sta.samsbpm.com")

    text = "\n".join(lines)

    if webhook_url:
        # Slack uses mrkdwn — wrap key parts in asterisks for bold
        slack_text = text.replace(f"{ticker} signal flipped:", f"*{ticker}* signal flipped:") \
                         .replace(f"{ticker} -", f"*{ticker}* —")
        await _slack_post(webhook_url, slack_text)

    if whatsapp_phone and whatsapp_apikey:
        await _whatsapp_send(whatsapp_phone, whatsapp_apikey, text)


async def send_daily_digest(
    webhook_url: str | None,
    display_name: str,
    signals: list[dict],
    whatsapp_phone: str | None = None,
    whatsapp_apikey: str | None = None,
) -> None:
    """Send a morning digest of all watchlist signals via Slack and/or WhatsApp."""
    if not signals:
        return

    from datetime import datetime, timezone
    date_str = datetime.now(tz=timezone.utc).strftime("%a %b %-d")

    header = f"Daily Watchlist - {date_str}"
    if display_name:
        header += f" for {display_name}"

    lines = [header]
    for s in signals:
        emoji = _SIGNAL_EMOJI.get(s.get("signal", "HOLD"), "📊")
        score_pct = round((s.get("score") or 0) * 100)
        conv = _CONVICTION_LABEL.get(s.get("conviction") or "", "")
        row = f"{emoji} {s['ticker']}: {s.get('signal', 'HOLD')} | Score {score_pct}"
        if conv:
            row += f" | {conv}"
        lines.append(row)

    lines.append("View full analysis at sta.samsbpm.com")
    text = "\n".join(lines)

    if webhook_url:
        await _slack_post(webhook_url, text)

    if whatsapp_phone and whatsapp_apikey:
        await _whatsapp_send(whatsapp_phone, whatsapp_apikey, text)


async def _slack_post(webhook_url: str, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"text": text})
            if resp.status_code != 200:
                logger.warning("slack_webhook_failed", status=resp.status_code, body=resp.text[:200])
    except Exception as exc:
        logger.warning("slack_webhook_error", error=str(exc))


async def _whatsapp_send(phone: str, apikey: str, text: str) -> None:
    """Send a WhatsApp message via CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/)."""
    url = (
        "https://api.callmebot.com/whatsapp.php"
        f"?phone={urllib.parse.quote(phone)}"
        f"&text={urllib.parse.quote(text)}"
        f"&apikey={urllib.parse.quote(apikey)}"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("whatsapp_send_failed", status=resp.status_code, body=resp.text[:200])
    except Exception as exc:
        logger.warning("whatsapp_send_error", error=str(exc))
