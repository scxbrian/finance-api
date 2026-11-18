"""The ledger list: month scoping, filters, search and paging, against a real database."""

from datetime import date

import pytest
from sqlalchemy import text

from app.services.ledger_view import list_transactions
from app.services.periods import Period
from test_overview import at, ledger, make_account, make_user, post  # noqa: F401  (ledger is a fixture)

NOV = Period(date(2026, 11, 1), date(2026, 11, 30))
OCT = Period(date(2026, 10, 1), date(2026, 10, 31))


def titles(rows):
    return [r["title"] for r in rows]


def test_newest_first_and_the_total_counts_everything_matching(db, ledger):
    rows, total = list_transactions(db, ledger["user"], NOV)
    assert total == 6
    assert titles(rows) == ["Later this month", "Naivas", "Matatus", "Top up M-Pesa", "Rent", "Salary"]


def test_a_month_only_shows_its_own_days(db, ledger):
    rows, total = list_transactions(db, ledger["user"], OCT)
    assert total == 5
    assert "Later this month" not in titles(rows) and "Top up M-Pesa" not in titles(rows)


def test_pages_do_not_overlap_and_together_are_everything(db, ledger):
    everything, _ = list_transactions(db, ledger["user"], NOV)
    pages = [list_transactions(db, ledger["user"], NOV, limit=2, offset=o) for o in (0, 2, 4)]
    assert [t for _, t in pages] == [6, 6, 6]  # the total does not change between pages
    assert [r["id"] for rows, _ in pages for r in rows] == [r["id"] for r in everything]


def test_a_page_past_the_end_is_empty(db, ledger):
    rows, total = list_transactions(db, ledger["user"], NOV, limit=10, offset=50)
    assert (rows, total) == ([], 6)


@pytest.mark.parametrize(("kind", "expected"), [("expense", 4), ("income", 1), ("transfer", 1), ("opening", 0)])
def test_filter_by_kind(db, ledger, kind, expected):
    assert list_transactions(db, ledger["user"], NOV, kind=kind)[1] == expected


def test_filter_by_account_finds_every_transaction_that_touches_it(db, ledger):
    rows, _ = list_transactions(db, ledger["user"], NOV, account=ledger["mpesa"])
    assert titles(rows) == ["Naivas", "Top up M-Pesa"]  # the spend from it and the top-up into it


def test_filter_by_category_uses_income_and_expense_names_only(db, ledger):
    user = ledger["user"]
    assert titles(list_transactions(db, user, NOV, category="Groceries")[0]) == ["Naivas"]
    assert titles(list_transactions(db, user, NOV, category="Salary")[0]) == ["Salary"]
    assert list_transactions(db, user, NOV, category="Bank")[1] == 0  # an account is not a category


def test_filters_combine_with_and(db, ledger):
    rows, _ = list_transactions(db, ledger["user"], NOV, kind="expense", account=ledger["mpesa"])
    assert titles(rows) == ["Naivas"]


def test_search_ignores_case_and_looks_in_notes_too(db, ledger):
    user = ledger["user"]
    assert titles(list_transactions(db, user, NOV, q="RENT")[0]) == ["Rent"]
    db.execute(text("UPDATE transactions SET note = 'weekly shop' WHERE user_id = :u AND title = 'Naivas'"), {"u": user})
    assert titles(list_transactions(db, user, NOV, q="weekly")[0]) == ["Naivas"]


def test_search_treats_percent_and_underscore_as_ordinary_characters(db, ledger):
    user, bank = ledger["user"], ledger["bank"]
    sale = make_account(db, user, "Shopping", "expense")
    post(db, user, "expense", "Discount 100% off", at(11, 15), (sale, 100), (bank, -100))
    assert titles(list_transactions(db, user, NOV, q="100%")[0]) == ["Discount 100% off"]
    assert list_transactions(db, user, NOV, q="%")[1] == 1  # only the one that really contains a %
    assert list_transactions(db, user, NOV, q="_")[1] == 0  # not "any single character"


@pytest.mark.parametrize("attack", ["'; DROP TABLE transactions; --", "' OR '1'='1", "\\"])
def test_hostile_text_is_only_ever_data(db, ledger, attack):
    user = ledger["user"]
    assert list_transactions(db, user, NOV, q=attack)[1] == 0
    assert list_transactions(db, user, NOV, category=attack)[1] == 0
    assert list_transactions(db, user, NOV)[1] == 6  # the table is intact and nothing was widened


def test_another_users_transactions_never_appear(db, ledger):
    other = make_user(db, "b@example.com")
    bank, salary = make_account(db, other, "Bank", "asset", "bank"), make_account(db, other, "Salary", "income")
    post(db, other, "income", "Secret", at(11, 3), (bank, 5), (salary, -5))
    assert "Secret" not in titles(list_transactions(db, ledger["user"], NOV)[0])
    assert titles(list_transactions(db, other, NOV)[0]) == ["Secret"]
    # Not even by naming the other user's account id.
    assert list_transactions(db, ledger["user"], NOV, account=bank)[1] == 0