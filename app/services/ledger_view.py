"""Reading the ledger back as the screens want to see it.

The ledger stores balanced entries; people think in "spent X on Y from Z". `describe` turns
one into the other. It is a pure function so every case can be tested without a database.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.services import chart
from app.services.periods import Period

HOLDING_KINDS = ("asset", "liability")  # where money sits


@dataclass(frozen=True)
class Entry:
    account_id: UUID | None
    account_name: str
    account_kind: str
    amount_minor: int


def _ref(entry: Entry | None) -> dict | None:
    if entry is None:
        return None
    return {"id": str(entry.account_id) if entry.account_id else None, "name": entry.account_name}


def describe(kind: str, entries: list[Entry]) -> dict[str, Any]:
    """amount_minor/fee_minor/category/account/to_account for one transaction.

    amount_minor is a magnitude (never negative); the kind says which way it went.
    For an expense it is the total that left the account, fee included, and fee_minor shows
    how much of that was the fee. Reversals are not produced yet and are not handled here.
    """
    holdings = [e for e in entries if e.account_kind in HOLDING_KINDS]
    spending = [e for e in entries if e.account_kind == "expense"]
    earning = [e for e in entries if e.account_kind == "income"]
    unknown = Entry(None, "Unknown account", "asset", 0)

    fee = 0
    category: str | None = None
    to_account: Entry | None = None

    if kind == "transfer" and holdings:
        account = min(holdings, key=lambda e: e.amount_minor)  # the one that lost money
        to_account = max(holdings, key=lambda e: e.amount_minor)  # the one that gained it
        amount = to_account.amount_minor
    elif kind == "expense" and holdings and spending:
        account = min(holdings, key=lambda e: e.amount_minor)
        amount = sum(e.amount_minor for e in spending)
        fee = sum(e.amount_minor for e in spending if e.account_name == chart.FEES)
        main = [e for e in spending if e.account_name != chart.FEES] or spending
        category = max(main, key=lambda e: e.amount_minor).account_name
    elif kind == "income" and holdings and earning:
        account = max(holdings, key=lambda e: e.amount_minor)
        amount = -sum(e.amount_minor for e in earning)
        category = min(earning, key=lambda e: e.amount_minor).account_name
    elif holdings:  # opening balances and adjustments
        account = max(holdings, key=lambda e: abs(e.amount_minor))
        amount = abs(account.amount_minor)
    else:
        account, amount = unknown, 0

    return {
        "amount_minor": amount,
        "fee_minor": fee,
        "category": category,
        "account": _ref(account),
        "to_account": _ref(to_account),
    }


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filters(user_id, period, kind, account, category, q) -> tuple[str, dict]:
    where = ["t.user_id = :u", "t.occurred_on BETWEEN :start AND :end"]
    params: dict[str, Any] = {"u": user_id, "start": period.start, "end": period.end}
    if kind:
        where.append("t.kind = :kind")
        params["kind"] = kind
    if account:
        where.append("EXISTS (SELECT 1 FROM entries e WHERE e.transaction_id = t.id AND e.ledger_account_id = :account)")
        params["account"] = account
    if category:
        where.append(
            "EXISTS (SELECT 1 FROM entries e JOIN ledger_accounts a ON a.id = e.ledger_account_id"
            " WHERE e.transaction_id = t.id AND a.name = :category AND a.kind IN ('expense', 'income'))"
        )
        params["category"] = category
    if q:
        where.append("(t.title ILIKE :q ESCAPE '\\' OR t.note ILIKE :q ESCAPE '\\')")
        params["q"] = f"%{_escape_like(q)}%"
    return " AND ".join(where), params


def list_transactions(
    db: Any, user_id: UUID, period: Period, *, kind: str | None = None, account: UUID | None = None,
    category: str | None = None, q: str | None = None, limit: int = 100, offset: int = 0,
) -> tuple[list[dict], int]:
    """(rows, total matching). Newest first. Only fixed SQL fragments are ever concatenated;
    every value the caller supplies travels as a bound parameter."""
    where, params = _filters(user_id, period, kind, account, category, q)

    total = db.execute(text(f"SELECT count(*) FROM transactions t WHERE {where}"), params).scalar_one()
    heads = db.execute(
        text(
            "SELECT t.id, t.occurred_on, t.kind, t.title, t.source FROM transactions t"
            f" WHERE {where} ORDER BY t.occurred_at DESC, t.created_at DESC, t.id DESC"
            " LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()
    if not heads:
        return [], total

    entries_by_tx: dict[UUID, list[Entry]] = {}
    for row in db.execute(
        text(
            "SELECT e.transaction_id, a.id, a.name, a.kind, e.amount_minor FROM entries e"
            " JOIN ledger_accounts a ON a.id = e.ledger_account_id WHERE e.transaction_id = ANY(:ids)"
        ),
        {"ids": [h.id for h in heads]},
    ):
        entries_by_tx.setdefault(row.transaction_id, []).append(Entry(row.id, row.name, row.kind, int(row.amount_minor)))

    rows = [
        {
            "id": str(h.id),
            "occurred_on": h.occurred_on.isoformat(),
            "kind": h.kind,
            "title": h.title,
            **describe(h.kind, entries_by_tx.get(h.id, [])),
            "source": h.source,
        }
        for h in heads
    ]
    return rows, total