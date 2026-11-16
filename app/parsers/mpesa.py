"""M-Pesa (sender MPESA). Dates are day/month/two-digit-year, times are 12-hour."""

import re
from datetime import datetime

from app.parsers.common import AMOUNT, mask_phone, nairobi, to_minor
from app.parsers.types import Ignored, Parsed, ParseResult, Unrecognised

# Real messages are inconsistent: "Confirmed.You", "PM.New", "Ksh0.00.Amount", and
# sometimes no "at" before the time. The pieces below are deliberately forgiving about
# exactly those gaps, and strict about everything that carries meaning.
_REF = r"^(?P<ref>[A-Z0-9]{10}) [Cc]onfirmed\. ?"
_DATE = (
    r" on (?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{2}) (?:at )?"
    r"(?P<h>\d{1,2}):(?P<mi>\d{2}) ?(?P<ap>AM|PM)"
)
_BALANCE = r"\.? ?New M-PESA balance is Ksh(?P<bal>" + AMOUNT + r")\."
_COST = r" ?Transaction cost, Ksh(?P<fee>" + AMOUNT + r")\."
_AMT = r"Ksh(?P<amt>" + AMOUNT + r")"

_PAYBILL = re.compile(
    _REF + _AMT + r" sent to (?P<who>.+?) for account (?P<acct>.+?)" + _DATE + _BALANCE + _COST
)
_SENT = re.compile(
    _REF + _AMT + r" sent to (?P<who>.+?)(?: (?P<phone>\d{10}))?" + _DATE + _BALANCE + _COST
)
_TILL = re.compile(_REF + _AMT + r" paid to (?P<who>.+?)\.?" + _DATE + _BALANCE + _COST)
_AIRTIME = re.compile(_REF + r"You bought " + _AMT + r" of airtime" + _DATE + _BALANCE + _COST)
_RECEIVED = re.compile(
    _REF + r"You have received " + _AMT + r" from (?P<who>.+?)(?: (?P<phone>[\d*]{9,13}))?"
    + _DATE + _BALANCE
)

_INSUFFICIENT = re.compile(r"^Insufficient funds in your M-PESA account")


def _build(kind: str, m: re.Match, **extra) -> Parsed:
    groups = m.groupdict()
    return Parsed(
        kind=kind,
        provider="mpesa",
        reference=groups["ref"],
        amount_minor=to_minor(groups["amt"]),
        fee_minor=to_minor(groups["fee"]) if groups.get("fee") else 0,
        balance_after_minor=to_minor(groups["bal"]),
        occurred_at=nairobi(
            2000 + int(groups["y"]), int(groups["m"]), int(groups["d"]),
            int(groups["h"]), int(groups["mi"]), meridiem=groups["ap"],
        ),
        **extra,
    )


def parse(text: str, received_at: datetime) -> ParseResult:
    if _INSUFFICIENT.match(text):
        return Ignored("insufficient_funds")
    try:
        # Order matters: a paybill message would also satisfy the looser person pattern.
        if m := _PAYBILL.match(text):
            return _build("mpesa.paybill", m, counterparty=m["who"], counterparty_ref=m["acct"])
        if m := _SENT.match(text):
            phone = mask_phone(m["phone"]) if m["phone"] else None
            return _build("mpesa.sent", m, counterparty=m["who"], counterparty_ref=phone)
        if m := _TILL.match(text):
            return _build("mpesa.till", m, counterparty=m["who"])
        if m := _AIRTIME.match(text):
            return _build("mpesa.airtime", m)
        if m := _RECEIVED.match(text):
            phone = mask_phone(m["phone"]) if m["phone"] else None
            return _build("mpesa.received", m, counterparty=m["who"], counterparty_ref=phone)
    except ValueError:  # an impossible date or amount: refuse to guess
        return Unrecognised("invalid_value")
    return Unrecognised("mpesa_unknown_format")