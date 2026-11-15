from datetime import UTC, date, datetime

from app.core.clock import today_nairobi


def test_after_midnight_in_nairobi_is_the_next_day():
    # 22:30 UTC on the 14th is 01:30 on the 15th in Nairobi (UTC+3).
    assert today_nairobi(datetime(2026, 11, 14, 22, 30, tzinfo=UTC)) == date(2026, 11, 15)


def test_daytime_is_the_same_day():
    assert today_nairobi(datetime(2026, 11, 14, 9, 0, tzinfo=UTC)) == date(2026, 11, 14)


def test_the_boundary_is_21_00_utc():
    assert today_nairobi(datetime(2026, 11, 14, 20, 59, tzinfo=UTC)) == date(2026, 11, 14)
    assert today_nairobi(datetime(2026, 11, 14, 21, 0, tzinfo=UTC)) == date(2026, 11, 15)