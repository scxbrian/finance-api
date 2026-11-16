"""Co-operative Bank (sender CoopBank).

This sender uses a different date format in almost every message type, so each pattern
below carries its own explicit format. None of them is ever inferred.
"""

import re
from datetime import datetime

from app.core.clock import NAIROBI
from app.parsers.common import (
    AMOUNT, mask_phone, month_number, nairobi, to_minor, trailing_digits,
)
from app.parsers.types import Ignored, Parsed, ParseResult, Unrecognised

# --- messages that have no ledger effect -------------------------------------------------
_DECLINED = re.compile(r"was declined\.")
_FAILED = re.compile(r"^Transaction FAILED\.")
_REQUEST = re.compile(r"your request to pay KES " + AMOUNT + r" to \S+ on .+? has been received")
_MARKETING = re.compile(r"do not qualify for this product")

# --- card purchase: "31-MAR-2026 10:23:12", 24-hour ---------------------------------------
_CARD = re.compile(
    r"(?:^|\. )Dear [^,]+, Card PAYMENT transaction dated"
    r" (?P<d>\d{2})-(?P<mon>[A-Z]{3})-(?P<y>\d{4}) (?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})"
    r" of (?P<cur>[A-Z]{3}) (?P<amt>" + AMOUNT + r") (?P<merchant>.+?) Was Successful\."
)

# --- M-Pesa -> own Co-op account (one deposit produces two or three messages) -------------
# "you have sent": month-FIRST date, "03/31/2026 at 10:18:04"
_DEPOSIT_SENT = re.compile(
    r"^Dear [^,]+, you have sent Ksh\. (?P<amt>" + AMOUNT + r") to (?P<who>.+?)"
    r" (?P<acct>[\d*]{8,}) on (?P<m>\d{2})/(?P<d>\d{2})/(?P<y>\d{4})"
    r" at (?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})\. MPESA Ref\. (?P<ref>[A-Z0-9]{10})\."
)
# completion notice: no date in the message
_DEPOSIT_OK = re.compile(
    r"^Ref: ?(?P<cref>[A-Z0-9]+)\. Dear [^,]+, your M-PESA to Account Deposit of KES"
    r" (?P<amt>" + AMOUNT + r") to account (?P<acct>\d+) was successful\."
    r" M-PESA Ref: (?P<ref>[A-Z0-9]{10})\.$"
)

# --- till payment made from the bank account through MCoopCash ----------------------------
_TILL = re.compile(
    r"Ref: ?(?P<cref>[A-Z0-9]+): Dear [^,]+, MPESA Till payment of KES (?P<amt>" + AMOUNT + r")"
    r" to (?P<who>.+?)-(?P<till>\d+) was successful\. ?MPESA Ref: ?(?P<ref>[A-Z0-9]{10})\."
)

# --- Co-op telling you about money that arrived in your M-Pesa; day-month-year, 12-hour ----
_MPESA_NOTICE = re.compile(
    r"Ref: ?(?P<cref>[A-Z0-9]+): Dear [^,]+, You have received KES (?P<amt>" + AMOUNT + r")"
    r" on your M-Pesa from (?P<who>.+?)-(?P<phone>\d{12})"
    r" at (?P<d>\d{2})-(?P<m>\d{2})-(?P<y>\d{4}) (?P<h>\d{1,2}):(?P<mi>\d{2}) (?P<ap>AM|PM)\."
    r" ?The M-Pesa receipt number is: ?(?P<ref>[A-Z0-9]{10})\."
)


def parse(text: str, received_at: datetime) -> ParseResult:
    arrival = received_at.astimezone(NAIROBI)

    if _DECLINED.search(text):
        return Ignored("declined")
    if _FAILED.match(text):
        return Ignored("failed")
    if _REQUEST.search(text):
        return Ignored("request_acknowledged")  # the success message that follows is the event
    if _MARKETING.search(text):
        return Ignored("marketing")

    try:
        if m := _CARD.search(text):
            amount = to_minor(m["amt"])
            if amount == 0:
                return Ignored("zero_amount")  # card verification, e.g. "USD 0 GOOGLE"
            return Parsed(
                kind="coop.card_purchase", provider="coop", amount_minor=amount,
                currency=m["cur"], counterparty=m["merchant"],
                occurred_at=nairobi(
                    int(m["y"]), month_number(m["mon"]), int(m["d"]),
                    int(m["h"]), int(m["mi"]), int(m["s"]),
                ),
            )
        if m := _DEPOSIT_SENT.match(text):
            return Parsed(
                kind="coop.deposit_from_mpesa", provider="coop", reference=m["ref"],
                amount_minor=to_minor(m["amt"]), counterparty=m["who"],
                account_suffix=trailing_digits(m["acct"]),
                occurred_at=nairobi(
                    int(m["y"]), int(m["m"]), int(m["d"]), int(m["h"]), int(m["mi"]), int(m["s"])
                ),
            )
        if m := _DEPOSIT_OK.match(text):
            return Parsed(
                kind="coop.deposit_from_mpesa", provider="coop", reference=m["ref"],
                amount_minor=to_minor(m["amt"]), account_suffix=trailing_digits(m["acct"]),
                occurred_at=arrival, date_from_message=False,
            )
        if m := _TILL.search(text):
            return Parsed(
                kind="coop.till_payment", provider="coop", reference=m["ref"],
                amount_minor=to_minor(m["amt"]), counterparty=m["who"],
                counterparty_ref=m["till"], occurred_at=arrival, date_from_message=False,
            )
        if m := _MPESA_NOTICE.search(text):
            return Parsed(
                kind="coop.mpesa_received_notice", provider="coop", reference=m["ref"],
                amount_minor=to_minor(m["amt"]), counterparty=m["who"],
                counterparty_ref=mask_phone(m["phone"]),
                occurred_at=nairobi(
                    int(m["y"]), int(m["m"]), int(m["d"]), int(m["h"]), int(m["mi"]),
                    meridiem=m["ap"],
                ),
            )
    except (ValueError, KeyError):  # impossible date, unknown month name: refuse to guess
        return Unrecognised("invalid_value")
    return Unrecognised("coop_unknown_format")