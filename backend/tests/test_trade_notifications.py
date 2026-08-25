"""
Trade notifications reach every configured channel.

The defect these cover: order events emailed and did nothing else, while every
other alert in the system also went to Slack and WhatsApp. The bug was not in
the sending — it was that `_notify_trade` only ever looked up an email address,
so a correctly configured WhatsApp number was silently never consulted.
"""
import asyncio

import pytest

from app.services import notifier, trade_manager

ENTRY = dict(
    action="BUY", ticker="HXL", qty=57, limit_price=61.40, order_id="1043",
    stop_loss=56.90, take_profit=70.10, is_paper=True, account_id="DU1",
    trigger="signal BUY", signal_score=0.74,
)


@pytest.fixture
def captured(monkeypatch):
    """Intercept both wire calls; nothing in these tests touches the network."""
    out: dict = {}

    async def fake_wa(phone, apikey, text):
        out["whatsapp"] = {"phone": phone, "apikey": apikey, "text": text}

    async def fake_slack(url, text):
        out["slack"] = {"url": url, "text": text}

    monkeypatch.setattr(notifier, "_whatsapp_send", fake_wa)
    monkeypatch.setattr(notifier, "_slack_post", fake_slack)
    return out


def test_trade_alert_goes_to_both_chat_channels(captured):
    asyncio.run(notifier.send_trade_alert(
        webhook_url="https://hooks.example/x",
        whatsapp_phone="+15551234567", whatsapp_apikey="key", **ENTRY
    ))
    assert captured["whatsapp"]["phone"] == "+15551234567"
    assert captured["slack"]["url"] == "https://hooks.example/x"


def test_trade_alert_leads_with_mode_and_carries_the_levels(captured):
    asyncio.run(notifier.send_trade_alert(
        whatsapp_phone="+1", whatsapp_apikey="k", **ENTRY
    ))
    text = captured["whatsapp"]["text"]
    # PAPER/LIVE first: read on a phone, that is the line that decides whether
    # this message is worth acting on.
    assert text.splitlines()[0].startswith(
        "📤 [PAPER] Buy order placed: 57 HXL @ $61.40 limit")
    assert "Target: $70.10 (+14.2%)" in text
    assert "Stop: $56.90 (-7.3%)" in text
    assert "Reward:risk 1.9 : 1" in text


def test_live_order_says_so(captured):
    asyncio.run(notifier.send_trade_alert(
        whatsapp_phone="+1", whatsapp_apikey="k",
        **{**ENTRY, "is_paper": False, "action": "SELL"},
    ))
    text = captured["whatsapp"]["text"]
    assert "[LIVE]" in text
    assert "real money" in text


def test_alert_accepts_every_email_keyword():
    """
    The two senders take one payload. If they drift apart, the chat channel
    breaks at runtime on a field the email added — exactly the class of failure
    that made trades email-only in the first place.
    """
    import inspect

    email_kw = set(inspect.signature(notifier.send_trade_email).parameters) - {"to"}
    alert_kw = set(inspect.signature(notifier.send_trade_alert).parameters)
    assert email_kw <= alert_kw


def test_notify_trade_fans_out_to_whatsapp_without_an_email(monkeypatch):
    """A user with no email configured must still get the WhatsApp message."""
    calls = []

    async def targets(_user_id):
        return {"email": "", "webhook_url": None,
                "whatsapp_phone": "+1", "whatsapp_apikey": "k"}

    async def fake_alert(**kw):
        calls.append(kw)

    monkeypatch.setattr(trade_manager, "_trade_notify_targets", targets)
    monkeypatch.setattr(notifier, "send_trade_alert", fake_alert)

    asyncio.run(trade_manager._notify_trade("u1", **ENTRY))
    assert len(calls) == 1
    assert calls[0]["whatsapp_phone"] == "+1"
    assert calls[0]["ticker"] == "HXL"


