from datetime import datetime

from fastapi import APIRouter, Depends

from terp.core import Page, PaginationDep, SessionDep

from .schemas import ReadingRead
from .service import ReadingService, get_service

router = APIRouter()


@router.get("/", response_model=Page[ReadingRead])
def list_readings(
    pagination: PaginationDep,
    session: SessionDep,
    taken_after: datetime | None = None,
    service: ReadingService = Depends(get_service),
) -> Page[ReadingRead]:
    # A timestamp filter forwarded to the service's declared filter: a bound without an
    # offset is refused there, naming the filter.
    rows, total = service.list(
        session,
        skip=pagination.skip,
        limit=pagination.limit,
        filters={"taken_after": taken_after},
    )
    return Page(items=rows, total=total, skip=pagination.skip, limit=pagination.limit)
