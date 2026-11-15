from app.core.config import Settings


def test_cors_origins_are_split_and_trimmed():
    settings = Settings(database_url="x", cors_origins=" http://a.test , http://b.test ,, ")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_empty_cors_means_no_origins():
    assert Settings(database_url="x", cors_origins="").cors_origin_list == []


def test_docs_are_off_in_production(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert client.get("/api/docs").status_code == 404
        assert client.get("/api/openapi.json").status_code == 404
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()