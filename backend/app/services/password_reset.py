"""
One-time password reset links.

Everything here exists to make a public endpoint safe to leave open. Five
properties, and each one is a way this feature is normally got wrong:

**Only a hash of the token is stored.** The link is a bearer credential — it
sets a password without knowing the old one — so a stored copy is as good as
the password itself. A database dump, a log line, a backup on someone's laptop:
none of them should yield a working link. The raw token exists only in the
email and in the request that redeems it.

**Single use.** The document is deleted the moment it is redeemed, so a link
forwarded, quoted in a reply, or sitting in a mail archive cannot be replayed.

**Short-lived, and expiry is enforced in the query rather than after it.** A
`find_one` that matched an expired document and then checked the date would
work, but it puts the check somewhere a later refactor can drop; here an
expired token simply does not match.

**Issuing one never says whether the account exists.** That belongs to the
route, but it is why this module returns `None` for an unknown address instead
of raising — a caller cannot accidentally turn "no such user" into a distinct
response if it never sees an error.

**Issuing a new one invalidates the outstanding ones** for that account, so a
link mailed to an address the owner no longer controls stops working the moment
they ask for a fresh one.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db import COLL_PASSWORD_RESETS, get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: How long a link works for. Long enough to walk to a laptop, short enough
#: that a mailbox someone else reaches later is not a standing key.
TOKEN_TTL_MINUTES = 60

#: 32 bytes, URL-safe. Guessing is not a threat model at this width; the
#: reasons this is short-lived and single-use are mailboxes and forwarding.
_TOKEN_BYTES = 32


def _fingerprint(token: str) -> str:
    """
    SHA-256 of the raw token.

    Plain SHA-256 rather than bcrypt on purpose, and the difference matters.
    A password is low-entropy and human-chosen, so it needs a slow hash to
    survive an offline attack. This is 256 bits from `secrets` — there is
    nothing to brute-force — and it has to be looked up by value on every
    redemption, which a deliberately slow hash would make impossible to index.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue(user_id: str) -> Optional[str]:
    """
    Create a reset token for this account and return the raw value.

    Returns None on a database failure, which the route reports as an outage —
    the one case where silence would be wrong, because the person is waiting
    for mail that is never coming.
    """
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    now = datetime.now(tz=timezone.utc)

    try:
        db = await get_db()
        # Supersede anything outstanding. A link sent to a mailbox the owner
        # has lost stops working as soon as they ask for a new one.
        await db[COLL_PASSWORD_RESETS].delete_many({"user_id": str(user_id)})
        await db[COLL_PASSWORD_RESETS].insert_one({
            "user_id": str(user_id),
            "token_hash": _fingerprint(token),
            "created_at": now,
            "expires_at": now + timedelta(minutes=TOKEN_TTL_MINUTES),
        })
    except Exception as exc:
        logger.error("password_reset_issue_failed", user_id=str(user_id), error=str(exc))
        return None

    return token


async def redeem(token: str) -> Optional[str]:
    """
    Consume a token and return the user id it belonged to.

    None means no live token matched — expired, already used, superseded, or
    never real. The four are deliberately indistinguishable to the caller:
    telling them apart tells whoever holds a stale link something about the
    account it came from.

    `find_one_and_delete` rather than read-then-delete, so two requests racing
    the same link cannot both succeed.
    """
    try:
        db = await get_db()
        doc = await db[COLL_PASSWORD_RESETS].find_one_and_delete({
            "token_hash": _fingerprint(token),
            # In the filter, not a check afterwards: an expired token must not
            # match at all, rather than match and then be rejected somewhere a
            # later edit could drop.
            "expires_at": {"$gt": datetime.now(tz=timezone.utc)},
        })
    except Exception as exc:
        logger.error("password_reset_redeem_failed", error=str(exc))
        return None

    return str(doc["user_id"]) if doc else None


async def revoke_for(user_id: str) -> None:
    """
    Drop every outstanding link for an account.

    Called after any password change, from any path. Somebody who has just set
    a new password has answered the question an outstanding link was asking,
    and leaving one live would let an old email undo what they just did.
    """
    try:
        db = await get_db()
        await db[COLL_PASSWORD_RESETS].delete_many({"user_id": str(user_id)})
    except Exception as exc:
        # Not fatal: the tokens still expire on their own, and the password is
        # already changed. Worth a line because the window is real.
        logger.warning("password_reset_revoke_failed", user_id=str(user_id), error=str(exc))
