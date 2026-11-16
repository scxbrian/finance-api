import pytest

from app.parsers.tariff import expected_send_money_fee_minor as fee


@pytest.mark.parametrize(
    ("kes", "expected_kes"),
    [(1, 0), (50, 0), (100, 0), (101, 7), (500, 7), (501, 13), (1000, 13), (1001, 23),
     (1500, 23), (1501, 33), (2500, 33), (2501, 53), (3500, 53), (3501, 57), (5000, 57),
     (5001, 78), (7500, 78), (7501, 90), (10000, 90), (10001, 100), (15000, 100)],
)
def test_bands_every_source_agrees_on(kes, expected_kes):
    assert fee(kes * 100) == expected_kes * 100


def test_above_the_per_transaction_limit_there_is_no_fee_to_predict():
    assert fee(250_000 * 100) == 108 * 100
    assert fee(250_001 * 100) is None


def test_every_fee_in_the_real_samples_is_the_free_band():
    # The real messages all sent Ksh100 or less, and all report Ksh0.00 cost.
    for kes in (50, 80, 90, 100):
        assert fee(kes * 100) == 0