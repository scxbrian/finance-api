"""Etica Capital (sender ETICALTD). Two messages per withdrawal: a request notice, then a completion."""

import re
from datetime import datetime

from app.core.clock import NAIROBI
from app.parsers.common import AMOUNT, mask_phone, to_minor
from app.parsers.types import Ignored, Parsed, ParseResult, Unrecognised

_DASH = r"[\u2013-]"  # the messages use an en dash

_REQUEST = re.compile(
    r"^Dear esteemed client, Kindly note that we have processed a withdrawal of KES " + AMOUNT
    + r" to Mpesa " + _DASH + r" \d{9,12}\. Please await Mpesa notification\.$"
)
_COMPLETED = re.compile(
    r"^Dear esteemed client, Your payment of KES (?P<amt>" + AMOUNT + r") to (?P<phone>\d{12}) "
    + _DASH + r" (?P<who>.+?) from account (?P<acct>\S+) \((?P<fund>[^)]+)\)"
    r" has been processed successfully\. Transaction ref: (?P<ref>[A-Z0-9]{10})$"
)


def parse(text: str, received_at: datetime) -> ParseResult:
    if _REQUEST.match(text):
        return Ignored("request_acknowledged")  # the completion message is the real event
    m = _COMPLETED.match(text)
    if not m:
        return Unrecognised("etica_unknown_format")
    try:
        return Parsed(
            kind="etica.withdrawal_completed",
            provider="etica",
            reference=m["ref"],  # the M-Pesa receipt code: it ties this to the M-Pesa message
            amount_minor=to_minor(m["amt"]),
            counterparty=m["who"],
            counterparty_ref=mask_phone(m["phone"]),
            account_suffix=m["acct"][-4:],
            occurred_at=received_at.astimezone(NAIROBI),
            date_from_message=False,
        )
    except ValueError:
        return Unrecognised("invalid_value")