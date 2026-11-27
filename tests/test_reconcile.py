"""Tests for retroactive opening balances and balance mismatch detection."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text

from app.services import chart, reconcile


def _seed_user_and_tx(db, *, provider: str, amount_minor: int, fee_minor: int, reported_balance_minor: int, occurred_at: datetime):
    user_id = db.execute(
        text(
            "INSERT INTO users (email, display_name, password_hash)"
            " VALUES (:e, 'Test User', 'hashed') RETURNING id"
        ),
        {"e": f"reconcile_{uuid4().hex[:8]}@example.com"},
    ).scalar_one()

    asset_id = chart.provider_account(db, user_id, provider)
    expense_id = chart.get_or_create_account(db, user_id, chart.UNCATEGORISED, "expense")
    fee_id = chart.get_or_create_account(db, user_id, chart.FEES, "expense")

    tx_id = db.execute(
        text(
            "INSERT INTO transactions (user_id, occurred_at, kind, title, source)"
            " VALUES (:u, :at, 'expense', 'Test Spend', 'sms') RETURNING id"
        ),
        {"u": user_id, "at": occurred_at},
    ).scalar_one()

    total_out = amount_minor + fee_minor
    entries = [
        {"u": user_id, "t": tx_id, "a": asset_id, "m": -total_out},
        {"u": user_id, "t": tx_id, "a": expense_id, "m": amount_minor},
    ]
    if fee_minor:
        entries.append({"u": user_id, "t": tx_id, "a": fee_id, "m": fee_minor})

    db.execute(
        text("INSERT INTO entries (user_id, transaction_id, ledger_account_id, amount_minor) VALUES (:u, :t, :a, :m)"),
        entries,
    )

    msg_id = db.execute(
        text(
            "INSERT INTO source_messages"
            " (user_id, transaction_id, sender, body, body_sha256, received_at, parse_status, parser_version, parsed)"
            " VALUES (:u, :tx, 'MPESA', 'test msg', :h, :rec, 'parsed', '1', CAST(:p AS jsonb))"
            " RETURNING id"
        ),
        {
            "u": user_id,
            "tx": tx_id,
            "h": uuid4().hex * 2,
            "rec": occurred_at,
            "p": (
                f'{{"kind":"mpesa.sent","provider":"{provider}","reference":"TEST123456",'
                f'"occurred_at":"{occurred_at.isoformat()}","balance_after_minor":{reported_balance_minor}}}'
            ),
        },
    ).scalar_one()

    return user_id, asset_id, tx_id, msg_id


def test_reconcile_infers_opening_and_detects_mismatch(db):
    t1 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    # Spent 500.00 (50000 minor) + 10.00 fee (1000 minor); reported balance after = 449000 (4,490.00 KES).
    # Implied balance before tx = 449000 - (-51000) = 500000 (5,000.00 KES).
    user_id, asset_id, tx1_id, _ = _seed_user_and_tx(
        db,
        provider="mpesa",
        amount_minor=50000,
        fee_minor=1000,
        reported_balance_minor=449000,
        occurred_at=t1,
    )

    report1 = reconcile.reconcile_provider(db, user_id, "mpesa")
    assert report1.opening_balance_minor == 500000
    assert report1.opening_transaction_id is not None
    assert report1.checked_messages == 1
    assert report1.mismatches == []

    # Second tx spends 200.00 (20000 minor), expected balance = 449000 - 20000 = 429000,
    # but reported balance is 400000 -> 29000 minor mismatch.
    t2 = t1 + timedelta(hours=2)
    expense_id = chart.get_or_create_account(db, user_id, chart.UNCATEGORISED, "expense")
    tx2_id = db.execute(
        text(
            "INSERT INTO transactions (user_id, occurred_at, kind, title, source)"
            " VALUES (:u, :at, 'expense', 'Second Spend', 'sms') RETURNING id"
        ),
        {"u": user_id, "at": t2},
    ).scalar_one()
    db.execute(
        text("INSERT INTO entries (user_id, transaction_id, ledger_account_id, amount_minor) VALUES (:u, :t, :a, :m)"),
        [
            {"u": user_id, "t": tx2_id, "a": asset_id, "m": -20000},
            {"u": user_id, "t": tx2_id, "a": expense_id, "m": 20000},
        ],
    )
    db.execute(
        text(
            "INSERT INTO source_messages"
            " (user_id, transaction_id, sender, body, body_sha256, received_at, parse_status, parser_version, parsed)"
            " VALUES (:u, :tx, 'MPESA', 'test msg 2', :h, :rec, 'parsed', '1', CAST(:p AS jsonb))"
        ),
        {
            "u": user_id,
            "tx": tx2_id,
            "h": uuid4().hex * 2,
            "rec": t2,
            "p": (
                f'{{"kind":"mpesa.sent","provider":"mpesa","reference":"TEST654321",'
                f'"occurred_at":"{t2.isoformat()}","balance_after_minor":400000}}'
            ),
        },
    )

    report2 = reconcile.reconcile_provider(db, user_id, "mpesa")
    assert report2.opening_transaction_id is None  # already exists, not duplicated
    assert report2.checked_messages == 2
    assert len(report2.mismatches) == 1
    m = report2.mismatches[0]
    assert m.transaction_id == tx2_id
    assert m.expected_minor == 429000
    assert m.reported_minor == 400000
    assert m.delta_minor == -29000
    assert tx1_id != tx2_id
