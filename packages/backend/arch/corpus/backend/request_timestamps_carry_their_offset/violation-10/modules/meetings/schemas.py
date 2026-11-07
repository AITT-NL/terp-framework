from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, field_validator

from terp.core import Instant


class ImportedMeeting(BaseModel):
    starts_at: Instant

    # The same escape as a field validator: it reads the text before Instant does.
    @field_validator("starts_at", mode="before")
    @classmethod
    def in_amsterdam(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
        return value
