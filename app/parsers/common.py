"""Helpers shared by every provider's parser."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.core.clock import NAIROBI

AMOUNT = r"\d[\d,]*(?:\.\d+)?"  # 1,000.00 | 192490.0 | 100

_WHITESPACE = re.compile(r"\s+")
_MONTHS = {
    name: number
    for number, name in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1
    )
}
# Messages that carry a one-time code. They are discarded unseen, never stored.
_OTP = re.compile(r"^<#>|login code|verification code|one[- ]time (?:pin|password|code)|\botp\b", re.I)


def normalise(body: str) -> str:
    """Collapse every run of whitespace (including line breaks) to one space."""
    return _WHITESPACE.sub(" ", body).strip()


def looks_like_otp(text: str) -> bool:
    return bool(_OTP.search(text))


def to_minor(text: str) -> int:
    """'1,000.00' -> 100000. Exact: goes through Decimal, never a float."""
    try:
        value = Decimal(text.replace(",", "").strip()) * 100
    except InvalidOperation:
        raise ValueError(f"not an amount: {text!r}") from None
    if value != value.to_integral_value():
        raise ValueError(f"more than two decimal places: {text!r}")
    return int(value)


def month_number(abbreviation: str) -> int:
    return _MONTHS[abbreviation.upper()]


def nairobi(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0,
    meridiem: str | None = None,
) -> datetime:
    """Build an aware Nairobi datetime. Pass meridiem ('AM'/'PM') for 12-hour clocks."""
    if meridiem:
        hour = hour % 12 + (12 if meridiem.upper() == "PM" else 0)
    return datetime(year, month, day, hour, minute, second, tzinfo=NAIROBI)


def mask_phone(phone: str) -> str:
    """0712345678 -> 0712***678. Already-masked numbers pass through unchanged."""
    if "*" in phone:
        return phone
    return f"{phone[:4]}***{phone[-3:]}"


def trailing_digits(account: str) -> str | None:
    """Last up-to-4 digits of an account number: '01101******001' -> '001'."""
    match = re.search(r"\d+$", account)
    return match.group()[-4:] if match else None