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


async def send_capability_alert(
    webhook_url: str | None,
    *,
    degraded: list[tuple[str, str]],
    recovered: list[str],
    summary: str,
    whatsapp_phone: str | None = None,
    whatsapp_apikey: str | None = None,
) -> None:
    """
    Tell the user a data source stopped working, or started again.

    Worth sending for the same reason the broker alert is: the failure is
    otherwise silent. Scoring continues, the UI works, verdicts keep publishing
    — they are just built on a neutral placeholder where a factor used to be.
    Nothing about the screen looks different, which is precisely the problem.

    Each degraded entry carries what it *costs*, not just that it happened. "FRED
    is failing" is not actionable on a phone; "the macro factor is pinned to 0.50
    on every score" tells you how much to discount what you are looking at.

    Never mentions a source that is merely unconfigured. A key you chose not to
    set is not news, and a channel that pages about settled configuration is one
    people mute.
    """
    if not degraded and not recovered:
        return

    lines: list[str] = []
    if degraded:
        lines.append("⚠️ Data source degraded")
        for label, impact in degraded:
            lines.append(f"{label} — {impact}")
    if recovered:
        lines.append("✅ Recovered: " + ", ".join(recovered))
    lines.append(summary)
    lines.append("Full picture: sta.samsbpm.com/status")
    lines.append("SAMSBPM Trading - sta.samsbpm.com")

    text = "\n".join(lines)

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


#: Phrases CallMeBot puts in the *body* of an otherwise successful-looking
#: response. Checked case-insensitively.
_WHATSAPP_ERROR_MARKERS = (
    "apikey is invalid",
    "api key is invalid",
    "you need to activate",
    "not registered",
    "missing",
    "invalid phone",
    "error",
)


async def _whatsapp_send(phone: str, apikey: str, text: str) -> str | None:
    """
    Send a WhatsApp message via CallMeBot.
    https://www.callmebot.com/blog/free-api-whatsapp-messages/

    Returns None on success, or a short reason on failure.

    **The status code does not tell you whether it worked.** CallMeBot answers
    an invalid API key with `203 Non-Authoritative Information` and puts the
    real outcome in the HTML body — so the old `!= 200` check both missed every
    real failure and would have cried wolf on successes. A dead API key
    therefore looked exactly like a delivered message, which is the worst
    possible failure mode for a notification channel: silent, and indefinite.
    The body is what gets inspected.
    """
    url = (
        "https://api.callmebot.com/whatsapp.php"
        f"?phone={urllib.parse.quote(phone)}"
        f"&text={urllib.parse.quote(text)}"
        f"&apikey={urllib.parse.quote(apikey)}"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        logger.warning("whatsapp_send_error", error=reason)
        return reason

    body = (resp.text or "").strip()
    if resp.status_code >= 400:
        reason = f"HTTP {resp.status_code}"
        logger.warning("whatsapp_send_failed", status=resp.status_code, body=body[:200])
        return reason

    # CallMeBot echoes the whole outgoing message back before saying what went
    # wrong. Cut to the error itself: the reason is surfaced in the UI and
    # written to logs, and neither is a place to reproduce the alert text.
    flat = _strip_tags(body)
    lowered = flat.lower()
    hit = next((m for m in _WHATSAPP_ERROR_MARKERS if m in lowered), None)
    if hit:
        reason = flat[lowered.index(hit):][:180] or f"CallMeBot rejected the request ({hit})"
        logger.warning(
            "whatsapp_send_rejected",
            status=resp.status_code, phone=_mask_phone(phone), reason=reason,
        )
        return reason

    logger.info("whatsapp_sent", phone=_mask_phone(phone))
    return None


def _strip_tags(html: str) -> str:
    """CallMeBot answers in HTML; the useful part is the sentence inside it."""
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _mask_phone(phone: str) -> str:
    """Log enough to tell two numbers apart, not enough to be a phone number."""
    digits = "".join(c for c in phone if c.isdigit())
    return f"…{digits[-4:]}" if len(digits) >= 4 else "…"


# ── Email ─────────────────────────────────────────────────────────────────────

def _send_email_blocking(to: str, subject: str, text: str, html: str, reply_to: str | None = None) -> None:
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
    if reply_to:
        # CR/LF stripped before it reaches a header. Pydantic already rejects
        # an address containing them, but this function must not depend on its
        # only caller having validated for it — header injection is exactly the
        # bug that survives a refactor.
        msg["Reply-To"] = reply_to.replace("\r", "").replace("\n", "").strip()
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


async def _send_email(to: str, subject: str, text: str, html: str, reply_to: str | None = None) -> str | None:
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
        await asyncio.to_thread(_send_email_blocking, to, subject, text, html, reply_to)
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
    trade_id: str | None = None,
    rationale: str | None = None,
) -> None:
    """
    Notify the user that an order was **submitted** to the broker.

    This is the first of a pair; `send_fill_email` sends the second when the
    order actually fills. The wording has to keep them apart at a glance on a
    lock screen — "Bought 57 HXL" was wrong here, because nothing has been
    bought yet: a resting limit order may never fill. So this one says *placed*
    and quotes the limit, and only the fill message says *filled* and quotes a
    price that was really paid.
    """
    mode = "PAPER" if is_paper else "LIVE"
    side = "Buy" if action.upper() == "BUY" else "Sell"
    notional = (qty or 0) * (limit_price or 0)
    subject = f"[{mode}] {side} order placed: {qty} {ticker} @ {_money(limit_price)} limit"

    rows: list[tuple[str, str]] = []
    if trade_id:
        # The same number that identifies this trade in the Orders table and
        # in every later fill/exit message about it — put first so it reads
        # as the record's name, not one detail among many.
        rows.append(("Reference", trade_id))
    rows.extend([
        ("Action", f"{action.upper()} {qty} {ticker}"),
        ("Limit price", _money(limit_price)),
        ("Notional", _money(notional)),
    ])
    if stop_loss is not None:
        rows.append(("Stop loss", _money(stop_loss)))
    if take_profit is not None:
        rows.append(("Take profit", _money(take_profit)))
    if signal_score is not None:
        rows.append(("Signal score", f"{signal_score:.2f}"))
    if trigger:
        rows.append(("Triggered by", trigger))
    if rationale:
        # The one row that answers the question a person actually has when an
        # order lands on their phone: *why*. Placed after the trigger, which
        # says which mechanism fired, because this says what the mechanism saw.
        rows.append(("Why", rationale))
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
    {side} order placed: {qty} {ticker} @ {_money(limit_price)}
  </h2>
  {banner}
  <table style="border-collapse:collapse;width:100%">{body_rows}</table>
  <p style="margin:20px 0 0;font-size:12px;color:#6b7280">
    Submitted to the broker — nothing has been bought or sold yet. A resting
    limit order may take time to fill, and you will get a second message when
    it does.
  </p>
