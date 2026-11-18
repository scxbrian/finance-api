"""How balanced entries read back as 'spent X on Y from Z'. Pure: no database."""

from uuid import uuid4

from app.services.ledger_view import Entry, describe

MPESA, BANK, ZIIDI = (uuid4() for _ in range(3))


def asset(account_id, name, amount):
    return Entry(account_id, name, "asset", amount)


def test_an_expense_reads_as_money_out_of_an_account_into_a_category():
    entries = [asset(MPESA, "M-Pesa", -234_000), Entry(uuid4(), "Groceries", "expense", 234_000)]
    out = describe("expense", entries)
    assert out["amount_minor"] == 234_000
    assert out["fee_minor"] == 0
    assert out["category"] == "Groceries"
    assert out["account"]["name"] == "M-Pesa"
    assert out["to_account"] is None


def test_the_fee_is_inside_the_amount_and_also_reported_on_its_own():
    entries = [
        asset(MPESA, "M-Pesa", -50_700),
        Entry(uuid4(), "Uncategorised", "expense", 50_000),
        Entry(uuid4(), "Fees", "expense", 700),
    ]
    out = describe("expense", entries)
    assert out["amount_minor"] == 50_700  # everything that left the account
    assert out["fee_minor"] == 700
    assert out["category"] == "Uncategorised"  # the fee never becomes the headline category


def test_income_reads_as_money_into_an_account_from_a_source():
    entries = [asset(BANK, "Bank", 6_500_000), Entry(uuid4(), "Salary", "income", -6_500_000)]
    out = describe("income", entries)
    assert out["amount_minor"] == 6_500_000  # a magnitude, not the stored negative
    assert out["category"] == "Salary"
    assert out["account"]["name"] == "Bank"


def test_a_transfer_names_both_accounts_and_has_no_category():
    entries = [asset(BANK, "Bank", -1_000_000), asset(MPESA, "M-Pesa", 1_000_000)]
    out = describe("transfer", entries)
    assert out["amount_minor"] == 1_000_000
    assert out["category"] is None
    assert out["account"]["name"] == "Bank"
    assert out["to_account"]["name"] == "M-Pesa"


def test_an_opening_balance_is_shown_against_the_account_it_opens():
    entries = [asset(ZIIDI, "Ziidi", 42_852), Entry(uuid4(), "Opening Balances", "equity", -42_852)]
    out = describe("opening", entries)
    assert out["amount_minor"] == 42_852
    assert out["account"]["name"] == "Ziidi"
    assert out["category"] is None


def test_a_broken_transaction_degrades_instead_of_crashing_the_screen():
    out = describe("expense", [])
    assert out["account"]["name"] == "Unknown account"
    assert out["amount_minor"] == 0


def test_amounts_are_never_negative():
    for kind, entries in [
        ("expense", [asset(MPESA, "M-Pesa", -5), Entry(uuid4(), "Uncategorised", "expense", 5)]),
        ("income", [asset(BANK, "Bank", 5), Entry(uuid4(), "Salary", "income", -5)]),
        ("transfer", [asset(BANK, "Bank", -5), asset(MPESA, "M-Pesa", 5)]),
    ]:
        assert describe(kind, entries)["amount_minor"] >= 0