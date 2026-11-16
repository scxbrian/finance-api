"""The ledger's rules, enforced by PostgreSQL itself and tested against a real database.

Each test runs inside a transaction that is rolled back. Deferred checks (such as "entries
sum to zero") normally fire at COMMIT, so tests call settle() to fire them on demand.
"""

from datetime import UTC, datetime

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from conftest import alembic_config

NOON = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


# ---- tiny helpers ------------------------------------------------------------------------
def make_user(db, email="a@example.com"):
    return db.execute(
        text("INSERT INTO users (email, display_name, password_hash) VALUES (:e, 'T', 'x') RETURNING id"),
        {"e": email},
    ).scalar_one()


def make_account(db, user, name, kind="asset", subtype=None):
    return db.execute(
        text("INSERT INTO ledger_accounts (user_id, name, kind, subtype) VALUES (:u, :n, :k, :s) RETURNING id"),
        {"u": user, "n": name, "k": kind, "s": subtype},
    ).scalar_one()


def make_tx(db, user, kind="expense", title="t", at=NOON, ref=None, reversal_of=None):
    return db.execute(
        text(
            "INSERT INTO transactions (user_id, occurred_at, kind, title, source, external_ref, reversal_of)"
            " VALUES (:u, :at, :k, :t, 'manual', :r, :rev) RETURNING id"
        ),
        {"u": user, "at": at, "k": kind, "t": title, "r": ref, "rev": reversal_of},
    ).scalar_one()


def add_entry(db, user, tx, account, amount):
    db.execute(
        text("INSERT INTO entries (user_id, transaction_id, ledger_account_id, amount_minor) VALUES (:u, :t, :a, :m)"),
        {"u": user, "t": tx, "a": account, "m": amount},
    )


def post(db, user, debit, credit, amount, **kw):
    """A balanced two-entry transaction: `debit` gains `amount`, `credit` loses it."""
    tx = make_tx(db, user, **kw)
    add_entry(db, user, tx, debit, amount)
    add_entry(db, user, tx, credit, -amount)
    return tx


def settle(db):
    db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.fixture
def world(db):
    """One user with a wallet, a bank, a grocery category and salary income."""
    user = make_user(db)
    return {
        "user": user,
        "mpesa": make_account(db, user, "M-Pesa", "asset", "mpesa"),
        "bank": make_account(db, user, "Bank", "asset", "bank"),
        "groceries": make_account(db, user, "Groceries", "expense"),
        "salary": make_account(db, user, "Salary", "income"),
    }


# ---- migrations --------------------------------------------------------------------------
def test_migration_can_be_undone_and_redone(test_database_url, migrated_engine):
    config = alembic_config(test_database_url)
    command.downgrade(config, "base")
    with migrated_engine.connect() as connection:
        tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars().all()
    assert "transactions" not in tables
    command.upgrade(config, "head")  # leave the shared database as we found it


# ---- the balancing rule ------------------------------------------------------------------
def test_a_balanced_transaction_is_accepted(db, world):
    post(db, world["user"], world["groceries"], world["mpesa"], 234_000)
    settle(db)  # does not raise


def test_an_unbalanced_transaction_is_rejected(db, world):
    tx = make_tx(db, world["user"])
    add_entry(db, world["user"], tx, world["groceries"], 234_000)
    add_entry(db, world["user"], tx, world["mpesa"], -200_000)
    with pytest.raises(IntegrityError, match="unbalanced"):
        settle(db)


def test_a_transaction_with_no_entries_is_rejected(db, world):
    make_tx(db, world["user"])
    with pytest.raises(IntegrityError, match="at least two entries"):
        settle(db)


def test_a_one_sided_transaction_is_rejected(db, world):
    tx = make_tx(db, world["user"])
    add_entry(db, world["user"], tx, world["mpesa"], 100)
    with pytest.raises(IntegrityError, match="at least two entries"):
        settle(db)


def test_zero_amount_entries_are_rejected(db, world):
    tx = make_tx(db, world["user"])
    with pytest.raises(IntegrityError):
        add_entry(db, world["user"], tx, world["mpesa"], 0)


def test_the_whole_ledger_always_sums_to_zero(db, world):
    u = world["user"]
    post(db, u, world["bank"], world["salary"], 6_500_000, kind="income")
    post(db, u, world["mpesa"], world["bank"], 1_000_000, kind="transfer")
    post(db, u, world["groceries"], world["mpesa"], 234_000)
    settle(db)
    total = db.execute(text("SELECT sum(amount_minor) FROM entries WHERE user_id = :u"), {"u": u}).scalar_one()
    assert total == 0
    # Balances come straight out of the entries: 6,500,000 - 1,000,000 = 5,500,000 in the bank.
    balance = lambda account: db.execute(
        text("SELECT sum(amount_minor) FROM entries WHERE ledger_account_id = :a"), {"a": account}
    ).scalar_one()
    assert balance(world["bank"]) == 5_500_000
    assert balance(world["mpesa"]) == 1_000_000 - 234_000
    assert -balance(world["salary"]) == 6_500_000  # income is stored negative


