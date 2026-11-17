from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import clear_session_cookie, current_user, require_allowed_origin, set_session_cookie
from app.core.config import get_settings
from app.core.db import get_db
from app.schemas.auth import LoginIn
from app.services import auth
from app.services.auth import AuthUser

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_body(user: AuthUser) -> dict:
    return {"user": {"id": str(user.id), "email": user.email, "display_name": user.display_name}}


@router.post("/login", dependencies=[Depends(require_allowed_origin)])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    user, token = auth.login(db, body.email, body.password, request.headers.get("user-agent", ""))
    set_session_cookie(response, token)
    return _user_body(user)


@router.post("/logout", dependencies=[Depends(require_allowed_origin)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(get_settings().session_cookie_name)
    if token:
        auth.revoke_session(db, token)
        db.commit()
    clear_session_cookie(response)
    return {"ok": True}  # signing out twice is not an error


@router.get("/me")
def me(user: AuthUser = Depends(current_user)) -> dict:
    return _user_body(user)