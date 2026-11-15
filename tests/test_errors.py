"""The error handlers, exercised on a throwaway app so no real route is needed."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import Conflict, install_error_handlers
from app.core.middleware import ApiHeadersMiddleware


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(ApiHeadersMiddleware)

    @app.get("/typed")
    def typed(amount_minor: int):
        return {"amount_minor": amount_minor}

    @app.get("/conflict")
    def conflict():
        raise Conflict("That reference already exists.", fields={"external_ref": "Already used."})

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    return TestClient(app, raise_server_exceptions=False)


def test_validation_errors_name_the_field(client):
    response = client.get("/typed", params={"amount_minor": "abc"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "amount_minor" in error["fields"]
    assert "query" not in error["fields"]  # the location prefix is dropped


def test_deliberate_errors_carry_fields(client):
    response = client.get("/conflict")
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "conflict",
            "message": "That reference already exists.",
            "fields": {"external_ref": "Already used."},
        }
    }


def test_unexpected_errors_never_leak_details(client):
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Something went wrong on the server."}
    }
    assert "secret" not in response.text
    assert response.headers["cache-control"] == "no-store"