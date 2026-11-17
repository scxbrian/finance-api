"""Accounts, sessions, lockout and API tokens, against a real database."""

import hashlib

import pytest
from argon2 import PasswordHasher
from sqlalchemy import text

from app.core import security
from app.core.errors import TooManyRequests, Unauthorized
from app.services import auth

PASSWORD = "a perfectly fine passphrase"
EMAIL = "brian@example.com"


@pytest.fixture
def user(session):
    return auth.create_user(session, EMAIL, "Brian", PASSWORD)


def sql(session, statement, **params):
    return session.execute(text(statement), params)


def fail_login(session, times, email=EMAIL):
    for _ in range(times):
        with pytest.raises(Unauthorized):
            auth.login(session, email, "the wrong password")


# ---- accounts ----------------------------------------------------------------------------
def test_emails_are_stored_lowercase_and_the_password_is_hashed(session, user):
    row = sql(session, "SELECT email, password_hash FROM users WHERE id = :u", u=user).one()
    assert row.email == EMAIL
    assert row.password_hash.startswith("$argon2")
    assert PASSWORD not in row.password_hash


def test_login_ignores_email_case_and_spaces(session, user):
    logged_in, _ = auth.login(session, "  BRIAN@Example.COM ", PASSWORD)
    assert logged_in.id == user


@pytest.mark.parametrize("email", ["nope", "a@" + "b" * 260])
def test_invalid_emails_are_refused(session, email):
    with pytest.raises(ValueError):
        auth.create_user(session, email, "X", PASSWORD)


# ---- login -------------------------------------------------------------------------------
def test_login_returns_a_working_session(session, user):
    logged_in, token = auth.login(session, EMAIL, PASSWORD, "Mozilla/5.0")
    assert logged_in.email == EMAIL
    assert auth.authenticate_session(session, token).id == user


def test_wrong_password_and_unknown_email_fail_with_the_same_message(session, user):
    with pytest.raises(Unauthorized) as wrong:
        auth.login(session, EMAIL, "not the password")
    with pytest.raises(Unauthorized) as unknown:
        auth.login(session, "nobody@example.com", "not the password")
    assert wrong.value.message == unknown.value.message == auth.BAD_CREDENTIALS


def test_a_disabled_account_cannot_sign_in(session, user):
    sql(session, "UPDATE users SET is_active = false WHERE id = :u", u=user)
    with pytest.raises(Unauthorized):
        auth.login(session, EMAIL, PASSWORD)


def test_old_hashes_are_upgraded_on_login(session, user, monkeypatch):
    before = sql(session, "SELECT password_hash FROM users WHERE id = :u", u=user).scalar_one()
    monkeypatch.setattr(security, "_hasher", PasswordHasher(time_cost=2, memory_cost=8, parallelism=1))
    auth.login(session, EMAIL, PASSWORD)
    after = sql(session, "SELECT password_hash FROM users WHERE id = :u", u=user).scalar_one()
    assert after != before
    assert security.verify_password(after, PASSWORD)


# ---- lockout -----------------------------------------------------------------------------
def test_five_failures_lock_the_account_even_for_the_right_password(session, user):
    fail_login(session, auth.MAX_FAILURES)
    with pytest.raises(TooManyRequests):
        auth.login(session, EMAIL, PASSWORD)


def test_failures_before_a_success_do_not_count_against_you(session, user):
    fail_login(session, auth.MAX_FAILURES - 1)
    auth.login(session, EMAIL, PASSWORD)  # a success resets the count
    fail_login(session, auth.MAX_FAILURES - 1)
    auth.login(session, EMAIL, PASSWORD)  # still not locked


def test_the_lockout_ends_after_the_window(session, user):
    fail_login(session, auth.MAX_FAILURES)
    sql(session, "UPDATE login_attempts SET attempted_at = now() - interval '20 minutes' WHERE email = :e", e=EMAIL)
    auth.login(session, EMAIL, PASSWORD)


def test_guessing_an_unknown_email_is_throttled_too(session):
    fail_login(session, auth.MAX_FAILURES, email="ghost@example.com")
    with pytest.raises(TooManyRequests):
        auth.login(session, "ghost@example.com", "anything")


