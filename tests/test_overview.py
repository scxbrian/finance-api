"""The Home screen's numbers, from a small ledger whose totals can be checked by hand.

The ledger mirrors docs/api-contract.md: on 15 Nov 2026 income is 65,000, expenses are 31,240
and 'saved' is 33,760, against 62,000 / 36,800 / 25,200 over 1-15 October.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from app.core.clock import NAIROBI
from app.services.overview import build_overview

TODAY = date(2026, 11, 15)


def at(month, day, hour=12):
    return datetime(2026, month, day, hour, 0, tzinfo=NAIROBI)


def make_user(db, email="a@example.com"):
    return db.execute(
        text("INSERT INTO users (email, display_name, password_hash) VALUES (:e, 'T', 'x') RETURNING id"),
        {"e": email},
    ).scalar_one()


def make_account(db, user, name, kind, subtype=None, archived=False):
    return db.execute(
        text("INSERT INTO ledger_accounts (user_id, name, kind, subtype, archived_at)"
             " VALUES (:u, :n, :k, :s, CASE WHEN :a THEN now() END) RETURNING id"),
        {"u": user, "n": name, "k": kind, "s": subtype, "a": archived},
    ).scalar_one()


def post(db, user, kind, title, when, *legs):
    """legs are (account_id, signed amount); they must sum to zero."""
    tx = db.execute(
        text("INSERT INTO transactions (user_id, occurred_at, kind, title, source)"
             " VALUES (:u, :at, :k, :t, 'manual') RETURNING id"),
        {"u": user, "at": when, "k": kind, "t": title},
    ).scalar_one()
    for account, amount in legs:
        db.execute(
            text("INSERT INTO entries (user_id, transaction_id, ledger_account_id, amount_minor) VALUES (:u, :t, :a, :m)"),
            {"u": user, "t": tx, "a": account, "m": amount},
        )
    assert sum(amount for _, amount in legs) == 0
    return tx


def populate(db, u):
    """Fills one user's ledger with the two-month example. Returns the account ids by name."""
    a = {
        "user": u,
        "mpesa": make_account(db, u, "M-Pesa", "asset", "mpesa"),
        "bank": make_account(db, u, "Bank", "asset", "bank"),
        "cash": make_account(db, u, "Cash", "asset", "cash"),
        "ziidi": make_account(db, u, "Ziidi", "asset", "mmf"),
        "salary": make_account(db, u, "Salary", "income"),
        "rent": make_account(db, u, "Rent", "expense"),
        "groceries": make_account(db, u, "Groceries", "expense"),
        "transport": make_account(db, u, "Transport", "expense"),
        "fees": make_account(db, u, "Fees", "expense"),
        "opening": make_account(db, u, "Opening Balances", "equity"),
    }
    bank, mpesa = a["bank"], a["mpesa"]
    post(db, u, "opening", "Ziidi opening balance", at(10, 1), (a["ziidi"], 4_000_000), (a["opening"], -4_000_000))
    # October
    post(db, u, "income", "Salary", at(10, 2), (bank, 6_200_000), (a["salary"], -6_200_000))
    post(db, u, "expense", "Rent", at(10, 5), (a["rent"], 1_800_000), (bank, -1_800_000))
    post(db, u, "expense", "Naivas", at(10, 8), (a["groceries"], 1_880_000), (bank, -1_880_000))
    post(db, u, "expense", "Naivas", at(10, 20), (a["groceries"], 500_000), (bank, -500_000))  # after the 15th
    # November
    post(db, u, "income", "Salary", at(11, 1), (bank, 6_500_000), (a["salary"], -6_500_000))
    post(db, u, "expense", "Rent", at(11, 10), (a["rent"], 1_800_000), (bank, -1_800_000))
    post(db, u, "transfer", "Top up M-Pesa", at(11, 12), (mpesa, 1_000_000), (bank, -1_000_000))
    post(db, u, "expense", "Matatus", at(11, 13), (a["transport"], 1_089_300), (bank, -1_089_300))
    post(db, u, "expense", "Naivas", at(11, 14), (a["groceries"], 234_000), (a["fees"], 700), (mpesa, -234_700))
    post(db, u, "expense", "Later this month", at(11, 20), (a["transport"], 99_900), (bank, -99_900))
    return a


@pytest.fixture
def ledger(db):
    return populate(db, make_user(db))


# ---- the summary -------------------------------------------------------------------------
def test_the_summary_matches_the_hand_computed_numbers(db, ledger):
    summary = build_overview(db, ledger["user"], "2026-11", TODAY)["summary"]
    assert summary == {
        "income_minor": 6_500_000,
        "expenses_minor": 3_124_000,
        "saved_minor": 3_376_000,
        "previous": {"income_minor": 6_200_000, "expenses_minor": 3_680_000, "saved_minor": 2_520_000},
    }