def test_a_failing_email_does_not_swallow_the_whatsapp(monkeypatch):
    """
    Channels are independent. An SMTP outage silencing the fast channel is how
    a trade goes unnoticed.
    """
    calls = []

    async def targets(_user_id):
        return {"email": "a@b.c", "webhook_url": None,
                "whatsapp_phone": "+1", "whatsapp_apikey": "k"}

    async def boom(_to, **_kw):
        raise RuntimeError("smtp down")

    async def fake_alert(**kw):
        calls.append(kw)

    monkeypatch.setattr(trade_manager, "_trade_notify_targets", targets)
    monkeypatch.setattr(notifier, "send_trade_email", boom)
    monkeypatch.setattr(notifier, "send_trade_alert", fake_alert)

    asyncio.run(trade_manager._notify_trade("u1", **ENTRY))
    assert len(calls) == 1


def test_opting_out_silences_every_channel(monkeypatch):
    """`notify_on_trade=false` is one preference about trade events, not an
    email-only switch — an opted-out user must not get a WhatsApp either."""
    calls = []

    async def targets(_user_id):
        return {}

    async def record(*_a, **kw):
        calls.append(kw)

    monkeypatch.setattr(trade_manager, "_trade_notify_targets", targets)
    monkeypatch.setattr(notifier, "send_trade_email", record)
    monkeypatch.setattr(notifier, "send_trade_alert", record)

    asyncio.run(trade_manager._notify_trade("u1", **ENTRY))
    assert calls == []


# ── The fill half of the pair ────────────────────────────────────────────────
#
# Submission and fill are two different events and the messages must not be
# confusable: one says the agent asked, the other says the market answered.


def test_submission_does_not_claim_anything_was_bought(captured):
    """
    "Bought 57 HXL" on submission was a lie — a resting limit order may never
    fill. Now that a real fill message exists, the two have to read differently.
    """
    asyncio.run(notifier.send_trade_alert(
        whatsapp_phone="+1", whatsapp_apikey="k", **ENTRY
    ))
    text = captured["whatsapp"]["text"]
    assert "order placed" in text
    assert "Bought" not in text
    assert "Not filled yet" in text


def test_fill_reports_the_price_actually_paid(captured):
    asyncio.run(notifier.send_fill_alert(
        whatsapp_phone="+1", whatsapp_apikey="k",
        kind="entry", action="BUY", ticker="HXL", qty=57,
        fill_price=61.38, limit_price=61.40, is_paper=True,
    ))
    text = captured["whatsapp"]["text"]
    assert "Filled: bought 57 HXL @ $61.38" in text
    assert "Cost: $3,498.66" in text


def test_slippage_direction_never_needs_decoding(captured):
    """
    A minus sign next to the word "better" makes a reader stop and work out
    whether it is good news. The word carries the direction; the numbers do not
    contradict it.
    """
    asyncio.run(notifier.send_fill_alert(
        whatsapp_phone="+1", whatsapp_apikey="k",
        kind="entry", action="BUY", ticker="HXL", qty=57,
        fill_price=61.38, limit_price=61.40, is_paper=True,
    ))
    assert "vs limit: $0.02 better (0.03%)" in captured["whatsapp"]["text"]

    asyncio.run(notifier.send_fill_alert(
        whatsapp_phone="+1", whatsapp_apikey="k",
        kind="entry", action="BUY", ticker="HXL", qty=57,
        fill_price=61.55, limit_price=61.40, is_paper=True,
    ))
    assert "vs limit: $0.15 worse (0.24%)" in captured["whatsapp"]["text"]


def test_a_fill_at_the_limit_does_not_mention_slippage(captured):
    asyncio.run(notifier.send_fill_alert(
        whatsapp_phone="+1", whatsapp_apikey="k",
        kind="entry", action="BUY", ticker="HXL", qty=57,
        fill_price=61.40, limit_price=61.40, is_paper=True,
    ))
    assert "vs limit" not in captured["whatsapp"]["text"]


def test_exit_leads_with_realised_pnl(captured):
    """An exit answers one question — did I make money — so it goes first."""
    asyncio.run(notifier.send_fill_alert(
        whatsapp_phone="+1", whatsapp_apikey="k",
        kind="exit", action="SELL", ticker="HXL", qty=57,
        fill_price=70.10, entry_price=61.38, pnl=497.04,
        exit_reason="stop or target", is_paper=True,
    ))
    head = captured["whatsapp"]["text"].splitlines()[0]
    assert "Closed HXL" in head and "+$497.04" in head and "(+14.2%)" in head


