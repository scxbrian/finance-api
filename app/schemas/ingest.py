from datetime import UTC, datetime, timedelta

from pydantic import AwareDatetime, BaseModel, Field, field_validator


class SmsIn(BaseModel):
    """One SMS as the phone's forwarder reports it."""

    sender: str = Field(min_length=1, max_length=64)
    body: str = Field(min_length=1, max_length=5000)
    received_at: AwareDatetime  # when it ARRIVED on the phone; the timezone is mandatory

    @field_validator("received_at")
    @classmethod
    def not_far_in_the_future(cls, value: datetime) -> datetime:
        # A phone with a wrong clock would file transactions under the wrong day.
        if value > datetime.now(UTC) + timedelta(days=1):
            raise ValueError("received_at is in the future; check the phone's clock.")
        return value