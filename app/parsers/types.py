"""What a parser can say about a message. There are exactly three outcomes."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Parsed:
    """Facts read from one message. Parsers report facts; they never decide ledger postings."""

    kind: str  # e.g. "mpesa.sent", "ziidi.withdrawn", "coop.card_purchase"
    provider: str  # mpesa | ziidi | etica | coop
    amount_minor: int  # in `currency`, never negative
    occurred_at: datetime  # timezone-aware, Africa/Nairobi
    reference: str | None = None  # shared across messages about one event (the M-Pesa code)
    fee_minor: int = 0
    balance_after_minor: int | None = None
    currency: str = "KES"
    counterparty: str | None = None  # who or what was paid / who paid
    counterparty_ref: str | None = None  # paybill account, till number, masked phone
    account_suffix: str | None = None  # last digits of an account, never the whole number
    date_from_message: bool = True  # False: the message had no date, so occurred_at = SMS arrival


@dataclass(frozen=True)
class Ignored:
    """Recognised, and deliberately has no ledger effect."""

    reason: str  # otp | declined | failed | zero_amount | request_acknowledged | ...
    store_raw: bool = True  # False for secrets such as login codes: never persist the text


@dataclass(frozen=True)
class Unrecognised:
    """Not understood. It goes to a review inbox; it is never guessed at."""

    reason: str = "no_pattern_matched"


ParseResult = Parsed | Ignored | Unrecognised