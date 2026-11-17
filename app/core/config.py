"""Settings, read once from environment variables (or a local .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    # extra="ignore": the shared .env also holds POSTGRES_* values for Docker Compose.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "production"] = "development"
    database_url: str  # required; the app refuses to start without it
    cors_origins: str = ""  # comma-separated; leave empty in production

    # Origins of the web app (e.g. https://finance-web.vercel.app). Browser requests that
    # change data must come from one of these. In production, empty means "refuse them all".
    app_origins: str = ""
    # None = decide from app_env. Set false only to test over plain http.
    cookie_secure: bool | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return _split(self.cors_origins)

    @property
    def app_origin_list(self) -> list[str]:
        return _split(self.app_origins)

    @property
    def use_secure_cookies(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure

    @property
    def session_cookie_name(self) -> str:
        # The __Host- prefix makes browsers refuse the cookie unless it is Secure, has
        # Path=/ and names no Domain, so a sibling subdomain cannot overwrite it.
        return "__Host-session" if self.use_secure_cookies else "session"


@lru_cache
def get_settings() -> Settings:
    return Settings()