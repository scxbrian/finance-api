"""Which days a month view covers, and which days it is compared against.

A half-finished month must not be compared with a whole one: on the 15th, "spent 31,000 vs
36,800 last month" would look like good news only because half of this month has not happened
yet. So for the CURRENT month the comparison covers the same number of days at the start of
the previous month.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

MONTH_PATTERN = r"^20\d{2}-(0[1-9]|1[0-2])$"  # 2000-01 .. 2099-12
_MONTH = re.compile(MONTH_PATTERN)


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive

    def as_json(self) -> dict[str, str]:
        return {"from": self.start.isoformat(), "to": self.end.isoformat()}


def parse_month(month: str) -> tuple[int, int]:
    if not _MONTH.match(month):
        raise ValueError(f"not a month in YYYY-MM form: {month!r}")
    return int(month[:4]), int(month[5:])


def whole_month(year: int, month: int) -> Period:
    return Period(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))


def periods_for(month: str, today: date) -> tuple[Period, Period]:
    """(the period to summarise, the period to compare it with)."""
    year, mon = parse_month(month)
    this = whole_month(year, mon)
    previous = whole_month(year - 1, 12) if mon == 1 else whole_month(year, mon - 1)

    if (year, mon) == (today.year, today.month):
        same_days_end = min(previous.start + timedelta(days=today.day - 1), previous.end)
        return Period(this.start, today), Period(previous.start, same_days_end)
    return this, previous  # a finished month (or a future one) is compared as a whole