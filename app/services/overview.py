"""Everything the Home screen shows, computed in one pass (see docs/api-contract.md)."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.services.ledger_view import list_transactions
from app.services.periods import Period, periods_for

# Contract "type" values. Money market funds are savings products from the user's point of view.
ACCOUNT_TYPES = {"mpesa": "mpesa", "bank": "bank", "cash": "cash", "savings": "savings", "mmf": "savings"}


def _flows(db: Any, user_id: UUID, period: Period) -> dict[str, int]:
    """Income and expenses in a period, straight from the entries.

    Only income and expense accounts count, so transfers between your own accounts and opening
    balances can never be mistaken for earning or spending. Income is stored negative, hence
    the sign flip. Fees sit on an expense account, so they are included in expenses.
    """
    rows = db.execute(
        text(
            "SELECT a.kind, sum(e.amount_minor) FROM entries e"
            " JOIN transactions t ON t.id = e.transaction_id"
            " JOIN ledger_accounts a ON a.id = e.ledger_account_id"
            " WHERE e.user_id = :u AND a.kind IN ('income', 'expense')"
            "   AND t.occurred_on BETWEEN :start AND :end GROUP BY a.kind"
        ),
        {"u": user_id, "start": period.start, "end": period.end},
    ).all()
    totals = {kind: int(total) for kind, total in rows}
    income = -totals.get("income", 0)
    expenses = totals.get("expense", 0)
    return {"income_minor": income, "expenses_minor": expenses, "saved_minor": income - expenses}


def _accounts(db: Any, user_id: UUID, today: date) -> tuple[list[dict], int]:
    """Balances as of the end of `today` (Nairobi). Entries dated later are planned, not yet real."""
    rows = db.execute(
        text(
            "SELECT a.id, a.name, a.subtype, a.kind, a.archived_at IS NOT NULL AS archived,"
            "       COALESCE(sum(e.amount_minor) FILTER (WHERE t.occurred_on <= :today), 0) AS balance"
            " FROM ledger_accounts a"
            " LEFT JOIN entries e ON e.ledger_account_id = a.id"
            " LEFT JOIN transactions t ON t.id = e.transaction_id"
            " WHERE a.user_id = :u AND a.kind IN ('asset', 'liability') GROUP BY a.id"
        ),
        {"u": user_id, "today": today},
    ).all()
    total = sum(int(r.balance) for r in rows)  # archived accounts still hold money
    shown = sorted(
        (
            {
                "id": str(r.id),
                "name": r.name,
                "type": "liability" if r.kind == "liability" else ACCOUNT_TYPES.get(r.subtype or "", "other"),
                "balance_minor": int(r.balance),
            }
            for r in rows
            if not r.archived
        ),
        key=lambda a: (-a["balance_minor"], a["name"]),
    )
    return shown, total


def build_overview(db: Any, user_id: UUID, month: str, today: date, recent: int = 5) -> dict:
    current, previous = periods_for(month, today)
    accounts, total_balance = _accounts(db, user_id, today)

    # "No earlier data" is different from "earlier data that happens to be zero".
    has_history = db.execute(
        text("SELECT EXISTS (SELECT 1 FROM transactions WHERE user_id = :u AND occurred_on < :start)"),
        {"u": user_id, "start": current.start},
    ).scalar_one()

    recent_rows, _ = list_transactions(db, user_id, current, limit=recent)
    return {
        "month": month,
        "period": current.as_json(),
        "previous_period": previous.as_json(),
        "total_balance_minor": total_balance,
        "accounts": accounts,
        "summary": {**_flows(db, user_id, current), "previous": _flows(db, user_id, previous) if has_history else None},
        "recent_transactions": recent_rows,
    }