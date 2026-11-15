import os

# Set before the app is imported. Port 1 is closed, so any real database call fails fast.
os.environ["DATABASE_URL"] = "postgresql+psycopg://test:test@127.0.0.1:1/test"
os.environ["APP_ENV"] = "development"
os.environ["CORS_ORIGINS"] = ""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())