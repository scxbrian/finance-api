"""Ziidi (Safaricom money market fund, sender ZIIDI). Messages carry no date: the arrival time is used."""

import re
from datetime import datetime

from app.core.clock import NAIROBI
from app.parsers.common import AMOUNT, to_minor
from app.parsers.types import Parsed, ParseResult, Unrecognised

_PATTERN = re.compile(
    r"^You have successfully (?P<verb>invested|withdrawn) Ksh\. ?(?P<amt>" + AMOUNT + r")"
    r" of transaction code (?P<ref>[A-Z0-9]{10})\."
    r" Your ZIIDI balance is Ksh\. ?(?P<bal>" + AMOUNT + r")\.?$"
)


def parse(text: str, received_at: datetime) -> ParseResult:
    m = _PATTERN.match(text)
    if not m:
        return Unrecognised("ziidi_unknown_format")
    try:
        return Parsed(
            kind=f"ziidi.{m['verb']}",
            provider="ziidi",
            reference=m["ref"],
            amount_minor=to_minor(m["amt"]),
            balance_after_minor=to_minor(m["bal"]),
            occurred_at=received_at.astimezone(NAIROBI),
            date_from_message=False,
        )
    except ValueError:
        return Unrecognised("invalid_value")