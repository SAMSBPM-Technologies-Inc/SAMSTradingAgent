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


# ── Email ─────────────────────────────────────────────────────────────────────

def _send_email_blocking(to: str, subject: str, text: str, html: str) -> None:
    """
    Synchronous SMTP send. Runs in a worker thread — smtplib blocks, and this is
    called from async request/pipeline paths where blocking the loop would stall
    every other ticker being processed.
    """
    import smtplib
    from email.message import EmailMessage

    from app.config import get_settings

    s = get_settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.email_from
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    if s.smtp_port == 465:
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20) as srv:
            srv.login(s.smtp_username, s.smtp_password)
            srv.send_message(msg)
    else:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as srv:
            if s.smtp_use_tls:
                srv.starttls()
            srv.login(s.smtp_username, s.smtp_password)
            srv.send_message(msg)


async def _send_email(to: str, subject: str, text: str, html: str) -> None:
    """Fire-and-forget email. Never raises — a mail outage must not stop trading."""
    import asyncio

    from app.config import get_settings

    s = get_settings()
    if not s.email_enabled:
        logger.debug("email_disabled", hint="SMTP_HOST/USERNAME/PASSWORD not configured")
        return
    if not to:
        return
    try:
        await asyncio.to_thread(_send_email_blocking, to, subject, text, html)
        logger.info("email_sent", to=to, subject=subject)
    except Exception as exc:
        logger.warning("email_send_failed", to=to, subject=subject, error=str(exc))


def _money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


async def send_trade_email(
    to: str,
    *,
    action: str,                 # "BUY" or "SELL"
    ticker: str,
    qty: int,
    limit_price: float,
    order_id: str | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    is_paper: bool = True,
    account_id: str = "",
    trigger: str = "",
    signal_score: float | None = None,
) -> None:
    """
    Notify the user that an order was submitted to the broker.

    Sent on submission, not on fill — a resting limit order may not fill for
    hours, and knowing the agent acted is the point. The subject line leads with
    PAPER/LIVE because that distinction is the one that matters most at a glance.
    """
    mode = "PAPER" if is_paper else "LIVE"
    verb = "Bought" if action.upper() == "BUY" else "Sold"
    notional = (qty or 0) * (limit_price or 0)
    subject = f"[{mode}] {verb} {qty} {ticker} @ {_money(limit_price)}"

    rows: list[tuple[str, str]] = [
        ("Action", f"{action.upper()} {qty} {ticker}"),
        ("Limit price", _money(limit_price)),
        ("Notional", _money(notional)),
    ]
    if stop_loss is not None:
        rows.append(("Stop loss", _money(stop_loss)))
    if take_profit is not None:
        rows.append(("Take profit", _money(take_profit)))
    if signal_score is not None:
        rows.append(("Signal score", f"{signal_score:.2f}"))
    if trigger:
        rows.append(("Triggered by", trigger))
    if order_id:
        rows.append(("Broker order", str(order_id)))
    if account_id:
        rows.append(("Account", account_id))
    rows.append(("Mode", f"{mode} trading"))

    text = f"{subject}\n\n" + "\n".join(f"{k}: {v}" for k, v in rows)

    accent = "#16a34a" if action.upper() == "BUY" else "#dc2626"
    banner = "" if is_paper else (
        '<p style="margin:0 0 16px;padding:10px 12px;background:#fef2f2;'
        'border:1px solid #fecaca;border-radius:8px;color:#991b1b;font-size:13px">'
        '<strong>Live trading.</strong> This order was placed with real money.</p>'
    )
    body_rows = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#6b7280;font-size:13px;'
        f'white-space:nowrap">{k}</td>'
        f'<td style="padding:6px 0;font-size:13px;font-weight:500;'
        f'font-variant-numeric:tabular-nums">{v}</td></tr>'
        for k, v in rows
    )
    html = f"""\
<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:520px;
            margin:0 auto;padding:24px;color:#111827">
  <p style="margin:0 0 4px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
            color:#6b7280">SAMSBPM Trading Agent</p>
  <h2 style="margin:0 0 16px;font-size:18px;font-weight:600;color:{accent}">
    {verb} {qty} {ticker} @ {_money(limit_price)}
  </h2>
  {banner}
  <table style="border-collapse:collapse;width:100%">{body_rows}</table>
  <p style="margin:20px 0 0;font-size:12px;color:#6b7280">
    Order submitted to the broker. A resting limit order may take time to fill —
    check the dashboard for current holdings.
  </p>
</div>"""

    await _send_email(to, subject, text, html)
