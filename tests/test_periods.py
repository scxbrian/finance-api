from datetime import date

import pytest

from app.services.periods import Period, parse_month, periods_for


def test_the_current_month_runs_to_today_and_is_compared_over_the_same_days():
    current, previous = periods_for("2026-11", today=date(2026, 11, 15))
    assert current == Period(date(2026, 11, 1), date(2026, 11, 15))
    assert previous == Period(date(2026, 10, 1), date(2026, 10, 15))


def test_the_comparison_is_clamped_to_a_shorter_previous_month():
    current, previous = periods_for("2026-03", today=date(2026, 3, 31))
    assert current == Period(date(2026, 3, 1), date(2026, 3, 31))
    assert previous == Period(date(2026, 2, 1), date(2026, 2, 28))  # not Feb 31


def test_a_leap_february_is_respected():
    _, previous = periods_for("2028-03", today=date(2028, 3, 31))
    assert previous.end == date(2028, 2, 29)


def test_january_compares_with_the_previous_december():
    current, previous = periods_for("2027-01", today=date(2027, 1, 10))
    assert previous == Period(date(2026, 12, 1), date(2026, 12, 10))
    assert current.start == date(2027, 1, 1)


def test_a_finished_month_is_compared_as_a_whole():
    current, previous = periods_for("2026-10", today=date(2026, 11, 15))
    assert current == Period(date(2026, 10, 1), date(2026, 10, 31))
    assert previous == Period(date(2026, 9, 1), date(2026, 9, 30))


def test_a_future_month_is_a_whole_month_too():
    current, _ = periods_for("2026-12", today=date(2026, 11, 15))
    assert current == Period(date(2026, 12, 1), date(2026, 12, 31))


def test_the_json_shape_matches_the_contract():
    assert Period(date(2026, 11, 1), date(2026, 11, 15)).as_json() == {"from": "2026-11-01", "to": "2026-11-15"}


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "2026-1", "26-11", "1999-12", "2026-11-01", "", "abcd-ef"])
def test_bad_months_are_refused(bad):
    with pytest.raises(ValueError):
        parse_month(bad)