def test_a_loss_is_not_dressed_up(captured):
    asyncio.run(notifier.send_fill_alert(
        whatsapp_phone="+1", whatsapp_apikey="k",
        kind="exit", action="SELL", ticker="HXL", qty=57,
        fill_price=56.90, entry_price=61.38, pnl=-255.36, is_paper=False,
    ))
    text = captured["whatsapp"]["text"]
    assert "🟥" in text
    assert "−$255.36" in text
    assert "Real money" in text


def test_an_unpriced_close_states_no_pnl_rather_than_zero(captured):
    """
    IB only serves same-session executions, so a position that closed on an
    earlier day cannot be priced. Reporting that as $0.00 would be a fabricated
    result, and it would pollute the record it is reporting on.
    """
    asyncio.run(notifier.send_fill_alert(
        whatsapp_phone="+1", whatsapp_apikey="k",
        kind="exit", action="SELL", ticker="HXL", qty=57,
        fill_price=None, entry_price=61.38, pnl=None,
        exit_reason="closed — exit price unavailable", is_paper=True,
    ))
    text = captured["whatsapp"]["text"]
    assert "Realised P&L" not in text
    assert "$0.00" not in text


def test_partial_fill_says_how_much_is_still_working(captured):
    asyncio.run(notifier.send_fill_alert(
        whatsapp_phone="+1", whatsapp_apikey="k",
        kind="partial", action="BUY", ticker="HXL", qty=30, ordered_qty=57,
        fill_price=61.39, limit_price=61.40, is_paper=True,
    ))
    assert "Partially filled: bought 30 of 57 HXL" in captured["whatsapp"]["text"]


def test_fill_email_and_fill_alert_render_the_same_facts(monkeypatch, captured):
    """
    Both senders read one builder. This is the guard against the original bug
    reappearing in the fill path — content decided in two places drifts.
    """
    emailed = {}

    async def fake_send(to, subject, text, html):
        emailed.update(subject=subject, text=text)

    monkeypatch.setattr(notifier, "_send_email", fake_send)

    fill = dict(kind="entry", action="BUY", ticker="HXL", qty=57,
                fill_price=61.38, limit_price=61.40, is_paper=True)
    asyncio.run(notifier.send_fill_email("a@b.c", **fill))
    asyncio.run(notifier.send_fill_alert(
        whatsapp_phone="+1", whatsapp_apikey="k", **fill))

    for line in ("Filled: 57 HXL @ $61.38", "Cost: $3,498.66"):
        assert line in emailed["text"]
        assert line in captured["whatsapp"]["text"]


# ── Once, and only once ──────────────────────────────────────────────────────


class _FakeTrades:
    """
    Stands in for the trades collection, honouring the one property the claim
    depends on: an update whose filter no longer matches modifies nothing.
    """

    def __init__(self):
        self.events: list[str] = []

    async def update_one(self, flt, update):
        key = update["$addToSet"]["notified_events"]
        if flt.get("notified_events", {}).get("$ne") == key and key in self.events:
            return type("R", (), {"modified_count": 0})()
        self.events.append(key)
        return type("R", (), {"modified_count": 1})()


def _patch_claim(monkeypatch, coll):
    async def fake_db(*_a, **_kw):
        return {trade_manager.COLL_TRADES: coll}
    monkeypatch.setattr(trade_manager, "get_db", fake_db)


FILL = dict(kind="entry", action="BUY", ticker="HXL", qty=57,
            fill_price=61.38, limit_price=61.40, is_paper=True)
TRADE = {"_id": "507f1f77bcf86cd799439011", "user_id": "u1"}


