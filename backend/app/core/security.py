"""
Security primitives — password hashing (Argon2id), JWT access tokens,
and opaque refresh tokens (stored hashed in the database).

Never log or return: plaintext passwords, password hashes, JWT secret.
"""

import hashlib
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from app.core.config import settings

_password_hasher = PasswordHasher()  # Argon2id defaults


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return _password_hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, plain)
    except (VerifyMismatchError, VerificationError):
        return False


# ---------------------------------------------------------------------------
# Access tokens (JWT)
# ---------------------------------------------------------------------------

def create_access_token(*, user_id: str, company_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "user_id": user_id,
        "company_id": company_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Returns claims or None when invalid/expired — never raises."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# Refresh tokens — opaque random strings, stored as SHA-256 hashes
# ---------------------------------------------------------------------------

def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


# ---------------------------------------------------------------------------
# Username generation — signup has no username field, derive from email
# ---------------------------------------------------------------------------

def slugify_username(seed: str) -> str:
    """'John.Doe+ops@x.com' → 'john.doe' — lowercase, dot-separated, unique-safe."""
    seed = unicodedata.normalize("NFKD", seed)
    slug = re.sub(r"[^a-zA-Z0-9]+", ".", seed).strip(".").lower()
    return slug or "user"
