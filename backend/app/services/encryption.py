"""
Symmetric encryption for storing sensitive credentials at rest.
Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` package.

Key management
--------------
Generate a key once:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Store it as ENCRYPTION_KEY=<value> in .env / .env.production.
NEVER rotate the key without first decrypting and re-encrypting all existing ciphertext.
"""
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _get_fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. "
            "Generate one with: python3 -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    """Return a URL-safe base64-encoded Fernet token for the given plaintext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """
    Decrypt a Fernet token produced by encrypt().
    Raises ValueError if the token is invalid or the key doesn't match.
    """
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Credential decryption failed — token invalid or key mismatch") from exc
