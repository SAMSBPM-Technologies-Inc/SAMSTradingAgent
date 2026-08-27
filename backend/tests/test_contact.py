"""
The public contact form.

`POST /contact` is the only unauthenticated write on this API and the only way
a stranger can make the server send mail, so the tests here are less about the
happy path than about the four things that stop it being a spam relay: the
rate limit, the honeypot, the length caps, and the refusal to put visitor text
where it could split a mail header.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import rate_limit


@pytest.fixture
def sent(monkeypatch):
    """Capture outbound mail; nothing in these tests touches SMTP."""
    box: list[dict] = []

    async def fake_send(to, subject, text, html, reply_to=None):
        box.append(dict(to=to, subject=subject, text=text, html=html, reply_to=reply_to))
        return None

    monkeypatch.setattr("app.services.notifier._send_email", fake_send)
    rate_limit.reset_for_tests()
    yield box
    rate_limit.reset_for_tests()


@pytest.fixture
def client():
    return TestClient(app)


MESSAGE = dict(name="Ada Lovelace", email="ada@example.com", message="Please tell me about access.")


def test_message_reaches_the_configured_address(client, sent):
    from app.config import get_settings

    res = client.post("/contact", json=MESSAGE)

    assert res.status_code == 200
    assert res.json() == {"sent": True}
    assert len(sent) == 1
    assert sent[0]["to"] == get_settings().contact_email


def test_reply_to_is_the_visitor(client, sent):
    client.post("/contact", json=MESSAGE)
    assert sent[0]["reply_to"] == "ada@example.com"


def test_honeypot_looks_successful_but_sends_nothing(client, sent):
    """
    A bot that fills every field learns nothing from the response, so it has no
    signal to adapt to.
    """
    res = client.post("/contact", json={**MESSAGE, "company": "spam co"})

    assert res.status_code == 200
    assert res.json() == {"sent": True}
    assert sent == []


def test_honeypot_submissions_still_consume_the_allowance(client, sent):
    for _ in range(rate_limit.CONTACT_MAX_SUBMISSIONS):
        client.post("/contact", json={**MESSAGE, "company": "spam co"})

    assert client.post("/contact", json=MESSAGE).status_code == 429


def test_rate_limited_after_the_allowance(client, sent):
    for _ in range(rate_limit.CONTACT_MAX_SUBMISSIONS):
        assert client.post("/contact", json=MESSAGE).status_code == 200

    res = client.post("/contact", json=MESSAGE)
    assert res.status_code == 429
    assert res.headers["retry-after"] == str(rate_limit.CONTACT_LOCKOUT_SECONDS)
    assert len(sent) == rate_limit.CONTACT_MAX_SUBMISSIONS


@pytest.mark.parametrize(
    "payload",
    [
        {**MESSAGE, "email": "not-an-email"},
        {**MESSAGE, "message": "short"},          # under the 10-char floor
        {**MESSAGE, "message": "x" * 4001},       # over the 4000-char cap
        {**MESSAGE, "name": "   "},               # blank after stripping
        {"email": "ada@example.com", "message": "no name supplied here"},
    ],
)
def test_rejected_before_any_mail_is_attempted(client, sent, payload):
    assert client.post("/contact", json=payload).status_code == 422
    assert sent == []


def test_newlines_cannot_split_a_header(client, sent):
    """
    A name carrying CRLF plus a Bcc would, unescaped, add a recipient. It has
    to arrive as one flat subject line.
    """
    client.post("/contact", json={**MESSAGE, "name": "Evil\r\nBcc: victim@example.com"})

    subject = sent[0]["subject"]
    assert "\n" not in subject and "\r" not in subject


def test_message_body_is_escaped_in_the_html_part(client, sent):
    client.post("/contact", json={**MESSAGE, "message": "<script>alert(1)</script> and more"})

    assert "<script>" not in sent[0]["html"]
    assert "&lt;script&gt;" in sent[0]["html"]


def test_a_mail_failure_is_reported_not_swallowed(client, monkeypatch):
    """
    Everywhere else a mail failure is logged and ignored so trading continues.
    Here it must surface: a visitor told "sent" when nothing was sent has been
    lied to and has no other route to anyone.
    """
    async def failing(*_args, **_kwargs):
        return "SMTPAuthenticationError: nope"

    monkeypatch.setattr("app.services.notifier._send_email", failing)
    rate_limit.reset_for_tests()

    assert client.post("/contact", json=MESSAGE).status_code == 502
