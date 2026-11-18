"""The read endpoints through HTTP: sessions, validation, shape, and who sees what."""

from datetime import date

import pytest

from app.services import auth
from test_api_auth import EMAIL, PASSWORD, login, make_client, user  # noqa: F401  (fixtures)
from test_overview import populate

TODAY = date(2026, 11, 15)


@pytest.fixture
def signed_in(make_client, session, user, monkeypatch):  # noqa: F811
    """A client signed in as a user whose ledger is the two-month example, 'today' = 15 Nov 2026."""
    monkeypatch.setattr("app.api.routers.overview.today_nairobi", lambda: TODAY)
    populate(session, user)
    client = make_client()
    assert login(client).status_code == 200
    return client


# ---- who may read ------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/api/overview", "/api/transactions"])
def test_reading_needs_a_session(make_client, path):
    response = make_client().get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


# ---- the overview ------------------------------------------------------------------------
def test_the_overview_has_exactly_the_contract_shape(signed_in):
    response = signed_in.get("/api/overview")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"month", "period", "previous_period", "total_balance_minor", "accounts",
                         "summary", "recent_transactions"}
    assert body["month"] == "2026-11"  # defaults to the current month in Nairobi
    assert set(body["summary"]) == {"income_minor", "expenses_minor", "saved_minor", "previous"}
    assert body["summary"]["saved_minor"] == 3_376_000
    assert set(body["accounts"][0]) == {"id", "name", "type", "balance_minor"}


def test_responses_are_never_cacheable(signed_in):
    assert signed_in.get("/api/overview").headers["cache-control"] == "no-store"
    assert signed_in.get("/api/transactions").headers["cache-control"] == "no-store"


def test_another_month_can_be_asked_for(signed_in):
    assert signed_in.get("/api/overview?month=2026-10").json()["period"] == {"from": "2026-10-01", "to": "2026-10-31"}


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "yesterday", "1999-01", "2026-11-01"])
def test_a_bad_month_is_a_validation_error_naming_the_field(signed_in, month):
    response = signed_in.get(f"/api/overview?month={month}")
    assert response.status_code == 422
    assert "month" in response.json()["error"]["fields"]


# ---- the ledger list ---------------------------------------------------------------------
def test_the_list_reports_its_total_and_pages(signed_in):
    body = signed_in.get("/api/transactions?month=2026-11&limit=2&offset=2").json()
    assert body["total"] == 6 and len(body["transactions"]) == 2
    assert body["period"] == {"from": "2026-11-01", "to": "2026-11-30"}  # a list covers the whole month


def test_the_list_filters(signed_in):
    body = signed_in.get("/api/transactions?month=2026-11&kind=expense&q=naivas").json()
    assert [t["title"] for t in body["transactions"]] == ["Naivas"]


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=201", "offset=-1", "kind=bogus", "account=not-a-uuid", "q=" + "x" * 101, "category=" + "x" * 101],
)
def test_bad_list_parameters_are_validation_errors(signed_in, query):
    response = signed_in.get(f"/api/transactions?{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_search_text_cannot_run_as_sql(signed_in):
    response = signed_in.get("/api/transactions", params={"q": "'; DROP TABLE transactions; --"})
    assert response.status_code == 200 and response.json()["total"] == 0
    assert signed_in.get("/api/transactions?month=2026-11").json()["total"] == 6


# ---- people ------------------------------------------------------------------------------
def test_each_user_sees_only_their_own_ledger(signed_in, make_client, session):  # noqa: F811
    auth.create_user(session, "other@example.com", "Other", PASSWORD)
    other = make_client()
    assert other.post("/api/auth/login", json={"email": "other@example.com", "password": PASSWORD}).status_code == 200
    body = other.get("/api/overview").json()
    assert body["total_balance_minor"] == 0 and body["accounts"] == [] and body["recent_transactions"] == []
    assert other.get("/api/transactions").json()["total"] == 0
    assert signed_in.get("/api/overview").json()["total_balance_minor"] == 9_396_000