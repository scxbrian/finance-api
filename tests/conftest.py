import os
from pathlib import Path

# Set before the app is imported. Port 1 is closed, so any real database call fails fast.
os.environ["DATABASE_URL"] = "postgresql+psycopg://test:test@127.0.0.1:1/test"
os.environ["APP_ENV"] = "development"
os.environ["CORS_ORIGINS"] = ""

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# ---- database tests ----------------------------------------------------------------------
# These need a real PostgreSQL and are skipped unless TEST_DATABASE_URL is set, so a plain
# `pytest` on a machine without a database still passes.


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("set TEST_DATABASE_URL to run the database tests")
    database = create_engine(url).url.database or ""
    # The next fixture DROPS the schema. Refuse to go anywhere near a real database.
    if not database.endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must name a database ending in '_test', not {database!r}")
    return url


@pytest.fixture(scope="session")
def migrated_engine(test_database_url):
    engine = create_engine(test_database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(test_database_url), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_engine):
    """A connection inside a transaction that is always rolled back, so tests never leak data."""
    connection = migrated_engine.connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()