"""``notices`` DTOs — compose the kernel schema bases; cap every input string."""

from __future__ import annotations

import datetime
import uuid

from pydantic import field_validator
from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema

from terp.capabilities.mail.settings import breaks_a_header, parse_address


class NoticeCreate(BaseSchema):
    """A notice is mailed as it is written, so it is refused here if it could not be.

    The title becomes the mail's subject and the recipient its one address. Checking both
    with the mail capability's own parsers turns a notice that could never be sent into a
    422 for the caller, instead of a job that dead-letters after the write committed.
    """

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    recipient: str = Field(max_length=254)

    @field_validator("title")
    @classmethod
    def _title_is_one_line(cls, value: str) -> str:
        if breaks_a_header(value):
            raise ValueError("the title is one line of text: it becomes the mail's subject")
        return value

    @field_validator("recipient")
    @classmethod
    def _recipient_is_one_address(cls, value: str) -> str:
        parse_address(value)
        return value


class NoticeUpdate(BaseUpdateSchema):
    """No route edits a notice; the service still needs an update type to be generic over."""

    body: str | None = Field(default=None, max_length=4000)
    # `version: int` is inherited and required (optimistic concurrency).


class NoticeRead(BaseSchema):
    id: uuid.UUID
    title: str
    body: str
    recipient: str
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class SnapshotCreate(BaseSchema):
    """Written by the snapshot job only — no route accepts one."""

    url: str = Field(max_length=2048)
    status_code: int = Field(ge=100, le=599)
    size: int = Field(ge=0)
    file_id: uuid.UUID | None = None


class SnapshotUpdate(BaseUpdateSchema):
    """Never applied: the snapshot service is append-only and refuses every update."""


class SnapshotRequested(BaseSchema):
    """The job that will take the snapshot; the worker runs it, the list shows the result."""

    job_id: str = Field(max_length=64)


class SnapshotRead(BaseSchema):
    id: uuid.UUID
    url: str
    status_code: int
    size: int
    file_id: uuid.UUID | None
    created_at: datetime.datetime