def test_the_same_fill_is_never_announced_twice(monkeypatch):
    """
    The reconciler is not serialised with itself — a pass that outruns its
    two-minute interval overlaps the next, and both would see the same PENDING
    record become FILLED. A duplicate "you bought HXL" at 3am is the failure
    this guard exists to prevent.
    """
    calls = []
    coll = _FakeTrades()
    _patch_claim(monkeypatch, coll)

    async def targets(_uid, event="submit"):
        return {"email": "", "webhook_url": None,
                "whatsapp_phone": "+1", "whatsapp_apikey": "k"}

    async def fake_alert(**kw):
        calls.append(kw)

    monkeypatch.setattr(trade_manager, "_trade_notify_targets", targets)
    monkeypatch.setattr(notifier, "send_fill_alert", fake_alert)

    for _ in range(3):
        asyncio.run(trade_manager._notify_fill(
            TRADE, event_key="fill:1043", **FILL))
    assert len(calls) == 1


def test_a_scale_in_add_is_announced_separately_from_the_first_fill(monkeypatch):
    """
    One position record can legitimately fill more than once. Keying the claim
    on the order id is what keeps the second add audible while still
    deduplicating each one.
    """
    calls = []
    coll = _FakeTrades()
    _patch_claim(monkeypatch, coll)

    async def targets(_uid, event="submit"):
        return {"email": "", "webhook_url": None,
                "whatsapp_phone": "+1", "whatsapp_apikey": "k"}

    async def fake_alert(**kw):
        calls.append(kw)

    monkeypatch.setattr(trade_manager, "_trade_notify_targets", targets)
    monkeypatch.setattr(notifier, "send_fill_alert", fake_alert)

    for key in ("fill:1043", "fill:1043", "fill:1099", "close"):
        asyncio.run(trade_manager._notify_fill(TRADE, event_key=key, **FILL))
    assert len(calls) == 3


def test_fill_and_submission_are_gated_independently(monkeypatch):
    """
    "Tell me when it happened, not when you tried" is a reasonable preference,
    so `notify_on_fill` is its own flag rather than sharing the submission one.
    """
    seen = {}

    class _Users:
        async def find_one(self, _flt, _proj):
            return {"email": "a@b.c",
                    "alert_settings": {"notify_on_trade": False,
                                       "notify_on_fill": True,
                                       "whatsapp_phone": "+1",
                                       "whatsapp_apikey": "k"}}

    async def fake_db(*_a, **_kw):
        return {trade_manager.COLL_USERS: _Users()}

    monkeypatch.setattr(trade_manager, "get_db", fake_db)

    seen["submit"] = asyncio.run(trade_manager._trade_notify_targets("u1", "submit"))
    seen["fill"] = asyncio.run(trade_manager._trade_notify_targets("u1", "fill"))

    assert seen["submit"] == {}                      # opted out of submissions
    assert seen["fill"]["whatsapp_phone"] == "+1"    # still wants fills


# ── The seam: a fill in the reconciler actually reaches the notifier ──────────


def test_settling_a_scale_in_announces_only_the_shares_added(monkeypatch):
    """
    A message saying "filled 550 HXL" when 100 were just bought would misreport
    the event as five times its size. The add reports the add; the position
    total is what the dashboard is for.
    """
    import app.services.trade_manager as tm

    sent = []

    async def capture(_trade, **kw):
        sent.append(kw)

    async def _update(_tid, _u):
        pass

    async def _reprotect(*_a, **_kw):
        return True

    monkeypatch.setattr(tm, "_update_trade", _update)
    monkeypatch.setattr(tm, "_reprotect", _reprotect)
    monkeypatch.setattr(tm, "_notify_fill", capture)

    trade = {
        "_id": "pos-1", "user_id": "u1", "ticker": "HXL", "action": "BUY",
        "status": "FILLED", "qty": 450, "filled_qty": 450,
        "entry_price": 88.0, "limit_price": 88.0,
        "stop_loss": 83.0, "take_profit": 110.0, "closed_at": None,
        "pending_add": {"qty": 100, "limit_price": 95.20, "order_id": "ORD-1",
                        "total_qty": 550, "blended_entry": 90.5,
                        "combined_stop": 86.0, "combined_target": 110.0},
    }
    asyncio.run(tm._settle_pending_add(trade, {}, {}, {"HXL": 550}, "DU123"))

    assert len(sent) == 1
    assert sent[0]["qty"] == 100          # added, not the 550 now held
    assert sent[0]["kind"] == "entry"
    assert sent[0]["event_key"] == "fill:ORD-1"


