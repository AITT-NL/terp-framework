from datetime import datetime
from typing import Annotated

from pydantic import BeforeValidator, field_validator

from terp.core import BaseSchema, LocalTimeIn


class MeetingCreate(BaseSchema):
    # The wall time of a named zone names its instant: the type reads it in that zone and
    # refuses a time the clocks skip or repeat there.
    starts_at: Annotated[datetime, LocalTimeIn("Europe/Amsterdam")]
    ends_at: datetime
    title: Annotated[str, BeforeValidator(str.strip)]

    # An after validator sees the instant the type made, so it reads no text.
    @field_validator("ends_at")
    @classmethod
    def ends_on_the_hour(cls, value: datetime) -> datetime:
        return value.replace(minute=0, second=0, microsecond=0)
