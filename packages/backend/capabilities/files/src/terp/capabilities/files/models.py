"""The ``file_object`` metadata table: an owner-scoped file record.

``File`` is a normal owner-scoped resource (``BaseTable`` + ``OwnedMixin``): its creator
owns it and only the owner may edit / delete it — the per-row write gate (ADR 0029),
enforced centrally by ``BaseService`` with zero module code (never a hand-rolled
``owner_id`` check — ``terp guide ownership``). Only the *metadata* lives here; the bytes
live behind the pluggable :class:`~terp.capabilities.files.StorageBackend`, addressed by
the server-generated ``storage_key``.

Mutability is decided per field:

* ``filename`` — **mutable** (a rename is a metadata edit; the bytes are untouched), via
  the OCC-bearing ``update`` path.
* ``content_type`` / ``size`` / ``sha256`` / ``storage_key`` / ``storage_profile`` —
  **append-only**: set once from the uploaded bytes at create time and never patched
  (``FileUpdate`` carries no field for them; replacing content is a new upload).
  ``storage_key`` and ``storage_profile`` in particular are server-side-only material
  (the raw storage address and the named backend holding it): both are generated /
  selected by the service, never accepted from a client, and never serialized out of the
  API boundary (no ``*Read`` DTO carries them — enforced by a runtime test alongside the
  ``schemas_exclude_sensitive_fields`` posture). ``storage_profile`` being append-only is
  what keeps a row pointing at the store that actually holds its bytes: re-homing a blob
  is an explicit migration, never a patch.

Every caller-influenceable ``str`` column caps its length so a hostile or oversized value
can never break the INSERT.
"""

from __future__ import annotations

from typing import Final

from sqlmodel import Field

from terp.core import BaseTable, OwnedMixin

from terp.capabilities.files.storage import STORAGE_PROFILE_MAX

# Hard caps so a hostile / oversized value can never break the INSERT.
FILENAME_MAX: Final[int] = 255
CONTENT_TYPE_MAX: Final[int] = 255
_SHA256_MAX: Final[int] = 64
_STORAGE_KEY_MAX: Final[int] = 512


class File(BaseTable, OwnedMixin, table=True):
    """One stored file's metadata: name, type, size, digest, and its storage address.

    ``id`` / ``created_at`` / ``updated_at`` / ``version`` are inherited from ``BaseTable``;
    ``owner_id`` from ``OwnedMixin`` (stamped from the request actor on create, then enforced
    as the per-row write gate). ``storage_key`` addresses the bytes inside the storage
    backend registered under ``storage_profile`` (ADR 0057); neither is **ever**
    serialized in a Read DTO.
    """

    __tablename__ = "file_object"

    filename: str = Field(max_length=FILENAME_MAX, index=True)
    content_type: str = Field(max_length=CONTENT_TYPE_MAX)
    size: int = Field(ge=0)
    sha256: str = Field(max_length=_SHA256_MAX)
    storage_key: str = Field(max_length=_STORAGE_KEY_MAX, unique=True)
    storage_profile: str = Field(max_length=STORAGE_PROFILE_MAX)


__all__ = ["CONTENT_TYPE_MAX", "FILENAME_MAX", "File"]
