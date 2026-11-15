from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ServiceUnavailable

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Touches nothing else, so it can never hang."""
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness: the process is up and the database answers."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise ServiceUnavailable("The database is not reachable.") from None
    return {"status": "ready"}