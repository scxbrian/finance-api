from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import ingest_user
from app.core.db import get_db
from app.schemas.ingest import SmsIn
from app.services.auth import AuthUser
from app.services.intake import ingest_sms

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/sms")
def ingest(body: SmsIn, user: AuthUser = Depends(ingest_user), db: Session = Depends(get_db)) -> dict:
    """Called by the phone's SMS forwarder. Every handled message answers 200, even duplicates
    and ones ignored on purpose, so the forwarder never retries something we already dealt with."""
    outcome = ingest_sms(db, user.id, body.sender, body.body, body.received_at)
    db.commit()  # the ledger's deferred balance check runs here
    return {
        "status": outcome.status,
        "transaction_id": str(outcome.transaction_id) if outcome.transaction_id else None,
        "reason": outcome.reason,
    }