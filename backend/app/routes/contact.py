"""
POST /contact — public contact form on the landing page.

The only unauthenticated write on this API, and the only endpoint a stranger
can use to make the server send mail. That shapes every decision here:

  * **Rate limited per client address, counting every submission** — not only
    failures, as login does. There is no such thing as a submission that should
    not be charged for.
  * **A honeypot field** that a real visitor never sees. Anything in it means a
    bot filled every input on the page; the response is a normal success, so
    the sender learns nothing and does not adapt.
  * **Length caps in the schema**, so a multi-megabyte body is rejected before
    it reaches the mail server.
  * **The visitor's address goes in Reply-To, never From.** Forging a From the
    SMTP provider has not authenticated is how a domain's deliverability dies.

The failure is reported honestly rather than swallowed. Elsewhere in this
codebase a mail failure is logged and ignored, because trading must not stop
for it — but a person who fills in a form and is told "sent" when nothing was
sent has simply been lied to, and has no other way to reach anyone.

Since accounts are provisioned by hand, this is also the intake. Each real
submission is written to `access_requests` so the operator has a queue rather
than an inbox search, which makes it the only unauthenticated **insert** on
this API as well as the only unauthenticated write. Three rules come with that:

  * **A honeypot trip persists nothing.** Filling the queue with what the
    honeypot exists to absorb defeats the point of having one.
  * **A failed write does not fail the request.** A dropped queue row is a lost
    convenience; a dropped email is a lost person, and the mail is what the
    visitor was promised.
  * **A successful write never masks a failed send.** The 502 stands. Writing
    a row and then reporting success for mail that did not go is the exact lie
    the paragraph above forbids.
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.db import COLL_ACCESS_REQUESTS, get_db
from app.services import rate_limit
from app.services.notifier import send_contact_message
from app.utils.logger import get_logger
from app.utils.net import client_ip

router = APIRouter(tags=["contact"])
logger = get_logger(__name__)


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    message: str = Field(min_length=10, max_length=4000)
    #: Honeypot. Named for what a bot expects to see, not for what it does.
    company: str = Field(default="", max_length=200)
    #: What they are after, in the visitor's own terms rather than in ours.
    #:
    #: Deliberately not "BASIC / PRO / TRADER": a stranger has no idea what
    #: those mean, and naming plans on a page that quotes no prices invites a
    #: question the page cannot answer. A fixed set rather than free text so it
    #: can be grouped, and so nothing arbitrary reaches a mail header.
    interest: Optional[Literal["read", "research", "trade"]] = None

    @field_validator("name", "message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class ContactResponse(BaseModel):
    sent: bool


@router.post("/contact", response_model=ContactResponse)
async def submit_contact(body: ContactRequest, request: Request) -> ContactResponse:
    ip = client_ip(request)

    decision = rate_limit.check_contact_allowed(ip)
    if not decision.allowed:
        logger.warning("contact_rate_limited", client=ip)
        raise HTTPException(
            status_code=429,
            detail="Too many messages from this address. Please try again later.",
            headers={"Retry-After": str(decision.retry_after)},
        )

    if body.company:
        # Counted like any other submission, so a bot that keeps filling it in
        # still exhausts its allowance.
        rate_limit.record_contact_submission(ip)
        logger.info("contact_honeypot_tripped", client=ip)
        return ContactResponse(sent=True)

    rate_limit.record_contact_submission(ip)

    await _record_request(body, ip)

    failure = await send_contact_message(
        body.name, str(body.email), body.message,
        interest=_INTEREST_LABELS.get(body.interest or ""),
    )
    if failure:
        logger.error("contact_send_failed", client=ip, error=failure)
        raise HTTPException(
            status_code=502,
            detail="Could not deliver that message. Please try again shortly.",
        )

    logger.info("contact_received", client=ip, sender=str(body.email))
    return ContactResponse(sent=True)


#: How each choice reads in the operator's inbox and queue. The wire values stay
#: short and stable; these are the sentence.
_INTEREST_LABELS = {
    "read": "Just wants to see the analysis",
    "research": "In-depth research on their own names",
    "trade": "Trading through their own IB account",
}


async def _record_request(body: ContactRequest, ip: str) -> None:
    """
    Add this submission to the operator's queue.

    Never raises. Persisting is a convenience for whoever provisions accounts;
    the mail is what the visitor was actually promised, and losing a queue row
    must not cost them their message. Called only for real submissions — a
    honeypot trip returns before this.
    """
    try:
        db = await get_db()
        await db[COLL_ACCESS_REQUESTS].insert_one({
            "name": body.name,
            "email": str(body.email),
            "message": body.message,
            "interest": _INTEREST_LABELS.get(body.interest or ""),
            "created_at": datetime.now(tz=timezone.utc),
            # Kept for the same reason the rate limiter keys on it, and aged out
            # by the TTL index with the rest of the row.
            "client_ip": ip,
        })
    except Exception as exc:
        logger.error(
            "access_request_not_recorded",
            client=ip, error=str(exc),
            impact="the message is still being sent; it just will not appear "
                   "in the admin queue",
        )
