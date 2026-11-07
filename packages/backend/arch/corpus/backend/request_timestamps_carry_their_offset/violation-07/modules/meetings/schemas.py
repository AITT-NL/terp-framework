from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import field_validator

from terp.core import BaseSchema


class MeetingCreate(BaseSchema):
    starts_at: datetime

    # Runs before the timestamp's type, and before the refusal of a time without its UTC
    # offset: it reads such a time in a zone of its own choosing, unseen.
    @field_validator("starts_at", mode="before")
    @classmethod
    def read_in_amsterdam(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
        return value
