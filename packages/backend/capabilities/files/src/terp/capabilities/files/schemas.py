"""File DTOs.

``FileCreate`` is **server-built only**: the upload route parses the multipart body,
derives ``size`` / ``sha256`` from the received bytes and generates ``storage_key`` /
selects ``storage_profile`` server-side, then constructs this schema itself — a client
never posts it as JSON, so neither the storage address nor the store it names is ever
client-influenceable. ``FileUpdate`` allows only the mutable metadata (``filename``);
the content-derived fields are append-only (see ``models``).

``FileRead`` deliberately **omits** ``storage_key`` and ``storage_profile``: the raw
storage address and the named backend holding it are server-side material and never
leave the API boundary (the ``schemas_exclude_sensitive_fields`` posture, plus a runtime
test asserting the omission).
"""

from __future__ import annotations

import datetime
import uuid

from sqlmodel import Field

from terp.core import BaseSchema, BaseUpdateSchema

# Mirror the model caps so an oversized value is rejected at the boundary (a DoS cap).
_FILENAME_MAX = 255
_CONTENT_TYPE_MAX = 255
_SHA256_MAX = 64
_STORAGE_KEY_MAX = 512
_STORAGE_PROFILE_MAX = 64


class FileCreate(BaseSchema):
    """The metadata row for one uploaded file — constructed by the service, never a client."""

    filename: str = Field(min_length=1, max_length=_FILENAME_MAX)
    content_type: str = Field(min_length=1, max_length=_CONTENT_TYPE_MAX)
    size: int = Field(ge=0)
    sha256: str = Field(max_length=_SHA256_MAX)
    storage_key: str = Field(max_length=_STORAGE_KEY_MAX)
    storage_profile: str = Field(min_length=1, max_length=_STORAGE_PROFILE_MAX)


class FileUpdate(BaseUpdateSchema):
    """Patch a file's mutable metadata (OCC via the inherited required ``version``).

    Only ``filename`` is patchable; the content-derived fields (``content_type`` /
    ``size`` / ``sha256`` / ``storage_key``) are append-only — replacing content is a new
    upload, never an edit.
    """

    filename: str | None = Field(default=None, min_length=1, max_length=_FILENAME_MAX)
    # `version: int` is inherited from BaseUpdateSchema and required (optimistic concurrency).


class FileRead(BaseSchema):
    """The file metadata as returned by the API — **without** ``storage_key`` / ``storage_profile``."""

    id: uuid.UUID
    filename: str
    content_type: str
    size: int
    sha256: str
    owner_id: uuid.UUID | None
    version: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


__all__ = ["FileCreate", "FileRead", "FileUpdate"]
