"""Time helpers. The business day is Africa/Nairobi, never UTC.

Between 00:00 and 03:00 East Africa Time the UTC date is still "yesterday", so
computing "today" in UTC would file those transactions under the wrong day.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

NAIROBI = ZoneInfo("Africa/Nairobi")


def today_nairobi(now: datetime | None = None) -> date:
    moment = now or datetime.now(UTC)
    return moment.astimezone(NAIROBI).date()