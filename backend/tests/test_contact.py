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


# ── The intake queue ──────────────────────────────────────────────────────────

class _FakeRequests:
    def __init__(self):
        self.rows: list[dict] = []

    async def insert_one(self, doc: dict):
        self.rows.append(doc)


@pytest.fixture
def queue(monkeypatch):
    """Capture what reaches `access_requests` without a database."""
    import app.routes.contact as contact
    from app.db import COLL_ACCESS_REQUESTS

    store = _FakeRequests()

    class _DB:
        def __getitem__(self, name):
            assert name == COLL_ACCESS_REQUESTS
            return store

    async def fake_get_db():
        return _DB()

    monkeypatch.setattr(contact, "get_db", fake_get_db)
    return store


def test_a_real_submission_joins_the_queue(client, sent, queue):
    """
    Accounts are provisioned by hand, so this form is the intake. Without the
    row, an SMTP outage loses the enquiry entirely — there is no other record.
    """
    res = client.post("/contact", json={**MESSAGE, "interest": "research"})

    assert res.status_code == 200
    assert len(queue.rows) == 1
    row = queue.rows[0]
    assert row["email"] == "ada@example.com"
    assert row["interest"] == "In-depth research on their own names"
    assert row["created_at"] is not None


def test_the_honeypot_persists_nothing(client, sent, queue):
    """
    Filling the queue with what the honeypot exists to absorb defeats the point
    of having one. The response stays a normal success so the sender still
    learns nothing.
    """
    res = client.post("/contact", json={**MESSAGE, "company": "Acme Bots"})

    assert res.status_code == 200
    assert res.json()["sent"] is True
    assert queue.rows == []
    assert sent == []


def test_a_failed_write_still_sends_the_mail(client, sent, monkeypatch):
    """
    A dropped queue row is a lost convenience. A dropped email is a lost
    person, and the mail is what the visitor was promised.
    """
    import app.routes.contact as contact

    async def broken_get_db():
        raise RuntimeError("mongo is down")

    monkeypatch.setattr(contact, "get_db", broken_get_db)

    res = client.post("/contact", json=MESSAGE)

    assert res.status_code == 200
    assert len(sent) == 1


def test_a_successful_write_does_not_mask_a_failed_send(client, queue, monkeypatch):
    """
    The 502 stands. Recording a row and then reporting success for mail that
    never went is exactly the lie this module exists not to tell.
    """
    async def failing_send(*args, **kwargs):
        return "smtp refused the message"

    monkeypatch.setattr("app.services.notifier._send_email", failing_send)

    res = client.post("/contact", json=MESSAGE)

    assert res.status_code == 502
    assert len(queue.rows) == 1, "the enquiry is still recoverable from the queue"


def test_the_public_form_does_not_name_internal_plan_values(client, sent, queue):
    """
    A stranger has no idea what BASIC or TRADER mean, and naming plans on a page
    that quotes no prices invites a question the page cannot answer.
    """
    for bad in ("BASIC", "PRO", "TRADER"):
        res = client.post("/contact", json={**MESSAGE, "interest": bad})
        assert res.status_code == 422