</div>"""

    await _send_email(to, subject, text, html)


async def send_trade_alert(
    *,
    webhook_url: str | None = None,
    whatsapp_phone: str | None = None,
    whatsapp_apikey: str | None = None,
    action: str,
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
    trade_id: str | None = None,
    rationale: str | None = None,
) -> None:
    """
    Push the same order event as `send_trade_email` down the chat channels.

    Takes the same keyword arguments as the email so callers can forward one
    payload to both without filtering it — a field added to the email must not
    be able to break the chat path.

    Trades were the one event that only ever emailed, while signal flips, broker
    outages and the digest all reached Slack and WhatsApp — so the notification
    that matters most (money moved) was the slowest to arrive. Same order, same
    numbers, phrased for a phone: one glance has to answer *what was bought or
    sold, how much, and is this real money*, which is why PAPER/LIVE leads.
    """
    mode = "PAPER" if is_paper else "LIVE"
    side = "Buy" if action.upper() == "BUY" else "Sell"
    notional = (qty or 0) * (limit_price or 0)

    lines = [
        f"📤 [{mode}] {side} order placed: {qty} {ticker} @ {_money(limit_price)} limit",
        f"Notional: {_money(notional)}",
    ]
    if trade_id:
        lines.append(f"Ref: {trade_id}")
    lines.extend(_level_lines(limit_price, take_profit, stop_loss))
    if signal_score is not None:
        lines.append(f"Signal score: {signal_score:.2f}")
    if trigger:
        lines.append(f"Triggered by: {trigger}")
    if rationale:
        lines.append(f"Why: {rationale}")
    if order_id:
        lines.append(f"Broker order: {order_id}")
    if not is_paper:
        lines.append("⚠️ Placed with real money.")
    lines.append("Not filled yet — you'll get a second message when it is.")
    lines.append("SAMSBPM Trading - sta.samsbpm.com")

    text = "\n".join(lines)

    if webhook_url:
        await _slack_post(webhook_url, text.replace(ticker, f"*{ticker}*", 1))
    if whatsapp_phone and whatsapp_apikey:
        await _whatsapp_send(whatsapp_phone, whatsapp_apikey, text)


# ── Fills ─────────────────────────────────────────────────────────────────────
#
# The second half of the pair. Submission says the agent acted; this says the
# market agreed, and it is the only one that carries numbers that are real —
# what was actually paid, and on an exit, what was actually made.


def _fill_message(
    *,
    kind: str,                   # "entry" | "partial" | "exit"
    action: str,
    ticker: str,
    qty: float,
    fill_price: float | None,
    limit_price: float | None = None,
    ordered_qty: float | None = None,
    entry_price: float | None = None,
    pnl: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    is_paper: bool = True,
    exit_reason: str = "",
    trade_id: str | None = None,
) -> tuple[str, str, list[tuple[str, str]]]:
    """
    Build the fill notification once, for every channel.

    Returns `(emoji, headline, rows)`. Email and chat render this same tuple —
    the two senders drifting apart is precisely how trades ended up emailing and
    nothing else, so there is one place where a fill's wording is decided.

    The headline differs by kind because the question each answers is different.
    An entry asks *what do I now own and at what price*; an exit asks *did I
    make money*, so realised P&L is the headline and everything else is detail.
    """
    mode = "PAPER" if is_paper else "LIVE"
    rows: list[tuple[str, str]] = []
    if trade_id:
        # Same reference the submission message carried, so a reader can tell
        # this fill is the other half of that earlier "order placed" alert.
        rows.append(("Reference", trade_id))

    if kind == "exit":
        emoji = "🏁"
        pnl_str = ""
        if pnl is not None:
            pct = ""
            if entry_price and qty:
                cost = float(entry_price) * float(qty)
                if cost:
                    pct = f" ({pnl / cost:+.1%})"
            pnl_str = f": {'+' if pnl >= 0 else '−'}{_money(abs(pnl))}{pct}"
            emoji = "🟩" if pnl >= 0 else "🟥"
        headline = f"[{mode}] Closed {ticker}{pnl_str}"
        rows.append(("Sold", f"{_qty(qty)} {ticker}"))
        if fill_price:
            rows.append(("Exit price", _money(fill_price)))
        if entry_price:
            rows.append(("Entry price", _money(entry_price)))
        if pnl is not None:
            rows.append(("Realised P&L", f"{'+' if pnl >= 0 else '−'}{_money(abs(pnl))}"))
        if exit_reason:
            rows.append(("Closed by", exit_reason))
        return emoji, headline, rows

    verb = "bought" if action.upper() == "BUY" else "sold"
    if kind == "partial":
        emoji = "◐"
        headline = (
            f"[{mode}] Partially filled: {verb} {_qty(qty)} of "
            f"{_qty(ordered_qty or qty)} {ticker} @ {_money(fill_price)}"
        )
    else:
        emoji = "✅"
        headline = f"[{mode}] Filled: {verb} {_qty(qty)} {ticker} @ {_money(fill_price)}"

    rows.append(("Filled", f"{_qty(qty)} {ticker} @ {_money(fill_price)}"))
    if fill_price and qty:
        rows.append(("Cost", _money(float(fill_price) * float(qty))))

    # Slippage is the one number a fill tells you that the submission could not.
    # Both figures are unsigned and the word carries the direction: "$0.02
    # better (-0.03%)" makes a reader stop and work out whether a minus sign is
    # good news, which is exactly the wrong thing to do to someone glancing at a
    # phone. "better"/"worse" is already from their point of view.
    if fill_price and limit_price:
        diff = float(fill_price) - float(limit_price)
        if abs(diff) >= 0.005:
            better = diff < 0 if action.upper() == "BUY" else diff > 0
            rows.append((
                "vs limit",
                f"{_money(abs(diff))} {'better' if better else 'worse'} "
                f"({abs(diff) / float(limit_price):.2%})",
            ))

    if stop_loss:
        rows.append(("Stop", _money(stop_loss)))
    if take_profit:
        rows.append(("Target", _money(take_profit)))
    return emoji, headline, rows


async def send_fill_alert(
    *,
    webhook_url: str | None = None,
    whatsapp_phone: str | None = None,
    whatsapp_apikey: str | None = None,
    **fill,
) -> None:
    """Fill notification for Slack and WhatsApp."""
    emoji, headline, rows = _fill_message(**fill)
    lines = [f"{emoji} {headline}"] + [f"{k}: {v}" for k, v in rows]
    if not fill.get("is_paper", True):
        lines.append("⚠️ Real money.")
    lines.append("SAMSBPM Trading - sta.samsbpm.com")
    text = "\n".join(lines)

    ticker = fill.get("ticker", "")
    if webhook_url:
        await _slack_post(webhook_url, text.replace(ticker, f"*{ticker}*", 1))
    if whatsapp_phone and whatsapp_apikey:
        await _whatsapp_send(whatsapp_phone, whatsapp_apikey, text)


async def send_fill_email(to: str, **fill) -> None:
    """Fill notification by email — same content as `send_fill_alert`."""
    emoji, headline, rows = _fill_message(**fill)
    subject = headline
    text = f"{headline}\n\n" + "\n".join(f"{k}: {v}" for k, v in rows)

    kind = fill.get("kind")
    pnl = fill.get("pnl")
    if kind == "exit" and pnl is not None:
        accent = "#16a34a" if pnl >= 0 else "#dc2626"
    elif fill.get("action", "").upper() == "BUY":
        accent = "#16a34a"
    else:
        accent = "#dc2626"

    banner = "" if fill.get("is_paper", True) else (
        '<p style="margin:0 0 16px;padding:10px 12px;background:#fef2f2;'
        'border:1px solid #fecaca;border-radius:8px;color:#991b1b;font-size:13px">'
        '<strong>Live trading.</strong> This executed with real money.</p>'
    )
    body_rows = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#6b7280;font-size:13px;'
        f'white-space:nowrap">{k}</td>'
        f'<td style="padding:6px 0;font-size:13px;font-weight:500;'
        f'font-variant-numeric:tabular-nums">{v}</td></tr>'
        for k, v in rows
    )
    footer = (
        "This position is closed. See the Performance page for how it sits "
        "against the rest of the record."
        if kind == "exit" else
        "The order has executed — this price is what you actually paid."
    )
    html = f"""\