def test_an_add_that_did_not_fill_announces_nothing(monkeypatch):
    """Settling a pending add that filled zero shares is not a fill."""
    import app.services.trade_manager as tm

    sent = []

    async def capture(_trade, **kw):
        sent.append(kw)

    async def _update(_tid, _u):
        pass

    async def _reprotect(*_a, **_kw):
        return True

    monkeypatch.setattr(tm, "_update_trade", _update)
    monkeypatch.setattr(tm, "_reprotect", _reprotect)
    monkeypatch.setattr(tm, "_notify_fill", capture)

    trade = {
        "_id": "pos-1", "user_id": "u1", "ticker": "HXL", "action": "BUY",
        "status": "FILLED", "qty": 450, "filled_qty": 450,
        "entry_price": 88.0, "limit_price": 88.0,
        "stop_loss": 83.0, "take_profit": 110.0, "closed_at": None,
        "pending_add": {"qty": 100, "limit_price": 95.20, "order_id": "ORD-1",
                        "total_qty": 550, "blended_entry": 90.5,
                        "combined_stop": 86.0, "combined_target": 110.0},
    }
    # Venue still reports the original 450 — nothing was added.
    asyncio.run(tm._settle_pending_add(trade, {}, {}, {"HXL": 450}, "DU123"))
    assert sent == []


# ── WhatsApp delivery is verified, not assumed ───────────────────────────────
#
# CallMeBot answers an invalid API key with `203 Non-Authoritative Information`
# and puts the real outcome in the HTML body. The old check was
# `if status != 200: warn`, which missed every real failure — a dead key was
# indistinguishable from a delivered message. Silent and indefinite is the worst
# failure mode a notification channel can have.


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


def _stub_httpx(monkeypatch, resp):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, _url):
            return resp

    monkeypatch.setattr(notifier.httpx, "AsyncClient", _Client)


def test_an_invalid_api_key_is_a_failure_even_though_the_status_is_2xx(monkeypatch):
    _stub_httpx(monkeypatch, _Resp(203, (
        "<p>Message to: +15551234567<p>Text to send: hi"
        '<p style="color:red"><b>APIKey is invalid.</b> Please create a new one.'
    )))
    reason = asyncio.run(notifier._whatsapp_send("+15551234567", "bad", "hi"))
    assert reason is not None
    assert reason.startswith("APIKey is invalid")


def test_the_failure_reason_does_not_echo_the_message_back(monkeypatch):
    """
    The reason is shown in the UI and written to logs. CallMeBot repeats the
    whole outgoing alert before saying what went wrong; neither destination is
    a place to reproduce it.
    """
    _stub_httpx(monkeypatch, _Resp(203, (
        "<p>Message to: +15551234567<p>Text to send: BUY HXL secret levels"
        "<p><b>APIKey is invalid.</b>"
    )))
    reason = asyncio.run(notifier._whatsapp_send("+15551234567", "bad", "x"))
    assert "HXL" not in reason
    assert "secret" not in reason


def test_a_successful_send_is_not_reported_as_an_error(monkeypatch):
    """
    The mirror of the bug: 203 is CallMeBot's normal answer, so treating any
    non-200 as failure would mark every delivered message as broken.
    """
    _stub_httpx(monkeypatch, _Resp(203, "<p>Message queued. You will receive it shortly.</p>"))
    assert asyncio.run(notifier._whatsapp_send("+15551234567", "good", "hi")) is None


def test_a_transport_failure_is_reported(monkeypatch):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, _url):
            raise TimeoutError("connect timeout")

    monkeypatch.setattr(notifier.httpx, "AsyncClient", _Client)
    reason = asyncio.run(notifier._whatsapp_send("+1", "k", "hi"))
    assert reason is not None and "timeout" in reason.lower()


def test_an_http_error_is_reported(monkeypatch):
    _stub_httpx(monkeypatch, _Resp(500, "upstream exploded"))
    assert asyncio.run(notifier._whatsapp_send("+1", "k", "hi")) == "HTTP 500"


def test_phone_numbers_are_masked_in_logs():
    assert notifier._mask_phone("+1 555 867 5309") == "…5309"
    assert notifier._mask_phone("abc") == "…"
