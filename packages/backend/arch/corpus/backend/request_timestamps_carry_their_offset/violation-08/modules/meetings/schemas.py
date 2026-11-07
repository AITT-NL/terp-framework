from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BeforeValidator

from terp.core import BaseSchema


def _in_amsterdam(value: object) -> object:
    if isinstance(value, str):
        return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
    return value


class MeetingCreate(BaseSchema):
    # The same escape spelled as the type's metadata: it sees the text first.
    starts_at: Annotated[datetime, BeforeValidator(_in_amsterdam)]
