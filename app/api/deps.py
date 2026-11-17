"""Request dependencies: who is calling, and is this request allowed to change anything."""

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.services import auth
from app.services.auth import AuthUser

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class OriginNotAllowed(Forbidden):
    code = "origin_not_allowed"


def require_allowed_origin(request: Request) -> None:
    """CSRF defence for browser requests that change data.

    The session cookie is SameSite=Lax, which already stops most cross-site posts. This
    second layer checks the Origin header the browser attaches. In production an empty
    APP_ORIGINS refuses everything, so a missing setting fails closed, not open.
    """
    if request.method in SAFE_METHODS:
        return
    settings = get_settings()
    allowed = settings.app_origin_list
    if not allowed and not settings.is_production:
        return  # local development convenience only
    if request.headers.get("origin") not in allowed:
        raise OriginNotAllowed("This request did not come from the web app.")


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=int(auth.SESSION_MAX.total_seconds()),
        httponly=True,  # JavaScript can never read it, so an XSS bug cannot steal it
        secure=settings.use_secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    # Same attributes as when it was set, or browsers ignore the deletion of a __Host- cookie.
    response.set_cookie(
        settings.session_cookie_name, "", max_age=0, httponly=True,
        secure=settings.use_secure_cookies, samesite="lax", path="/",
    )


def current_user(request: Request, db: Session = Depends(get_db)) -> AuthUser:
    token = request.cookies.get(get_settings().session_cookie_name)
    user = auth.authenticate_session(db, token) if token else None
    if user is None:
        raise Unauthorized("Sign in required.")
    db.commit()  # persists the occasional "last seen" update
    return user


def ingest_user(request: Request, db: Session = Depends(get_db)) -> AuthUser:
    """Authenticates the phone's forwarder by its bearer token. Cookies are never accepted here."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    user = auth.authenticate_api_token(db, token.strip(), "ingest") if scheme.lower() == "bearer" and token else None
    if user is None:
        raise Unauthorized("A valid ingest token is required.")
    db.commit()
    return user