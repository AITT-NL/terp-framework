from datetime import datetime
from typing import Annotated

from fastapi import APIRouter
from pydantic import AfterValidator, BaseModel

from terp.core import Instant

router = APIRouter()


def _on_the_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


class ImportedMeeting(BaseModel):
    # A class that reads its own fields holds a timestamp to its offset through its type.
    starts_at: Instant
    # An after validator sees the instant Instant made, so it reads no text.
    ends_at: Annotated[Instant, AfterValidator(_on_the_hour)]


@router.get("/", response_model=dict[str, str])
def list_meetings(since: Instant | None = None) -> dict[str, str]:
    # A route parameter is no field of a schema: Instant puts the refusal in front of it.
    return {}
