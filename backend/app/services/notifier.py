"""
Notification Service
────────────────────
Sends Slack webhook messages for signal alerts and daily digests.
All functions are fire-and-forget — failures are logged but never raise.
"""
import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

_SIGNAL_EMOJI = {"BUY": "📈", "SELL": "📉", "HOLD": "📊"}
_CONVICTION_LABEL = {"HIGH": "Strong Signal", "MEDIUM": "Moderate", "LOW": "Weak Signal"}


async def send_signal_alert(
    webhook_url: str,
    ticker: str,
    old_signal: str | None,
    new_signal: str,
    score: float,
    conviction: str | None,
    confidence: float,
    price_target: float | None,
    stop_loss: float | None,
) -> None:
    """Send a Slack notification when a signal flips or becomes HIGH conviction."""
    if not webhook_url:
        return

    emoji = _SIGNAL_EMOJI.get(new_signal, "📊")
    conv_label = _CONVICTION_LABEL.get(conviction or "", "")
    score_pct = round(score * 100)
    conf_pct = round(confidence * 100)

    if old_signal and old_signal != new_signal:
        header = f"{emoji} *{ticker}* signal flipped: {old_signal} → *{new_signal}*"
    else:
        header = f"{emoji} *{ticker}* — *{new_signal}* (High Conviction)"

    lines = [header, f"Score: {score_pct}  |  {conv_label}  |  Confidence: {conf_pct}%"]
    if price_target or stop_loss:
        parts = []
        if price_target:
            parts.append(f"Target: ${price_target:.2f}")
        if stop_loss:
            parts.append(f"Stop: ${stop_loss:.2f}")
        lines.append("  |  ".join(parts))
    lines.append("_SAMSBPM Trading — sta.samsbpm.com_")

    await _post(webhook_url, "\n".join(lines))


async def send_daily_digest(
    webhook_url: str,
    display_name: str,
    signals: list[dict],
) -> None:
    """Send a morning digest of all watchlist signals."""
    if not webhook_url or not signals:
        return

    from datetime import datetime, timezone
    date_str = datetime.now(tz=timezone.utc).strftime("%a %b %-d")

    lines = [f"📋 *Daily Watchlist — {date_str}*"]
    if display_name:
        lines[0] += f" for {display_name}"

    for s in signals:
        emoji = _SIGNAL_EMOJI.get(s.get("signal", "HOLD"), "📊")
        score_pct = round((s.get("score") or 0) * 100)
        conv = _CONVICTION_LABEL.get(s.get("conviction") or "", "")
        row = f"{emoji} *{s['ticker']}*: {s.get('signal', 'HOLD')} | Score {score_pct}"
        if conv:
            row += f" | {conv}"
        lines.append(row)

    lines.append("_View full analysis at sta.samsbpm.com_")
    await _post(webhook_url, "\n".join(lines))


async def _post(webhook_url: str, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json={"text": text})
            if resp.status_code != 200:
                logger.warning("slack_webhook_failed", status=resp.status_code, body=resp.text[:200])
    except Exception as exc:
        logger.warning("slack_webhook_error", error=str(exc))
