"""Turns one SMS into a Parsed, Ignored or Unrecognised result. Pure functions: no database."""

import re
from datetime import datetime

from app.parsers import coop, etica, mpesa, ziidi
from app.parsers.common import looks_like_otp, normalise
from app.parsers.types import Ignored, Parsed, ParseResult, Unrecognised

__all__ = ["Ignored", "Parsed", "ParseResult", "Unrecognised", "parse_message"]

# The allow-list. Only these senders are ever interpreted; anything else is Unrecognised.
_PROVIDERS = {
    "mpesa": mpesa.parse,
    "ziidi": ziidi.parse,
    "eticaltd": etica.parse,
    "coopbank": coop.parse,
}


def parse_message(sender: str, body: str, received_at: datetime) -> ParseResult:
    """`received_at` is the moment the SMS arrived on the phone, with a timezone."""
    if received_at.tzinfo is None:
        raise ValueError("received_at must be timezone-aware")

    text = normalise(body)

    # First, before any provider logic: one-time codes are secrets and are never kept.
    if looks_like_otp(text):
        return Ignored("otp", store_raw=False)

    parser = _PROVIDERS.get(re.sub(r"[^a-z0-9]", "", sender.lower()))
    if parser is None:
        return Unrecognised("unknown_sender")
    return parser(text, received_at)