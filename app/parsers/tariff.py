"""M-Pesa send-money tariff, used ONLY as a sanity check.

The fee that goes in the ledger is always the "Transaction cost" printed in the SMS.
This table exists to notice when that number looks odd. It covers person-to-person
send money; paybill, till, withdrawal and promotional tariffs are different and are
not modelled. Safaricom changes tariffs, so a mismatch means "look at this", not "error".
"""

from app.parsers.types import Parsed

# (highest amount in KES that the band covers, fee in KES). Up to 10,000 every 2026
# source agrees; the top bands (105 up to 20,000, 108 above) came from fewer sources.
SEND_MONEY_BANDS: tuple[tuple[int, int], ...] = (
    (100, 0),
    (500, 7),
    (1_000, 13),
    (1_500, 23),
    (2_500, 33),
    (3_500, 53),
    (5_000, 57),
    (7_500, 78),
    (10_000, 90),
    (15_000, 100),
    (20_000, 105),
    (250_000, 108),
)


def expected_send_money_fee_minor(amount_minor: int) -> int | None:
    """The tariff fee for sending this amount, in cents; None above the per-transaction limit."""
    for upper_kes, fee_kes in SEND_MONEY_BANDS:
        if amount_minor <= upper_kes * 100:
            return fee_kes * 100
    return None


def fee_matches_tariff(parsed: Parsed) -> bool | None:
    """True/False for a send-money message; None when the tariff does not apply."""
    if parsed.kind != "mpesa.sent":
        return None
    expected = expected_send_money_fee_minor(parsed.amount_minor)
    if expected is None:
        return None
    return parsed.fee_minor == expected