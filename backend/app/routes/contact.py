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
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

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

    failure = await send_contact_message(body.name, str(body.email), body.message)
    if failure:
        logger.error("contact_send_failed", client=ip, error=failure)
        raise HTTPException(
            status_code=502,
            detail="Could not deliver that message. Please try again shortly.",
        )

    logger.info("contact_received", client=ip, sender=str(body.email))
    return ContactResponse(sent=True)
