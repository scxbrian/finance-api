"""Password and token primitives. No database needed."""

import hashlib

import pytest
from argon2 import PasswordHasher

from app.core import security


def test_a_password_verifies_against_its_own_hash_only():
    stored = security.hash_password("correct horse battery staple")
    assert security.verify_password(stored, "correct horse battery staple")
    assert not security.verify_password(stored, "correct horse battery stapl")


def test_hashes_are_salted_so_equal_passwords_differ():
    assert security.hash_password("same password here") != security.hash_password("same password here")


def test_an_unknown_account_never_verifies_but_still_does_the_work():
    assert security.verify_password(None, "anything at all") is False
    # Even the dummy's own password must not log anyone in.
    assert security.verify_password(None, "not-a-real-password") is False


def test_a_corrupt_stored_hash_fails_closed():
    assert security.verify_password("not a hash", "whatever password") is False


def test_the_real_default_settings_are_argon2id_and_work():
    real = PasswordHasher()  # what production uses
    encoded = real.hash("a long enough password")
    assert encoded.startswith("$argon2id$")
    assert not real.check_needs_rehash(encoded)


def test_weaker_hashes_are_flagged_for_upgrade(monkeypatch):
    weak = security.hash_password("a long enough password")  # the cheap test settings
    monkeypatch.setattr(security, "_hasher", PasswordHasher(time_cost=2, memory_cost=8, parallelism=1))
    assert security.needs_rehash(weak)


@pytest.mark.parametrize(
    ("password", "email", "fragment"),
    [("short", None, "at least"), ("x" * 129, None, "at most"), ("Me@Example.com", "me@example.com", "email")],
)
def test_weak_passwords_are_refused(password, email, fragment):
    with pytest.raises(ValueError, match=fragment):
        security.validate_password(password, email)


def test_length_not_complexity_is_what_counts():
    security.validate_password("alllowercasebutlong")  # does not raise


def test_tokens_are_long_unique_and_prefixable():
    tokens = {security.new_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(len(t) >= 43 for t in tokens)  # 256 bits in url-safe base64
    assert security.new_token(security.API_TOKEN_PREFIX).startswith("fin_")


def test_only_a_one_way_hash_of_a_token_is_stored():
    token = security.new_token()
    assert security.hash_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert token not in security.hash_token(token)