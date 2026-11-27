"""Balance reconciliation: retroactive opening balances and mismatch checks."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.services import chart


@dataclass(frozen=True)
class Mismatch:
    message_id: UUID
    transaction_id: UUID | None
    reference: str | None
    occurred_at: str
    expected_minor: int
    reported_minor: int
    delta_minor: int


@dataclass(frozen=True)
class ReconciliationReport:
    provider: str
    account_id: UUID
    opening_transaction_id: UUID | None
    opening_balance_minor: int | None
    checked_messages: int
    mismatches: list[Mismatch]


def _has_opening_transaction(db: Any, user_id: UUID, account_id: UUID) -> bool:
    return bool(
        db.execute(
            text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM transactions t"
                "  JOIN entries e ON e.transaction_id = t.id"
                "  WHERE t.user_id = :u AND t.kind = 'opening' AND e.ledger_account_id = :a"
                ")"
            ),
            {"u": user_id, "a": account_id},
        ).scalar_one()
    )


def _post_opening_balance(db: Any, user_id: UUID, account_id: UUID, provider: str, amount_minor: int, at) -> UUID:
    equity_id = chart.get_or_create_account(db, user_id, "Opening Balances", "equity")
    tx_id = db.execute(
        text(
            "INSERT INTO transactions (user_id, occurred_at, kind, title, note, source)"
            " VALUES (:u, :at, 'opening', :title, :note, 'sms')"
            " RETURNING id"
        ),
        {
            "u": user_id,
            "at": at,
            "title": f"{chart.provider_name(provider)} opening balance",
            "note": "Retroactively inferred from earliest reported SMS balance",
        },
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO entries (user_id, transaction_id, ledger_account_id, amount_minor) VALUES"
            " (:u, :t, :asset, :asset_amt),"
            " (:u, :t, :eq, :eq_amt)"
        ),
        {
            "u": user_id,
            "t": tx_id,
            "asset": account_id,
            "asset_amt": amount_minor,
            "eq": equity_id,
            "eq_amt": -amount_minor,
        },
    )
    return tx_id


def reconcile_provider(db: Any, user_id: UUID, provider: str, *, apply_opening: bool = True) -> ReconciliationReport:
    """Reconcile a provider asset account against reported balances in parsed SMS messages."""
    account_id = chart.provider_account(db, user_id, provider)

    rows = db.execute(
        text(
            "SELECT m.id AS message_id, m.transaction_id, m.received_at,"
            "       m.parsed->>'kind' AS kind,"
            "       m.parsed->>'reference' AS reference,"
            "       m.parsed->>'occurred_at' AS occurred_at,"
            "       (m.parsed->>'balance_after_minor')::bigint AS reported_minor,"
            "       COALESCE(("
            "         SELECT sum(e.amount_minor) FROM entries e"
            "         WHERE e.transaction_id = m.transaction_id AND e.ledger_account_id = :a"
            "       ), 0) AS tx_delta_minor"
            " FROM source_messages m"
            " WHERE m.user_id = :u"
            "   AND m.parse_status = 'parsed'"
            "   AND m.parsed->>'provider' = :p"
            "   AND m.parsed ? 'balance_after_minor'"
            "   AND m.parsed->>'balance_after_minor' IS NOT NULL"
            " ORDER BY COALESCE((m.parsed->>'occurred_at')::timestamptz, m.received_at) ASC,"
            "          m.received_at ASC, m.created_at ASC"
        ),
        {"u": user_id, "p": provider, "a": account_id},
    ).all()

    opening_tx_id: UUID | None = None
    opening_balance_minor: int | None = None

    if rows and apply_opening and not _has_opening_transaction(db, user_id, account_id):
        first = rows[0]
        reported_first = int(first.reported_minor)
        tx_delta_first = int(first.tx_delta_minor)
        prior_ledger_balance = int(
            db.execute(
                text(
                    "SELECT COALESCE(sum(e.amount_minor), 0) FROM entries e"
                    " JOIN transactions t ON t.id = e.transaction_id"
                    " WHERE e.user_id = :u AND e.ledger_account_id = :a"
                    "   AND t.occurred_at < COALESCE((:occ)::timestamptz, :rec)"
                ),
                {"u": user_id, "a": account_id, "occ": first.occurred_at, "rec": first.received_at},
            ).scalar_one()
        )
        implied_before = reported_first - tx_delta_first
        delta_needed = implied_before - prior_ledger_balance
        if delta_needed != 0:
            opening_at = first.received_at - timedelta(seconds=1)
            opening_tx_id = _post_opening_balance(db, user_id, account_id, provider, delta_needed, opening_at)
            opening_balance_minor = delta_needed

    # Evaluate running ledger balance up to each message's timestamp and compare against reported_minor.
    mismatches: list[Mismatch] = []
    seen_tx_ids: set[UUID] = set()
    running_balance = int(
        db.execute(
            text(
                "SELECT COALESCE(sum(e.amount_minor), 0) FROM entries e"
                " JOIN transactions t ON t.id = e.transaction_id"
                " WHERE e.user_id = :u AND e.ledger_account_id = :a"
            ),
            {"u": user_id, "a": account_id},
        ).scalar_one()
    )

    # Recompute strictly in chronological order using non-opening transactions + opening balance.
    base_balance = int(
        db.execute(
            text(
                "SELECT COALESCE(sum(e.amount_minor), 0) FROM entries e"
                " JOIN transactions t ON t.id = e.transaction_id"
                " WHERE e.user_id = :u AND e.ledger_account_id = :a AND t.kind = 'opening'"
            ),
            {"u": user_id, "a": account_id},
        ).scalar_one()
    )
    running_balance = base_balance

    tx_rows = db.execute(
        text(
            "SELECT t.id AS tx_id, COALESCE(sum(e.amount_minor), 0) AS delta"
            " FROM transactions t"
            " JOIN entries e ON e.transaction_id = t.id"
            " WHERE t.user_id = :u AND e.ledger_account_id = :a AND t.kind <> 'opening'"
            " GROUP BY t.id, t.occurred_at, t.created_at"
            " ORDER BY t.occurred_at ASC, t.created_at ASC, t.id ASC"
        ),
        {"u": user_id, "a": account_id},
    ).all()
    tx_deltas = {r.tx_id: int(r.delta) for r in tx_rows}
    ordered_tx_ids = [r.tx_id for r in tx_rows]

    # Map each transaction to the earliest message reporting balance_after_minor for it.
    msg_by_tx: dict[UUID, Any] = {}
    for r in rows:
        if r.transaction_id is not None and r.transaction_id not in msg_by_tx:
            msg_by_tx[r.transaction_id] = r

    checked = 0
    for tx_id in ordered_tx_ids:
        running_balance += tx_deltas.get(tx_id, 0)
        msg = msg_by_tx.get(tx_id)
        if msg is not None and msg.reported_minor is not None:
            checked += 1
            reported = int(msg.reported_minor)
            if running_balance != reported:
                mismatches.append(
                    Mismatch(
                        message_id=msg.message_id,
                        transaction_id=tx_id,
                        reference=msg.reference,
                        occurred_at=msg.occurred_at or msg.received_at.isoformat(),
                        expected_minor=running_balance,
                        reported_minor=reported,
                        delta_minor=reported - running_balance,
                    )
                )

    return ReconciliationReport(
        provider=provider,
        account_id=account_id,
        opening_transaction_id=opening_tx_id,
        opening_balance_minor=opening_balance_minor,
        checked_messages=checked,
        mismatches=mismatches,
    )
