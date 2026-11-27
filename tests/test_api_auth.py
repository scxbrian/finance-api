"""Login, sessions and SMS ingest through the real HTTP layer (cookies, headers, error shapes)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_db
from app.main import create_app
from app.services import auth
from sms_fixtures import load_cases

EMAIL = "brian@example.com"
PASSWORD = "a perfectly fine passphrase"
WEB = "https://finance-web.example.com"
AIRTIME = next(c for c in load_cases() if "UKC8X1QHD3" in c.body)


@pytest.fixture
def make_client(session, monkeypatch):
    """Builds an app bound to the test database session, optionally with other settings."""

    def build(env: dict | None = None, base_url: str = "http://testserver") -> TestClient:
        for key, value in (env or {}).items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: session
        return TestClient(app, base_url=base_url)

    yield build
    get_settings.cache_clear()


@pytest.fixture
def user(session):
    return auth.create_user(session, EMAIL, "Brian", PASSWORD)


def login(client, password=PASSWORD, **headers):
    return client.post("/api/auth/login", json={"email": EMAIL, "password": password}, headers=headers)


PRODUCTION = {"APP_ENV": "production", "APP_ORIGINS": WEB}


# ---- the session cookie ------------------------------------------------------------------
def test_login_sets_a_cookie_javascript_cannot_read(make_client, user):
    response = login(make_client())
    assert response.status_code == 200
    assert response.json()["user"]["email"] == EMAIL
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("session=")
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "secure" not in cookie  # plain-http development only


def test_in_production_the_cookie_is_secure_and_host_prefixed(make_client, user):
    client = make_client(PRODUCTION, base_url="https://testserver")
    response = login(client, origin=WEB)
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("__host-session=")
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_me_needs_a_session_and_then_works(make_client, user):
    client = make_client()
    unauthenticated = client.get("/api/auth/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "unauthorized"
    login(client)
    assert client.get("/api/auth/me").json()["user"]["email"] == EMAIL


def test_logout_ends_the_session_and_clears_the_cookie(make_client, user):
    client = make_client()
    login(client)
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").status_code == 401


def test_logging_out_twice_is_fine(make_client, user):
    client = make_client()
    assert client.post("/api/auth/logout").status_code == 200


# ---- failures ----------------------------------------------------------------------------
def test_wrong_password_and_unknown_email_look_identical(make_client, user):
    client = make_client()
    wrong = login(client, password="definitely not it")
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "definitely not it"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "set-cookie" not in wrong.headers


def test_repeated_failures_answer_429(make_client, user):
    client = make_client()
    for _ in range(5):
        login(client, password="wrong")
    locked = login(client)  # even the correct password now
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "too_many_attempts"


def test_a_malformed_login_is_a_validation_error(make_client):
    response = make_client().post("/api/auth/login", json={"email": "a@b.co"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---- the origin check (CSRF) -------------------------------------------------------------
def test_production_refuses_a_login_with_no_origin(make_client, user):
    response = login(make_client(PRODUCTION, base_url="https://testserver"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


def test_production_refuses_a_foreign_origin(make_client, user):
    response = login(make_client(PRODUCTION, base_url="https://testserver"), origin="https://evil.example.net")
    assert response.status_code == 403


def test_production_accepts_the_web_app_origin(make_client, user):
    assert login(make_client(PRODUCTION, base_url="https://testserver"), origin=WEB).status_code == 200


def test_logout_is_origin_checked_too(make_client, user):
    client = make_client(PRODUCTION, base_url="https://testserver")
    login(client, origin=WEB)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"origin": WEB}).status_code == 200


def test_reading_does_not_need_an_origin(make_client, user):
    client = make_client(PRODUCTION, base_url="https://testserver")
    login(client, origin=WEB)
    assert client.get("/api/auth/me").status_code == 200


def test_production_with_no_configured_origin_fails_closed(make_client, user):
    client = make_client({"APP_ENV": "production", "APP_ORIGINS": ""}, base_url="https://testserver")
    assert login(client, origin=WEB).status_code == 403


# ---- SMS ingest --------------------------------------------------------------------------
def sms(body=AIRTIME.body, received="2026-11-12T09:34:00+03:00", sender="MPESA"):
    return {"sender": sender, "body": body, "received_at": received}


@pytest.fixture
def token(session, user):
    return auth.create_api_token(session, user, "Pixel 8")


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_the_phone_can_post_a_message_and_it_becomes_a_transaction(make_client, session, user, token):
    client = make_client()
    response = client.post("/api/ingest/sms", json=sms(), headers=bearer(token))
    assert response.status_code == 200
    assert response.json()["status"] == "created"
    balance = session.execute(
        text("SELECT sum(amount_minor) FROM entries e JOIN ledger_accounts a ON a.id = e.ledger_account_id"
             " WHERE e.user_id = :u AND a.name = 'M-Pesa'"), {"u": user}).scalar_one()
    assert balance == -500


def test_a_retry_answers_200_and_counts_once(make_client, session, user, token):
    client = make_client()
    client.post("/api/ingest/sms", json=sms(), headers=bearer(token))
    again = client.post("/api/ingest/sms", json=sms(), headers=bearer(token))
    assert (again.status_code, again.json()["status"]) == (200, "duplicate")
    assert session.execute(text("SELECT count(*) FROM transactions WHERE user_id = :u"), {"u": user}).scalar_one() == 1


def test_a_login_code_is_acknowledged_but_never_stored(make_client, session, user, token):
    otp = sms(body="<#> Please use 123456 as your login code (token).", sender="ETICALTD")
    response = make_client().post("/api/ingest/sms", json=otp, headers=bearer(token))
    assert (response.status_code, response.json()["status"]) == (200, "discarded")
    assert session.execute(text("SELECT count(*) FROM source_messages")).scalar_one() == 0


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer fin_wrong"}, {"Authorization": "Basic abc"}])
def test_ingest_without_a_valid_token_is_refused(make_client, user, token, headers):
    response = make_client().post("/api/ingest/sms", json=sms(), headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_a_valid_token_under_the_wrong_scheme_is_refused(make_client, user, token):
    """Only `Bearer` is accepted, even when the secret itself is right."""
    for scheme in ("Basic", "Token", "bearerish"):
        response = make_client().post("/api/ingest/sms", json=sms(), headers={"Authorization": f"{scheme} {token}"})
        assert response.status_code == 401, scheme


def test_a_revoked_token_is_refused(make_client, session, user, token):
    auth.revoke_api_token(session, user, "Pixel 8")
    assert make_client().post("/api/ingest/sms", json=sms(), headers=bearer(token)).status_code == 401


def test_a_signed_in_browser_cannot_use_the_ingest_endpoint(make_client, user):
    client = make_client()
    login(client)  # has a valid session cookie
    assert client.post("/api/ingest/sms", json=sms()).status_code == 401


def test_an_ingest_token_cannot_read_the_account(make_client, token):
    response = make_client().get("/api/auth/me", headers=bearer(token))
    assert response.status_code == 401


def test_ingest_needs_no_origin_even_in_production(make_client, user, token):
    client = make_client(PRODUCTION, base_url="https://testserver")
    assert client.post("/api/ingest/sms", json=sms(), headers=bearer(token)).status_code == 200


@pytest.mark.parametrize(
    "bad",
    [sms(received="2026-11-12T09:34:00"), sms(received="2099-01-01T00:00:00+03:00"), sms(body=""), sms(sender="")],
    ids=["no-timezone", "future", "empty-body", "empty-sender"],
)
def test_malformed_messages_are_validation_errors(make_client, user, token, bad):
    response = make_client().post("/api/ingest/sms", json=bad, headers=bearer(token))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

def test_the_forwarder_apps_own_payload_shape_is_accepted(make_client, session, user, token):
    """The Android app sends the arrival time as Unix MILLISECONDS inside a string."""
    from datetime import UTC, datetime

    ms = int(datetime(2026, 11, 12, 6, 34, tzinfo=UTC).timestamp() * 1000)
    response = make_client().post(
        "/api/ingest/sms",
        json={"sender": "MPESA", "body": AIRTIME.body, "received_at": str(ms)},
        headers=bearer(token),
    )
    assert (response.status_code, response.json()["status"]) == (200, "created")


def test_a_message_from_an_unknown_sender_is_acknowledged_but_never_stored(make_client, session, user, token):
    response = make_client().post(
        "/api/ingest/sms", json=sms(body="Hi dear, call me", sender="Mum"), headers=bearer(token)
    )
    assert (response.status_code, response.json()["status"], response.json()["reason"]) == (200, "discarded", "unknown_sender")
    assert session.execute(text("SELECT count(*) FROM source_messages")).scalar_one() == 0