<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:520px;
            margin:0 auto;padding:24px;color:#111827">
  <p style="margin:0 0 4px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
            color:#6b7280">SAMSBPM Trading Agent</p>
  <h2 style="margin:0 0 16px;font-size:18px;font-weight:600;color:{accent}">
    {emoji} {headline}
  </h2>
  {banner}
  <table style="border-collapse:collapse;width:100%">{body_rows}</table>
  <p style="margin:20px 0 0;font-size:12px;color:#6b7280">{footer}</p>
</div>"""

    await _send_email(to, subject, text, html)


def _qty(v) -> str:
    """Whole share counts read as integers; fractional ones keep their decimals."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


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


# ── Contact form ──────────────────────────────────────────────────────────────

async def send_contact_message(name: str, email: str, message: str,
                               interest: str | None = None) -> str | None:
    """
    Deliver a landing-page contact submission to `CONTACT_EMAIL`.

    Returns None on success or a short reason on failure — the route surfaces
    it, because a visitor who fills in a form and is told "sent" when nothing
    was sent has been lied to, and unlike a trade alert there is no second
    channel that might still carry the message.

    Everything here is attacker-controlled text. It is escaped for the HTML
    part, and the sender's address goes in Reply-To rather than From so the
    message still originates from an address the SMTP provider authenticates.
    """
    import html as html_mod

    from app.config import get_settings

    to = get_settings().contact_email
    # Subject lines are headers; a newline in one splits the message.
    safe_name = name.replace("\r", " ").replace("\n", " ").strip()

    # Validated against a fixed set at the schema, so this cannot carry
    # arbitrary text into a header — but it is still escaped for the HTML part
    # like everything else here.
    safe_interest = (interest or "").replace("\r", " ").replace("\n", " ").strip()

    subject = f"[STA] Contact from {safe_name}"
    text = (
        f"Name:    {safe_name}\n"
        f"Email:   {email}\n"
        + (f"Wants:   {safe_interest}\n" if safe_interest else "")
        + f"\n"
        f"{message}\n"
    )
    body_html = html_mod.escape(message).replace("\n", "<br>")
    interest_html = (
        f"<br><strong>Wants:</strong> {html_mod.escape(safe_interest)}"
        if safe_interest else ""
    )
    html_body = (
        f"<p><strong>Name:</strong> {html_mod.escape(safe_name)}<br>"
        f"<strong>Email:</strong> {html_mod.escape(email)}{interest_html}</p>"
        f"<hr><p>{body_html}</p>"
    )

    return await _send_email(to, subject, text, html_body, reply_to=email)


