from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BeforeValidator

from terp.core import Instant

router = APIRouter()


def _in_amsterdam(value: object) -> object:
    if isinstance(value, str):
        return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
    return value


@router.get("/", response_model=dict[str, str])
def list_meetings(
    # Instant refuses text without an offset, but this validator reads the text first and
    # hands it an instant read in a zone of its own choosing.
    since: Annotated[Instant, BeforeValidator(_in_amsterdam)] | None = None,
) -> dict[str, str]:
    return {}
