"""
Auth helpers — password hashing, JWT creation/validation, account shape.

**The token carries no tier and no capabilities**, and that is deliberate.
`get_current_user` loads the whole user document on every request anyway, so a
claim would save no query — and it would be stale for the token's entire
lifetime, which means an admin downgrade would take effect whenever the user
next happened to sign in rather than on their next request. For a control whose
whole purpose is to stop a spend now, that is the wrong direction. Changing this
payload also changes the login path, which is the one thing on this API that
must not break.
"""
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.models.user import AccessTier

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, email: str) -> str:
    settings = get_settings()
    expire = datetime.now(tz=timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {"sub": user_id, "email": email, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


#: Unambiguous in a monospaced font and in a phone's mail app. No l/1/I/O/0 —
#: a generated password is read off a screen and typed by hand at least once.
_PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_password(length: int = 16) -> str:
    """A password for an account the operator is about to email credentials for."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def new_user_document(
    *,
    email: str,
    password: str,
    display_name: str = "",
    access_tier: AccessTier = AccessTier.BASIC,
    watchlist_cap: Optional[int] = None,
    research_daily_allowed: bool = False,
) -> dict:
    """
    The shape of a freshly provisioned account, in one place.

    Two things create accounts — `scripts/create_user.py` and
    `POST /admin/users` — and they must not drift. A field added by one and
    missed by the other is a document that reads as something nobody intended:
    a missing `access_tier` resolves to BASIC, so the drift would show up as an
    account that silently has less access than the operator granted.

    `watchlist_cap` is omitted entirely when None rather than written as null,
    so the tier default applies *and keeps applying* if that default is ever
    retuned. A stored copy of today's default would freeze it per account.

    Defaults to BASIC. The operator's own account is created with an explicit
    tier; everything else starts at the smallest thing that is useful.
    """
    doc: dict = {
        "email": email,
        "password_hash": hash_password(password),
        "display_name": display_name or email.split("@")[0],
        "created_at": datetime.now(tz=timezone.utc),
        # None until the user sets their own; the global defaults apply.
        "scoring_weights": None,
        "access_tier": AccessTier(access_tier).value,
        "research_daily_allowed": bool(research_daily_allowed),
    }
    if watchlist_cap is not None:
        doc["watchlist_cap"] = max(0, int(watchlist_cap))
    return doc