# ---- sessions ----------------------------------------------------------------------------
def test_only_a_hash_of_the_session_token_is_stored(session, user):
    _, token = auth.login(session, EMAIL, PASSWORD)
    assert sql(session, "SELECT count(*) FROM sessions WHERE token_hash = :t", t=token).scalar_one() == 0
    digest = hashlib.sha256(token.encode()).hexdigest()
    assert sql(session, "SELECT count(*) FROM sessions WHERE token_hash = :t", t=digest).scalar_one() == 1


def test_a_made_up_token_is_rejected(session, user):
    assert auth.authenticate_session(session, "made-up") is None


def test_logout_revokes_the_session(session, user):
    _, token = auth.login(session, EMAIL, PASSWORD)
    auth.revoke_session(session, token)
    assert auth.authenticate_session(session, token) is None


def test_an_expired_session_is_rejected(session, user):
    _, token = auth.login(session, EMAIL, PASSWORD)
    sql(session, "UPDATE sessions SET expires_at = now() - interval '1 second'")
    assert auth.authenticate_session(session, token) is None


def test_an_idle_session_is_rejected(session, user):
    _, token = auth.login(session, EMAIL, PASSWORD)
    sql(session, "UPDATE sessions SET last_seen_at = now() - interval '15 days'")
    assert auth.authenticate_session(session, token) is None


def test_using_a_session_refreshes_last_seen_but_not_on_every_request(session, user):
    _, token = auth.login(session, EMAIL, PASSWORD)
    sql(session, "UPDATE sessions SET last_seen_at = now() - interval '2 hours'")
    auth.authenticate_session(session, token)
    assert sql(session, "SELECT last_seen_at > now() - interval '1 minute' FROM sessions").scalar_one()

    sql(session, "UPDATE sessions SET last_seen_at = now() - interval '10 minutes'")
    auth.authenticate_session(session, token)
    assert sql(session, "SELECT last_seen_at < now() - interval '5 minutes' FROM sessions").scalar_one()


def test_a_disabled_user_loses_access_immediately(session, user):
    _, token = auth.login(session, EMAIL, PASSWORD)
    sql(session, "UPDATE users SET is_active = false WHERE id = :u", u=user)
    assert auth.authenticate_session(session, token) is None


def test_changing_the_password_signs_out_every_session(session, user):
    _, first = auth.login(session, EMAIL, PASSWORD)
    _, second = auth.login(session, EMAIL, PASSWORD)
    auth.set_password(session, EMAIL, "a brand new passphrase")
    assert auth.authenticate_session(session, first) is None
    assert auth.authenticate_session(session, second) is None
    with pytest.raises(Unauthorized):
        auth.login(session, EMAIL, PASSWORD)
    auth.login(session, EMAIL, "a brand new passphrase")


def test_resetting_the_password_of_nobody_is_an_error(session):
    with pytest.raises(LookupError):
        auth.set_password(session, "nobody@example.com", "a perfectly fine passphrase")


# ---- API tokens --------------------------------------------------------------------------
def test_an_ingest_token_authenticates_and_is_stored_hashed(session, user):
    token = auth.create_api_token(session, user, "Pixel 8")
    assert token.startswith("fin_")
    assert auth.authenticate_api_token(session, token, "ingest").id == user
    assert sql(session, "SELECT count(*) FROM api_tokens WHERE token_hash = :t", t=token).scalar_one() == 0


def test_a_revoked_token_stops_working(session, user):
    token = auth.create_api_token(session, user, "Pixel 8")
    assert auth.revoke_api_token(session, user, "Pixel 8") is True
    assert auth.authenticate_api_token(session, token, "ingest") is None
    assert auth.revoke_api_token(session, user, "Pixel 8") is False


def test_a_token_for_a_disabled_user_is_rejected(session, user):
    token = auth.create_api_token(session, user, "Pixel 8")
    sql(session, "UPDATE users SET is_active = false WHERE id = :u", u=user)
    assert auth.authenticate_api_token(session, token, "ingest") is None


def test_a_token_is_only_good_for_its_own_scope(session, user):
    token = auth.create_api_token(session, user, "Pixel 8")
    assert auth.authenticate_api_token(session, token, "admin") is None


def test_a_session_token_is_not_an_api_token_and_vice_versa(session, user):
    _, session_token = auth.login(session, EMAIL, PASSWORD)
    api_token = auth.create_api_token(session, user, "Pixel 8")
    assert auth.authenticate_api_token(session, session_token, "ingest") is None
    assert auth.authenticate_session(session, api_token) is None