"""Accounts, sessions and API tokens.

Only `login` commits by itself: a failed attempt must be recorded even though the request
then fails, otherwise the lockout could never count. Everything else leaves committing to
the caller.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core import security
from app.core.errors import TooManyRequests, Unauthorized

SESSION_IDLE = timedelta(days=14)  # signed out after this long without use
SESSION_MAX = timedelta(days=90)  # and never stays signed in longer than this
TOUCH_EVERY = timedelta(hours=1)  # how often "last seen" is written, to keep writes rare
MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)

BAD_CREDENTIALS = "Email or password is incorrect."  # the same words for every failure


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    email: str
    display_name: str


def normalise_email(email: str) -> str:
    return email.strip().lower()


# ---- accounts -----------------------------------------------------------------------------
def create_user(db: Any, email: str, display_name: str, password: str) -> UUID:
    email = normalise_email(email)
    if "@" not in email or len(email) > 254:
        raise ValueError("Enter a valid email address.")
    if not display_name.strip():
        raise ValueError("Enter a name.")
    security.validate_password(password, email)
    return db.execute(
        text("INSERT INTO users (email, display_name, password_hash) VALUES (:e, :n, :h) RETURNING id"),
        {"e": email, "n": display_name.strip(), "h": security.hash_password(password)},
    ).scalar_one()


def revoke_all_sessions(db: Any, user_id: UUID) -> int:
    result = db.execute(
        text("UPDATE sessions SET revoked_at = now() WHERE user_id = :u AND revoked_at IS NULL"), {"u": user_id}
    )
    return result.rowcount


def set_password(db: Any, email: str, password: str) -> None:
    """Changes the password and signs the user out everywhere."""
    email = normalise_email(email)
    security.validate_password(password, email)
    user_id = db.execute(text("SELECT id FROM users WHERE lower(email) = :e"), {"e": email}).scalar_one_or_none()
    if user_id is None:
        raise LookupError("No such user.")
    db.execute(
        text("UPDATE users SET password_hash = :h WHERE id = :u"),
        {"h": security.hash_password(password), "u": user_id},
    )
    revoke_all_sessions(db, user_id)


# ---- login --------------------------------------------------------------------------------
def _locked_out(db: Any, email: str) -> bool:
    failures = db.execute(
        text(
            "SELECT count(*) FROM login_attempts WHERE email = :e AND NOT succeeded"
            " AND attempted_at > now() - :window"
            " AND attempted_at > COALESCE((SELECT max(attempted_at) FROM login_attempts"
            "                              WHERE email = :e AND succeeded), CAST('-infinity' AS timestamptz))"
        ),
        {"e": email, "window": FAILURE_WINDOW},
    ).scalar_one()
    return failures >= MAX_FAILURES


def _record_attempt(db: Any, email: str, succeeded: bool) -> None:
    db.execute(
        text("INSERT INTO login_attempts (email, succeeded) VALUES (:e, :s)"), {"e": email, "s": succeeded}
    )


def login(db: Any, email: str, password: str, user_agent: str = "") -> tuple[AuthUser, str]:
    """Returns the user and a new session token, or raises Unauthorized / TooManyRequests."""
    email = normalise_email(email)

    if _locked_out(db, email):
        # Checked BEFORE the password, so guessing during a lockout learns nothing.
        raise TooManyRequests("Too many failed attempts. Try again in 15 minutes.")

    row = db.execute(
        text("SELECT id, email, display_name, password_hash, is_active FROM users WHERE lower(email) = :e"),
        {"e": email},
    ).one_or_none()

    correct = security.verify_password(row.password_hash if row else None, password)
    if not (row and row.is_active and correct):
        _record_attempt(db, email, False)
        db.commit()
        raise Unauthorized(BAD_CREDENTIALS)

    if security.needs_rehash(row.password_hash):  # quietly upgrade old hashes
        db.execute(
            text("UPDATE users SET password_hash = :h WHERE id = :u"),
            {"h": security.hash_password(password), "u": row.id},
        )

    token = security.new_token()
    db.execute(
        text(
            "INSERT INTO sessions (user_id, token_hash, expires_at, user_agent)"
            " VALUES (:u, :h, now() + :max, :ua)"
        ),
        {"u": row.id, "h": security.hash_token(token), "max": SESSION_MAX, "ua": user_agent[:255] or None},
    )
    _record_attempt(db, email, True)
    db.commit()
    return AuthUser(row.id, row.email, row.display_name), token


# ---- sessions -----------------------------------------------------------------------------
def authenticate_session(db: Any, token: str) -> AuthUser | None:
    row = db.execute(
        text(
            "SELECT s.id AS session_id, u.id, u.email, u.display_name"
            " FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = :h AND s.revoked_at IS NULL AND s.expires_at > now()"
            "   AND s.last_seen_at > now() - :idle AND u.is_active"
        ),
        {"h": security.hash_token(token), "idle": SESSION_IDLE},
    ).one_or_none()
    if row is None:
        return None
    db.execute(
        text("UPDATE sessions SET last_seen_at = now() WHERE id = :s AND last_seen_at < now() - :touch"),
        {"s": row.session_id, "touch": TOUCH_EVERY},
    )
    return AuthUser(row.id, row.email, row.display_name)


def revoke_session(db: Any, token: str) -> None:
    db.execute(
        text("UPDATE sessions SET revoked_at = now() WHERE token_hash = :h AND revoked_at IS NULL"),
        {"h": security.hash_token(token)},
    )


# ---- API tokens (for the phone's SMS forwarder) -------------------------------------------
def create_api_token(db: Any, user_id: UUID, name: str, scope: str = "ingest") -> str:
    """Returns the token. This is the only time it exists in readable form."""
    token = security.new_token(security.API_TOKEN_PREFIX)
    db.execute(
        text("INSERT INTO api_tokens (user_id, name, token_hash, scope) VALUES (:u, :n, :h, :s)"),
        {"u": user_id, "n": name, "h": security.hash_token(token), "s": scope},
    )
    return token


def revoke_api_token(db: Any, user_id: UUID, name: str) -> bool:
    result = db.execute(
        text("UPDATE api_tokens SET revoked_at = now() WHERE user_id = :u AND name = :n AND revoked_at IS NULL"),
        {"u": user_id, "n": name},
    )
    return result.rowcount > 0


def authenticate_api_token(db: Any, token: str, scope: str) -> AuthUser | None:
    row = db.execute(
        text(
            "SELECT t.id AS token_id, u.id, u.email, u.display_name"
            " FROM api_tokens t JOIN users u ON u.id = t.user_id"
            " WHERE t.token_hash = :h AND t.scope = :s AND t.revoked_at IS NULL AND u.is_active"
        ),
        {"h": security.hash_token(token), "s": scope},
    ).one_or_none()
    if row is None:
        return None
    db.execute(
        text(
            "UPDATE api_tokens SET last_used_at = now() WHERE id = :t"
            " AND (last_used_at IS NULL OR last_used_at < now() - interval '1 minute')"
        ),
        {"t": row.token_id},
    )
    return AuthUser(row.id, row.email, row.display_name)