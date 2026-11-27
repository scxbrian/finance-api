from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.clock import today_nairobi
from app.core.db import get_db
from app.services import chart, ledger_view, reconcile
from app.services.auth import AuthUser
from app.services.overview import build_overview
from app.services.periods import MONTH_PATTERN, parse_month, whole_month

router = APIRouter(tags=["read"])


def _month(month: str | None) -> tuple[str, date]:
    today = today_nairobi()
    return month or today.strftime("%Y-%m"), today


@router.get("/overview")
def overview(
    month: str | None = Query(None, pattern=MONTH_PATTERN),
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    month, today = _month(month)
    return build_overview(db, user.id, month, today)


@router.get("/transactions")
def transactions(
    month: str | None = Query(None, pattern=MONTH_PATTERN),
    kind: str | None = Query(None, pattern="^(income|expense|transfer|opening|adjustment)$"),
    account: UUID | None = None,
    category: str | None = Query(None, max_length=100),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    month, _ = _month(month)
    # The whole month, including days after today: something dated tomorrow must still be visible.
    period = whole_month(*parse_month(month))
    rows, total = ledger_view.list_transactions(
        db, user.id, period, kind=kind, account=account, category=category, q=q or None, limit=limit, offset=offset
    )
    return {"month": month, "period": period.as_json(), "total": total, "transactions": rows}


@router.get("/reconcile")
def reconciliation_status(
    apply_opening: bool = Query(False),
    user: AuthUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    reports = []
    for provider in chart.PROVIDER_ACCOUNTS:
        rep = reconcile.reconcile_provider(db, user.id, provider, apply_opening=apply_opening)
        reports.append(
            {
                "provider": rep.provider,
                "account_id": str(rep.account_id),
                "opening_transaction_id": str(rep.opening_transaction_id) if rep.opening_transaction_id else None,
                "opening_balance_minor": rep.opening_balance_minor,
                "checked_messages": rep.checked_messages,
                "mismatches": [
                    {
                        "message_id": str(m.message_id),
                        "transaction_id": str(m.transaction_id) if m.transaction_id else None,
                        "reference": m.reference,
                        "occurred_at": m.occurred_at,
                        "expected_minor": m.expected_minor,
                        "reported_minor": m.reported_minor,
                        "delta_minor": m.delta_minor,
                    }
                    for m in rep.mismatches
                ],
            }
        )
    return {"providers": reports}