# ── Password reset ────────────────────────────────────────────────────────────

async def send_password_reset(email: str, link: str, ttl_minutes: int) -> str | None:
    """
    Mail a one-time reset link.

    Returns None on success or a short reason on failure. The route does not
    surface that reason: telling a stranger the difference between "we sent it"
    and "there is no such account" is the enumeration this whole flow is shaped
    to avoid. It is logged instead, which is where somebody debugging a missing
    email should be looking anyway.

    The mail says what to do if it was not requested, and it does **not** say
    what the account can do or what plan it is on — a reset email reaches a
    mailbox that may no longer belong to the account holder.
    """
    subject = "Reset your SAMSTradingAgent password"
    text = (
        "Someone asked to reset the password for this address.\n\n"
        f"{link}\n\n"
        f"The link works once and expires in {ttl_minutes} minutes.\n\n"
        "If that was not you, nothing has changed and you can ignore this "
        "message. Your current password still works.\n"
    )
    html = (
        "<p>Someone asked to reset the password for this address.</p>"
        f'<p><a href="{link}">Set a new password</a></p>'
        f"<p>The link works once and expires in {ttl_minutes} minutes.</p>"
        "<p>If that was not you, nothing has changed and you can ignore this "
        "message. Your current password still works.</p>"
    )
    return await _send_email(email, subject, text, html)
