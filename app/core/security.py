"""Passwords and tokens: the small, security-critical primitives."""

import hashlib
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# Argon2id with the library's defaults (the RFC 9106 low-memory recommendation: 64 MiB, 3 passes).
_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128  # a ceiling, so nobody can make the server hash a megabyte
API_TOKEN_PREFIX = "fin_"  # recognisable by secret scanners if one ever leaks into a repo


def validate_password(password: str, email: str | None = None) -> None:
    """Length matters, composition rules do not (NIST SP 800-63B): long beats clever."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    if email and password.strip().lower() == email.strip().lower():
        raise ValueError("The password must not be your email address.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash("not-a-real-password")


def verify_password(stored_hash: str | None, password: str) -> bool:
    """True only for a correct password on a real account.

    It does one full hash comparison even when there is no such account (stored_hash is
    None), so the time a login takes does not reveal which email addresses exist.
    """
    try:
        _hasher.verify(stored_hash or _dummy_hash(), password)
    except (VerificationError, InvalidHashError):
        return False
    return stored_hash is not None


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash was made with weaker settings than the current ones."""
    return _hasher.check_needs_rehash(stored_hash)


def new_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)  # 256 bits from the operating system's CSPRNG


def hash_token(token: str) -> str:
    """Only this hash is stored. Tokens are random, so a fast hash is correct here: there is
    nothing to brute-force, unlike a human-chosen password."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()