def test_the_comparison_period_stops_where_this_one_does(db, ledger):
    out = build_overview(db, ledger["user"], "2026-11", TODAY)
    assert out["period"] == {"from": "2026-11-01", "to": "2026-11-15"}
    assert out["previous_period"] == {"from": "2026-10-01", "to": "2026-10-15"}
    # October's 20th (500,000 of groceries) is outside 1-15 Oct, so it is not in 'previous'.
    assert out["summary"]["previous"]["expenses_minor"] == 3_680_000


def test_the_future_part_of_the_month_is_left_out(db, ledger):
    out = build_overview(db, ledger["user"], "2026-11", TODAY)
    assert "Later this month" not in [t["title"] for t in out["recent_transactions"]]
    assert out["summary"]["expenses_minor"] == 3_124_000  # without the 20 Nov 99,900


def test_transfers_and_opening_balances_are_neither_income_nor_spending(db, ledger):
    summary = build_overview(db, ledger["user"], "2026-10", TODAY)["summary"]
    # October holds an opening balance of 40,000 and salary 62,000: only the salary is income.
    assert summary["income_minor"] == 6_200_000
    nov = build_overview(db, ledger["user"], "2026-11", TODAY)["summary"]
    assert nov["income_minor"] == 6_500_000  # the 10,000 top-up is not income


def test_a_fee_counts_as_spending_and_is_reported_on_its_own(db):
    u = make_user(db)
    mpesa, fees, other = (make_account(db, u, n, k) for n, k in [("M-Pesa", "asset"), ("Fees", "expense"), ("Uncategorised", "expense")])
    post(db, u, "expense", "Sent to John", at(11, 14), (other, 50_000), (fees, 700), (mpesa, -50_700))
    out = build_overview(db, u, "2026-11", TODAY)
    assert out["summary"]["expenses_minor"] == 50_700
    only = out["recent_transactions"][0]
    assert (only["amount_minor"], only["fee_minor"], only["category"]) == (50_700, 700, "Uncategorised")


# ---- balances ----------------------------------------------------------------------------
def test_the_total_is_the_sum_of_the_accounts(db, ledger):
    out = build_overview(db, ledger["user"], "2026-11", TODAY)
    assert out["total_balance_minor"] == 9_396_000  # 40,000 opening + 127,000 income - 73,040 spent
    assert sum(a["balance_minor"] for a in out["accounts"]) == out["total_balance_minor"]


def test_money_dated_in_the_future_is_not_in_the_balance_until_its_day(db, ledger):
    before = build_overview(db, ledger["user"], "2026-11", date(2026, 11, 19))["total_balance_minor"]
    after = build_overview(db, ledger["user"], "2026-11", date(2026, 11, 20))["total_balance_minor"]
    assert before - after == 99_900  # the 20 Nov matatu fare leaves the bank on the 20th


def test_accounts_carry_contract_types_and_exact_balances(db, ledger):
    accounts = {a["name"]: a for a in build_overview(db, ledger["user"], "2026-11", TODAY)["accounts"]}
    assert accounts["M-Pesa"]["type"] == "mpesa" and accounts["M-Pesa"]["balance_minor"] == 765_300
    assert accounts["Ziidi"]["type"] == "savings"  # a money market fund is a savings product
    assert accounts["Cash"]["balance_minor"] == 0  # empty accounts are still listed
    assert set(accounts) == {"M-Pesa", "Bank", "Cash", "Ziidi"}  # categories are not accounts


def test_the_total_does_not_depend_on_which_month_is_shown(db, ledger):
    totals = {build_overview(db, ledger["user"], m, TODAY)["total_balance_minor"] for m in ("2026-09", "2026-10", "2026-11")}
    assert len(totals) == 1


def test_archived_accounts_are_hidden_but_their_money_still_counts(db):
    u = make_user(db)
    live = make_account(db, u, "Bank", "asset", "bank")
    old = make_account(db, u, "Old savings", "asset", "savings", archived=True)
    eq = make_account(db, u, "Opening Balances", "equity")
    post(db, u, "opening", "Open", at(11, 1), (live, 100), (old, 900), (eq, -1000))
    out = build_overview(db, u, "2026-11", TODAY)
    assert [a["name"] for a in out["accounts"]] == ["Bank"]
    assert out["total_balance_minor"] == 1000