# ---- the business day --------------------------------------------------------------------
def test_the_business_day_is_the_nairobi_day(db, world):
    late_utc = datetime(2026, 11, 14, 22, 30, tzinfo=UTC)  # 01:30 on the 15th in Nairobi
    tx = make_tx(db, world["user"], at=late_utc)
    day = db.execute(text("SELECT occurred_on FROM transactions WHERE id = :t"), {"t": tx}).scalar_one()
    assert str(day) == "2026-11-15"


# ---- no mixing of users ------------------------------------------------------------------
def test_an_entry_cannot_use_another_users_account(db, world):
    other = make_user(db, "b@example.com")
    their_account = make_account(db, other, "Theirs")
    tx = make_tx(db, world["user"])
    with pytest.raises(IntegrityError):
        add_entry(db, world["user"], tx, their_account, 100)


def test_a_transaction_cannot_reverse_another_users_transaction(db, world):
    other = make_user(db, "b@example.com")
    theirs = make_tx(db, other)
    with pytest.raises(IntegrityError):
        make_tx(db, world["user"], reversal_of=theirs)


def test_a_message_cannot_attach_to_another_users_transaction(db, world):
    other = make_user(db, "b@example.com")
    theirs = make_tx(db, other)
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO source_messages (user_id, transaction_id, sender, body, body_sha256, received_at,"
                " parse_status, parser_version) VALUES (:u, :t, 'MPESA', 'b', :h, :at, 'parsed', '1')"
            ),
            {"u": world["user"], "t": theirs, "h": "a" * 64, "at": NOON},
        )


# ---- references and reversals ------------------------------------------------------------
def test_one_reference_cannot_create_two_transactions(db, world):
    make_tx(db, world["user"], ref="UKF8X24CHK")
    with pytest.raises(IntegrityError):
        make_tx(db, world["user"], ref="UKF8X24CHK")


def test_the_same_reference_is_fine_for_a_different_user(db, world):
    make_tx(db, world["user"], ref="UKF8X24CHK")
    other = make_user(db, "b@example.com")
    make_tx(db, other, ref="UKF8X24CHK")  # does not raise


def test_many_transactions_may_have_no_reference(db, world):
    make_tx(db, world["user"])
    make_tx(db, world["user"])  # does not raise


def test_a_transaction_can_be_reversed_only_once(db, world):
    original = post(db, world["user"], world["groceries"], world["mpesa"], 500)
    make_tx(db, world["user"], reversal_of=original)
    with pytest.raises(IntegrityError):
        make_tx(db, world["user"], reversal_of=original)


# ---- append-only -------------------------------------------------------------------------
def test_entries_cannot_be_edited(db, world):
    post(db, world["user"], world["groceries"], world["mpesa"], 500)
    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(text("UPDATE entries SET amount_minor = 1 WHERE user_id = :u"), {"u": world["user"]})


def test_entries_cannot_be_deleted(db, world):
    post(db, world["user"], world["groceries"], world["mpesa"], 500)
    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(text("DELETE FROM entries WHERE user_id = :u"), {"u": world["user"]})


def test_transactions_cannot_be_deleted(db, world):
    tx = make_tx(db, world["user"])
    with pytest.raises(IntegrityError, match="append-only"):
        db.execute(text("DELETE FROM transactions WHERE id = :t"), {"t": tx})


def test_posted_facts_are_frozen_but_the_title_can_be_edited(db, world):
    tx = make_tx(db, world["user"], title="Naivas")
    db.execute(text("UPDATE transactions SET title = 'Naivas Westlands', note = 'weekly' WHERE id = :t"), {"t": tx})
    with pytest.raises(IntegrityError, match="cannot be changed"):
        db.execute(text("UPDATE transactions SET kind = 'income' WHERE id = :t"), {"t": tx})


def test_a_reference_can_be_attached_once_and_never_changed(db, world):
    tx = make_tx(db, world["user"])
    db.execute(text("UPDATE transactions SET external_ref = 'UKF8X24CHK' WHERE id = :t"), {"t": tx})
    with pytest.raises(IntegrityError, match="already set"):
        db.execute(text("UPDATE transactions SET external_ref = 'OTHER' WHERE id = :t"), {"t": tx})


# ---- messages, emails and account identifiers --------------------------------------------
def test_the_same_message_cannot_be_stored_twice(db, world):
    params = {"u": world["user"], "h": "b" * 64, "at": NOON}
    sql = text(
        "INSERT INTO source_messages (user_id, sender, body, body_sha256, received_at, parse_status, parser_version)"
        " VALUES (:u, 'MPESA', 'body', :h, :at, 'parsed', '1')"
    )
    db.execute(sql, params)
    with pytest.raises(IntegrityError):
        db.execute(sql, params)  # a forwarder retry


def test_emails_are_unique_ignoring_case(db):
    make_user(db, "Brian@Example.com")
    with pytest.raises(IntegrityError):
        make_user(db, "brian@example.com")


def test_an_account_identifier_is_unique_per_user_and_provider(db, world):
    sql = text(
        "INSERT INTO account_identifiers (user_id, ledger_account_id, provider, suffix) VALUES (:u, :a, 'coop', '0001')"
    )
    db.execute(sql, {"u": world["user"], "a": world["bank"]})
    with pytest.raises(IntegrityError):
        db.execute(sql, {"u": world["user"], "a": world["mpesa"]})