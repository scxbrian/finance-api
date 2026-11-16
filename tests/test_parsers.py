from datetime import UTC, datetime

import pytest

from app.parsers import Ignored, Parsed, Unrecognised, parse_message
from sms_fixtures import Case, load_cases

CASES = load_cases()


def test_fixtures_were_found():
    # Guards against a silently empty suite if the loader or the folder breaks.
    assert len(CASES) >= 30


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_message(case: Case):
    result = parse_message(case.sender, case.body, case.received)
    expect = dict(case.expect)
    outcome = expect.pop("result", "parsed")

    if outcome == "ignored":
        assert isinstance(result, Ignored), result
        assert result.reason == expect.pop("reason")
        assert result.store_raw == expect.pop("store_raw", True)
    elif outcome == "unrecognised":
        assert isinstance(result, Unrecognised), result
        assert result.reason == expect.pop("reason")
    else:
        assert isinstance(result, Parsed), result
        for field, wanted in expect.items():
            actual = getattr(result, field)
            if field == "occurred_at":
                actual = actual.isoformat()
            assert actual == wanted, f"{field}: expected {wanted!r}, got {actual!r}"


def test_unknown_sender_is_never_interpreted():
    body = "UKF8X24QSV Confirmed. Ksh50.00 sent to JOHN DOE on 15/11/26 at 12:24 PM."
    result = parse_message("RANDOM-SENDER", body, datetime(2026, 11, 15, tzinfo=UTC))
    assert result == Unrecognised("unknown_sender")


@pytest.mark.parametrize("sender", ["MPESA", "mpesa", "M-PESA", " Mpesa "])
def test_sender_spelling_is_forgiving(sender):
    result = parse_message(
        sender, "Insufficient funds in your M-PESA account for this transaction",
        datetime(2026, 11, 15, tzinfo=UTC),
    )
    assert result == Ignored("insufficient_funds")


def test_naive_received_time_is_rejected():
    with pytest.raises(ValueError):
        parse_message("MPESA", "anything", datetime(2026, 11, 15))


@pytest.mark.parametrize(
    "body",
    [
        "Please use 123456 as your login code. It expires in 15 minutes.",
        "Your verification code is 482913",
        "Use OTP 5521 to confirm this payment",
    ],
)
def test_one_time_codes_are_dropped_whichever_sender_claims_them(body):
    result = parse_message("ETICALTD", body, datetime(2026, 1, 1, tzinfo=UTC))
    assert result == Ignored("otp", store_raw=False)


def _providers_by_reference() -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for case in CASES:
        result = parse_message(case.sender, case.body, case.received)
        if isinstance(result, Parsed) and result.reference:
            seen.setdefault(result.reference, []).append(result.provider)
    return seen


@pytest.mark.parametrize("code", ["UKF8X24CHK", "UKD8X1XC7P"])
def test_a_ziidi_withdrawal_and_its_mpesa_credit_share_one_reference(code):
    """One real event, two senders: the code is what lets them be merged into one transaction."""
    assert sorted(_providers_by_reference()[code]) == ["mpesa", "ziidi"]


def test_the_stages_of_a_coop_deposit_share_one_reference():
    assert _providers_by_reference()["UCV8XB2LT8"] == ["coop", "coop"]