# ---- recent activity ---------------------------------------------------------------------
def test_recent_is_the_newest_five_in_the_period_newest_first(db, ledger):
    recent = build_overview(db, ledger["user"], "2026-11", TODAY)["recent_transactions"]
    assert [t["title"] for t in recent] == ["Naivas", "Matatus", "Top up M-Pesa", "Rent", "Salary"]
    assert [t["occurred_on"] for t in recent] == ["2026-11-14", "2026-11-13", "2026-11-12", "2026-11-10", "2026-11-01"]


def test_recent_rows_have_the_contract_shape(db, ledger):
    recent = build_overview(db, ledger["user"], "2026-11", TODAY)["recent_transactions"]
    transfer = next(t for t in recent if t["kind"] == "transfer")
    assert transfer["account"]["name"] == "Bank" and transfer["to_account"]["name"] == "M-Pesa"
    assert transfer["category"] is None and transfer["amount_minor"] == 1_000_000
    salary = next(t for t in recent if t["kind"] == "income")
    assert salary["category"] == "Salary" and salary["account"]["name"] == "Bank" and salary["amount_minor"] == 6_500_000
    assert set(salary) == {"id", "occurred_on", "kind", "title", "amount_minor", "fee_minor", "category",
                           "account", "to_account", "source"}


def test_the_limit_is_respected(db, ledger):
    assert len(build_overview(db, ledger["user"], "2026-11", TODAY, recent=2)["recent_transactions"]) == 2


# ---- other months, and 'no comparison' ---------------------------------------------------
def test_a_finished_month_covers_all_of_it(db, ledger):
    out = build_overview(db, ledger["user"], "2026-10", TODAY)
    assert out["period"] == {"from": "2026-10-01", "to": "2026-10-31"}
    assert out["summary"]["income_minor"] == 6_200_000
    assert out["summary"]["expenses_minor"] == 1_800_000 + 1_880_000 + 500_000  # includes the 20th


def test_there_is_no_comparison_when_nothing_came_before(db, ledger):
    # The first thing in the ledger happened on 1 Oct, so October has nothing earlier to compare with.
    assert build_overview(db, ledger["user"], "2026-10", TODAY)["summary"]["previous"] is None


def test_an_empty_earlier_period_is_zero_not_missing(db):
    u = make_user(db)
    bank, salary = make_account(db, u, "Bank", "asset", "bank"), make_account(db, u, "Salary", "income")
    post(db, u, "income", "Salary", at(8, 5), (bank, 100), (salary, -100))  # history exists, but not in October
    previous = build_overview(db, u, "2026-11", TODAY)["summary"]["previous"]
    assert previous == {"income_minor": 0, "expenses_minor": 0, "saved_minor": 0}


def test_a_future_month_is_simply_empty(db, ledger):
    out = build_overview(db, ledger["user"], "2026-12", TODAY)
    assert out["period"] == {"from": "2026-12-01", "to": "2026-12-31"}
    assert (out["summary"]["income_minor"], out["summary"]["expenses_minor"]) == (0, 0)
    assert out["recent_transactions"] == []


def test_a_brand_new_user_gets_a_well_formed_empty_overview(db):
    out = build_overview(db, make_user(db), "2026-11", TODAY)
    assert out["total_balance_minor"] == 0 and out["accounts"] == [] and out["recent_transactions"] == []
    assert out["summary"] == {"income_minor": 0, "expenses_minor": 0, "saved_minor": 0, "previous": None}


# ---- days, and people --------------------------------------------------------------------
def test_the_business_day_is_the_nairobi_day(db):
    u = make_user(db)
    bank, salary = make_account(db, u, "Bank", "asset", "bank"), make_account(db, u, "Salary", "income")
    late_utc = datetime(2026, 11, 15, 22, 30, tzinfo=UTC)  # 01:30 on the 16th in Nairobi
    post(db, u, "income", "Late", late_utc, (bank, 500), (salary, -500))
    assert build_overview(db, u, "2026-11", date(2026, 11, 15))["summary"]["income_minor"] == 0
    assert build_overview(db, u, "2026-11", date(2026, 11, 16))["summary"]["income_minor"] == 500


def test_one_users_money_never_appears_for_another(db, ledger):
    other = make_user(db, "b@example.com")
    bank, salary = make_account(db, other, "Bank", "asset", "bank"), make_account(db, other, "Salary", "income")
    post(db, other, "income", "Their salary", at(11, 3), (bank, 999_999_900), (salary, -999_999_900))

    mine = build_overview(db, ledger["user"], "2026-11", TODAY)
    theirs = build_overview(db, other, "2026-11", TODAY)
    assert mine["summary"]["income_minor"] == 6_500_000
    assert all(t["title"] != "Their salary" for t in mine["recent_transactions"])
    assert theirs["total_balance_minor"] == 999_999_900
    assert [a["name"] for a in theirs["accounts"]] == ["Bank"]