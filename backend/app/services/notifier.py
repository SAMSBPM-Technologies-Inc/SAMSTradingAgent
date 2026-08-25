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


def _level_lines(
    price: float | None, target: float | None, stop: float | None
) -> list[str]:
    """
    Render the protective levels so they can be judged, not just read.

    A level is meaningless on its own — it only means something relative to
    where the stock is now and to the other level. Both distances are quoted,
    and when both exist so is the ratio between them, because that ratio is the
    single number that says whether the trade is worth taking: risking 8% to
    make 7% is a losing proposition at any hit rate below ~53%, and no amount of
    conviction in the headline changes that arithmetic.
    """
    lines: list[str] = []
    if not target and not stop:
        return lines

    if target:
        pct = f" ({(target - price) / price:+.1%})" if price else ""
        lines.append(f"Target: {_money(target)}{pct}")
    if stop:
        pct = f" ({(stop - price) / price:+.1%})" if price else ""
        lines.append(f"Stop: {_money(stop)}{pct}")

    if price and target and stop and target > price > stop:
        reward = target - price
        risk = price - stop
        if risk > 0:
            lines.append(f"Reward:risk {reward / risk:.1f} : 1")
    return lines


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
    current_price: float | None = None,
    risk_score: float | None = None,
    time_horizon: str | None = None,
    position_size_pct: float | None = None,
    whatsapp_phone: str | None = None,
    whatsapp_apikey: str | None = None,
) -> None:
    """
    Send a signal-flip / high-conviction alert via Slack and/or WhatsApp.

    The message has to survive being read on a phone, out of context, with no
    chart in front of you. "Target: $102.00 | Stop: $87.50" did not: it never
    said what those levels were measured from, so it was impossible to tell a
    2% target from a 20% one, or to see that a stop can sit further away than
    the target and turn a plausible-looking setup into a bad bet. Each level is
    now quoted with its distance from the price the call was made at, and the
    two are compared to each other.
    """
    emoji = _SIGNAL_EMOJI.get(new_signal, "📊")
    conv_label = _CONVICTION_LABEL.get(conviction or "", "")
    score_pct = round(score * 100)
    conf_pct = round(confidence * 100)

    if old_signal and old_signal != new_signal:
        header = f"{emoji} {ticker} signal flipped: {old_signal} -> {new_signal}"
    else:
        header = f"{emoji} {ticker} - {new_signal} (High Conviction)"

    second = f"Score: {score_pct}/100 | {conv_label} | Confidence: {conf_pct}%"
    if risk_score is not None:
        second += f" | Risk: {risk_score:.1f}/10"
    lines = [header, second]

    if current_price:
        lines.append(f"Price now: {_money(current_price)}")
    lines.extend(_level_lines(current_price, price_target, stop_loss))
    if time_horizon:
        lines.append(f"Expected horizon: {time_horizon}")
    if position_size_pct and new_signal == "BUY":
        # Answers "how much do I put in this" in the message that prompts the
        # question, instead of leaving the user to find the setting.
        lines.append(
            f"Your sizing: {position_size_pct:.0%} of account equity, "
            f"adjusted for volatility"
        )
    lines.append("SAMSBPM Trading - sta.samsbpm.com")

    text = "\n".join(lines)

    if webhook_url:
        # Slack uses mrkdwn — wrap key parts in asterisks for bold
        slack_text = text.replace(f"{ticker} signal flipped:", f"*{ticker}* signal flipped:") \
                         .replace(f"{ticker} -", f"*{ticker}* —")
        await _slack_post(webhook_url, slack_text)

    if whatsapp_phone and whatsapp_apikey:
        await _whatsapp_send(whatsapp_phone, whatsapp_apikey, text)


async def send_broker_alert(
    webhook_url: str | None,
    *,
    down_minutes: int,
    recovered: bool,
    trading_mode: str,
    whatsapp_phone: str | None = None,
    whatsapp_apikey: str | None = None,
) -> None:
    """
    Tell the user the broker session is down (or back).

    Worth waking someone for because it is silent otherwise: the agent keeps
    scoring and the UI keeps working, orders are simply refused. The failure is
    invisible until you try to trade, which is the worst time to discover it.
    """
    if recovered:
        text = "\n".join([
            "✅ IB Gateway reconnected",
            f"Back after {down_minutes} min. Trading is live again ({trading_mode}).",
            "SAMSBPM Trading - sta.samsbpm.com",
        ])
    else:
        text = "\n".join([
            "🔌 IB Gateway disconnected",
            f"No broker session for {down_minutes} min — orders are being refused ({trading_mode}).",
            "Common after IBKR's weekend maintenance or an unanswered 2FA prompt.",
            "Fix: Orders page → Broker → Reconnect, then Restart Gateway if that fails.",
            "SAMSBPM Trading - sta.samsbpm.com",
        ])

    if webhook_url:
        await _slack_post(webhook_url, text)
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


async def _send_email(to: str, subject: str, text: str, html: str) -> str | None:
    """
    Send an email. Never raises — a mail outage must not stop trading.

    Returns None on success, or a short reason on failure. Callers that are
    firing-and-forgetting can ignore it; the test endpoint surfaces it so SMTP
    can be diagnosed from the UI rather than the server logs.
    """
    import asyncio

    from app.config import get_settings

    s = get_settings()
    if not s.email_enabled:
        logger.debug("email_disabled", hint="SMTP_HOST/USERNAME/PASSWORD not configured")
        return "email not configured (SMTP_HOST / SMTP_USERNAME / SMTP_PASSWORD unset)"
    if not to:
        return "no recipient address"
    try:
        await asyncio.to_thread(_send_email_blocking, to, subject, text, html)
        logger.info("email_sent", to=to, subject=subject)
        return None
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        logger.warning("email_send_failed", to=to, subject=subject, error=reason)
        return reason


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


async def send_test_email(to: str) -> str | None:
    """Deliverability check. Returns None on success or the failure reason."""
    subject = "[TEST] SAMSBPM Trading Agent — email notifications working"
    text = (
        "This is a test from your trading agent.\n\n"
        "If you received it, trade notifications will reach you: every order the "
        "agent submits sends a message like this one, with the ticker, size, "
        "limit price and protective levels."
    )
    html = """\
<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:520px;
            margin:0 auto;padding:24px;color:#111827">
  <p style="margin:0 0 4px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
            color:#6b7280">SAMSBPM Trading Agent</p>
  <h2 style="margin:0 0 12px;font-size:18px;font-weight:600">Email notifications are working</h2>
  <p style="margin:0;font-size:13px;line-height:1.6;color:#374151">
    Every order the agent submits will send a message like this one — ticker,
    size, limit price, and the stop and target protecting the position.
  </p>
</div>"""
    return await _send_email(to, subject, text, html)
