"""SMS intake against a real PostgreSQL: parsed messages become ledger entries.

Uses the same fixture messages as the parser tests, so what is posted here is what was
read from your real SMS (names and numbers replaced).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.services.intake import ingest_sms
from sms_fixtures import load_cases

CASES = load_cases()


# ---- helpers -----------------------------------------------------------------------------
def make_user(db, email="a@example.com"):
    return db.execute(
        text("INSERT INTO users (email, display_name, password_hash) VALUES (:e, 'T', 'x') RETURNING id"),
        {"e": email},
    ).scalar_one()


def case(sender, fragment):
    """The one fixture message from `sender` whose text contains `fragment`."""
    matches = [c for c in CASES if c.sender == sender and fragment in c.body]
    assert len(matches) == 1, f"{len(matches)} fixtures match {fragment!r}"
    return matches[0]


def send(db, user, c):
    return ingest_sms(db, user, c.sender, c.body, c.received)


def balances(db, user):
    """Net amount per account name, hiding accounts that net to zero."""
    rows = db.execute(
        text(
            "SELECT a.name, sum(e.amount_minor) FROM entries e JOIN ledger_accounts a ON a.id = e.ledger_account_id"
            " WHERE e.user_id = :u GROUP BY a.name"
        ),
        {"u": user},
    ).all()
    return {name: int(total) for name, total in rows if total != 0}


def count(db, user, table, where="true"):
    return db.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :u AND {where}"), {"u": user}).scalar_one()


def settle(db):
    db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.fixture
def user(db):
    return make_user(db)


# ---- one event, several messages ---------------------------------------------------------
@pytest.mark.parametrize("order", [("ZIIDI", "MPESA"), ("MPESA", "ZIIDI")])
def test_a_ziidi_withdrawal_and_its_mpesa_credit_become_one_transfer(db, user, order):
    """Same M-Pesa code from two senders. Either can arrive first; the money counts once."""
    by_sender = {"ZIIDI": case("ZIIDI", "UKF8X24CHK"), "MPESA": case("MPESA", "UKF8X24CHK")}
    first, second = (send(db, user, by_sender[s]) for s in order)

    assert (first.status, second.status) == ("created", "merged")
    assert first.transaction_id == second.transaction_id
    assert balances(db, user) == {"Ziidi": -10_000, "M-Pesa": 10_000}
    assert count(db, user, "transactions") == 1
    assert count(db, user, "source_messages", "transaction_id IS NOT NULL") == 2
    assert db.execute(text("SELECT kind FROM transactions WHERE user_id = :u"), {"u": user}).scalar_one() == "transfer"
    settle(db)


def test_the_stages_of_a_coop_deposit_post_one_transfer(db, user):
    first = send(db, user, case("CoopBank", "you have sent Ksh. 100.0"))
    second = send(db, user, case("CoopBank", "Account Deposit of KES 100 to account 01101234560001 was successful"))
    assert (first.status, second.status) == ("created", "merged")
    assert balances(db, user) == {"M-Pesa": -10_000, "Co-op Bank": 10_000}
    settle(db)


def test_a_retry_with_a_new_arrival_time_still_counts_once(db, user):
    c = case("MPESA", "UKC8X1QHD3")  # airtime
    assert send(db, user, c).status == "created"
    later = ingest_sms(db, user, c.sender, c.body, datetime(2026, 11, 12, 9, 40, tzinfo=UTC))
    assert later.status == "merged"
    assert balances(db, user) == {"M-Pesa": -500, "Airtime & Data": 500}


def test_the_identical_message_twice_is_a_duplicate(db, user):
    c = case("MPESA", "UKC8X1QHD3")
    send(db, user, c)
    assert send(db, user, c).status == "duplicate"
    assert count(db, user, "source_messages") == 1
    assert count(db, user, "transactions") == 1


# ---- what each kind of message means -----------------------------------------------------
def test_a_fee_is_its_own_line_inside_the_same_transaction(db, user):
    out = send(db, user, case("MPESA", "UKX1Y2Z3A4"))  # synthetic: Ksh500 sent, Ksh7 cost
    assert out.status == "created"
    assert balances(db, user) == {"M-Pesa": -50_700, "Uncategorised": 50_000, "Fees": 700}
    assert count(db, user, "entries") == 3
    settle(db)


def test_money_from_a_person_is_income(db, user):
    send(db, user, case("MPESA", "UKC5C1TT1I"))
    assert balances(db, user) == {"M-Pesa": 10_000, "Uncategorised Income": -10_000}
    assert db.execute(text("SELECT kind FROM transactions WHERE user_id = :u"), {"u": user}).scalar_one() == "income"


def test_airtime_goes_to_its_own_category(db, user):
    send(db, user, case("MPESA", "UKC8X1QHD3"))
    assert balances(db, user) == {"M-Pesa": -500, "Airtime & Data": 500}


def test_investing_in_ziidi_is_a_transfer_not_spending(db, user):
    send(db, user, case("ZIIDI", "UKC8X1QV16"))
    assert balances(db, user) == {"M-Pesa": -42_800, "Ziidi": 42_800}


def test_an_etica_withdrawal_moves_money_into_mpesa(db, user):
    send(db, user, case("ETICALTD", "Your payment of KES 5,000.00"))
    assert balances(db, user) == {"Etica": -500_000, "M-Pesa": 500_000}


def test_a_card_payment_is_spending_from_the_bank(db, user):
    send(db, user, case("CoopBank", "SPOTIFY"))
    assert balances(db, user) == {"Co-op Bank": -20_900, "Uncategorised": 20_900}


def test_the_day_comes_from_the_message_when_it_has_one(db, user):
    send(db, user, case("MPESA", "UKF8X24QSV"))
    day = db.execute(text("SELECT occurred_on FROM transactions WHERE user_id = :u"), {"u": user}).scalar_one()
    assert str(day) == "2026-11-15"


# ---- things that must NOT become money ---------------------------------------------------
def test_a_login_code_is_discarded_and_never_stored(db, user):
    out = send(db, user, case("ETICALTD", "login code"))
    assert out.status == "discarded"
    assert count(db, user, "source_messages") == 0


@pytest.mark.parametrize(
    ("sender", "fragment", "reason"),
    [
        ("MPESA", "Insufficient funds", "insufficient_funds"),
        ("CoopBank", "was declined", "declined"),
        ("CoopBank", "Transaction FAILED", "failed"),
        ("CoopBank", "USD 0 GOOGLE", "zero_amount"),
        ("ETICALTD", "Kindly note that we have processed a withdrawal", "request_acknowledged"),
    ],
)
def test_ignored_messages_are_kept_but_post_nothing(db, user, sender, fragment, reason):
    out = send(db, user, case(sender, fragment))
    assert (out.status, out.reason) == ("ignored", reason)
    assert count(db, user, "source_messages", "parse_status = 'ignored'") == 1
    assert count(db, user, "transactions") == 0


def test_an_unrecognised_message_waits_for_review(db, user):
    out = send(db, user, case("MPESA", "new kind of message"))
    assert out.status == "unrecognised"
    assert count(db, user, "source_messages", "parse_status = 'unrecognised'") == 1
    assert count(db, user, "transactions") == 0


def test_a_foreign_currency_purchase_is_flagged_not_guessed(db, user):
    out = send(db, user, case("CoopBank", "USD 12.50"))
    assert (out.status, out.reason) == ("unrecognised", "foreign_currency")
    assert count(db, user, "transactions") == 0


def test_two_messages_that_disagree_about_one_event_are_flagged_not_merged(db, user):
    """An M-Pesa paybill and a Co-op deposit sharing a code but meaning different things."""
    paybill = (
        "UCV8XB2LT8 Confirmed. Ksh100.00 sent to Cooperative Bank for account 123 on 31/03/26 at 10:18 AM."
        " New M-PESA balance is Ksh10.00. Transaction cost, Ksh0.00. Amount you can transact within the day is 1."
    )
    assert ingest_sms(db, user, "MPESA", paybill, datetime(2026, 3, 31, 7, 18, tzinfo=UTC)).status == "created"
    out = send(db, user, case("CoopBank", "Account Deposit of KES 100 to account 01101234560001 was successful"))
    assert (out.status, out.reason) == ("conflict", "conflicts_with_existing_transaction")
    assert count(db, user, "transactions") == 1  # nothing silently rewritten
    assert count(db, user, "source_messages", "parse_status = 'unrecognised'") == 1


# ---- users and the whole set -------------------------------------------------------------
def test_two_users_can_receive_the_same_message(db, user):
    other = make_user(db, "b@example.com")
    c = case("MPESA", "UKC8X1QHD3")
    assert send(db, user, c).status == "created"
    assert send(db, other, c).status == "created"
    assert balances(db, user) == balances(db, other)


def test_every_fixture_message_can_be_ingested_and_the_ledger_stays_balanced(db, user):
    outcomes = [send(db, user, c) for c in sorted(CASES, key=lambda c: c.received)]
    assert {o.status for o in outcomes} <= {"created", "merged", "conflict", "ignored", "unrecognised", "discarded"}
    settle(db)  # fires every deferred balance check

    total = db.execute(text("SELECT coalesce(sum(amount_minor), 0) FROM entries WHERE user_id = :u"), {"u": user}).scalar_one()
    assert total == 0
    # Every message the parser understood ended up attached to a transaction or flagged.
    orphans = count(db, user, "source_messages", "parse_status = 'parsed' AND transaction_id IS NULL")
    assert orphans == 0
    stored = count(db, user, "source_messages")
    assert stored == len(CASES) - sum(o.status == "discarded" for o in outcomes)