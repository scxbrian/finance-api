"""The user's chart of accounts: finds an account, or creates the standard one on first use.

Accounts appear as messages arrive, so a new user needs no setup. Each provider gets one
asset account for now; several accounts at one provider would use `account_identifiers`.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text

# provider -> (account name, subtype)
PROVIDER_ACCOUNTS: dict[str, tuple[str, str]] = {
    "mpesa": ("M-Pesa", "mpesa"),
    "coop": ("Co-op Bank", "bank"),
    "ziidi": ("Ziidi", "mmf"),
    "etica": ("Etica", "mmf"),
}

UNCATEGORISED = "Uncategorised"
UNCATEGORISED_INCOME = "Uncategorised Income"
FEES = "Fees"
AIRTIME = "Airtime & Data"

_FIND = text("SELECT id FROM ledger_accounts WHERE user_id = :u AND kind = :k AND name = :n")
_CREATE = text(
    "INSERT INTO ledger_accounts (user_id, name, kind, subtype) VALUES (:u, :n, :k, :s)"
    " ON CONFLICT (user_id, kind, name) DO NOTHING"
)


def get_or_create_account(db: Any, user_id: UUID, name: str, kind: str, subtype: str | None = None) -> UUID:
    params = {"u": user_id, "n": name, "k": kind}
    found = db.execute(_FIND, params).scalar_one_or_none()
    if found is not None:
        return found
    db.execute(_CREATE, {**params, "s": subtype})  # DO NOTHING: a concurrent request may have won
    return db.execute(_FIND, params).scalar_one()


def provider_name(provider: str) -> str:
    return PROVIDER_ACCOUNTS[provider][0]


def provider_account(db: Any, user_id: UUID, provider: str) -> UUID:
    name, subtype = PROVIDER_ACCOUNTS[provider]
    return get_or_create_account(db, user_id, name, "asset", subtype)