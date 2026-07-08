"""Owner-scoped admin router for files: upload, download, list, rename, delete.

Self-registering (``module``): the kernel's entry-point discovery mounts it at
``/api/v1/files`` with no composition-root edit. File storage is a privileged,
disk/backend-consuming capability, so the policy requires ``ADMIN``; ``File`` also
composes ``OwnedMixin``, so the **per-row** write gate (an admin may rename / delete only
their *own* file) is enforced centrally by ``BaseService`` — the routes carry no ownership
logic. The raw ``storage_key`` never leaves the boundary (``FileRead`` omits it); the
download route **streams** the bytes back through a ``StreamingResponse`` (read from the
backend in chunks, so a large file never lands in memory whole) with a sanitized
``Content-Disposition`` (RFC 5987 encoding, so a hostile stored filename can never inject
response headers). The upload is **streamed** straight from the parsed part's spooled file
into the storage backend, hashing and size-capping the bytes in flight (ADR 0066): the
service refuses the instant the running total crosses ``MAX_UPLOAD_BYTES`` and compensates
the partial blob, so the write path never buffers the whole upload — and the kernel's
``RequestSizeLimitMiddleware`` still bounds the raw request body up front.
"""

from __future__ import annotations

import urllib.parse
import uuid
from collections.abc import Iterator
from typing import BinaryIO, Final

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from terp.core import (
    ADMIN,
    ModuleSpec,
    Page,
    PaginationDep,
    Policy,
    SessionDep,
    ValidationFailedError,
)

from terp.capabilities.files.models import CONTENT_TYPE_MAX, FILENAME_MAX
from terp.capabilities.files.schemas import FileRead, FileUpdate
from terp.capabilities.files.service import FileService

# The default cap on one upload's stored byte size (a DoS guard enforced mid-stream by the
# service, which compensates the partial blob on overrun — the request path never buffers the
# whole upload). Deliberately conservative; a deployment retunes it with one composition-root
# line (configure_upload_limit) paired with create_app(request_size_overrides={"files": ...})
# when the new ceiling exceeds the module's declared request allowance (ADR 0067).
MAX_UPLOAD_BYTES: Final[int] = 25 * 1024 * 1024

# Headroom the module's declared request-body allowance adds over the stored-bytes cap:
# a multipart body carries boundary lines + part headers around the file bytes, so the
# request cap must sit slightly above the stored cap or a maximum-size file would be
# refused at the socket before the streamed cap ever measured it.
_MULTIPART_HEADROOM_BYTES: Final[int] = 64 * 1024

# The active stored-bytes cap (module-level, composition-root-configured — the same seam
# shape as the storage registry). Never client data.
_upload_limit: int = MAX_UPLOAD_BYTES


def configure_upload_limit(max_bytes: int) -> None:
    """Set the stored-bytes cap for uploads (a composition-root line, ADR 0067).

    Validated eagerly (positive) so a mis-wired root fails at boot, not at the first
    upload. A ceiling above the module's declared request allowance
    (``MAX_UPLOAD_BYTES + 64 KiB``) must be paired with
    ``create_app(request_size_overrides={"files": <ceiling + headroom>})`` — otherwise
    the kernel's request-size middleware still refuses the larger body first
    (fail-closed, never silently wider).
    """
    global _upload_limit
    if max_bytes <= 0:
        raise ValueError("the upload limit must be a positive byte count")
    _upload_limit = max_bytes


def active_upload_limit() -> int:
    """The stored-bytes cap uploads are currently held to."""
    return _upload_limit


def reset_upload_limit() -> None:
    """Restore the default cap (the test-isolation reset, like the storage registry's)."""
    global _upload_limit
    _upload_limit = MAX_UPLOAD_BYTES


# The chunk size the download route pulls from the backend stream (bounded memory per read).
_DOWNLOAD_CHUNK_BYTES: Final[int] = 64 * 1024

_DEFAULT_FILENAME: Final[str] = "upload"
_DEFAULT_CONTENT_TYPE: Final[str] = "application/octet-stream"


def _iter_blob(stream: BinaryIO) -> Iterator[bytes]:
    """Yield a backend blob stream in fixed-size chunks, closing it when exhausted.

    Feeds ``StreamingResponse`` so a download never materializes the whole file in memory;
    the ``finally`` guarantees the backend handle is released even if the client disconnects
    mid-stream.
    """
    try:
        while chunk := stream.read(_DOWNLOAD_CHUNK_BYTES):
            yield chunk
    finally:
        stream.close()


router = APIRouter(tags=["files"])
_service = FileService()


def _content_disposition(filename: str) -> str:
    """A header-safe attachment disposition for *filename* (RFC 5987 / RFC 6266).

    The stored filename is caller-supplied, so it is never emitted raw: the primary
    ``filename*`` value is fully percent-encoded (no CR/LF/quote can survive), and the
    ASCII ``filename`` fallback keeps only a conservative character set.
    """
    fallback = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "._-") else "_" for ch in filename
    )
    encoded = urllib.parse.quote(filename, safe="")
    return f'attachment; filename="{fallback or _DEFAULT_FILENAME}"; filename*=UTF-8\'\'{encoded}'


@router.post("/", response_model=FileRead, status_code=201)
async def upload_file(request: Request, session: SessionDep) -> FileRead:
    form = await request.form(max_files=1, max_fields=0, max_part_size=1024)
    uploaded = form.get("file")
    if not isinstance(uploaded, UploadFile):
        raise ValidationFailedError("Upload a file part named 'file'.")
    file = uploaded
    filename = file.filename or _DEFAULT_FILENAME
    if len(filename) > FILENAME_MAX:
        raise ValidationFailedError(
            f"The filename exceeds the {FILENAME_MAX}-character limit."
        )
    content_type = file.content_type or _DEFAULT_CONTENT_TYPE
    if len(content_type) > CONTENT_TYPE_MAX:
        raise ValidationFailedError(
            f"The content type exceeds the {CONTENT_TYPE_MAX}-character limit."
        )
    # Stream the parsed part's spooled file straight into the backend: the service hashes
    # and size-caps the bytes in flight (refusing + compensating past the active limit), so
    # the write path never holds the whole upload in memory. A sync handler runs in the
    # threadpool, so the blocking copy never stalls the event loop.
    file.file.seek(0)
    return FileRead.model_validate(
        _service.store(
            session,
            filename=filename,
            content_type=content_type,
            source=file.file,
            max_bytes=active_upload_limit(),
        )
    )


@router.get("/", response_model=Page[FileRead])
def list_files(session: SessionDep, pagination: PaginationDep) -> Page[FileRead]:
    rows, total = _service.list(session, skip=pagination.skip, limit=pagination.limit)
    return Page[FileRead].of(
        [FileRead.model_validate(row) for row in rows], total, pagination
    )


@router.get("/{file_id}", response_model=FileRead)
def get_file(file_id: uuid.UUID, session: SessionDep) -> FileRead:
    return FileRead.model_validate(_service.get(session, file_id))


@router.get("/{file_id}/content")  # arch-allow-routes-declare-response-model: binary download — the bytes stream out through a StreamingResponse (stored media type + sanitized attachment disposition), never a serialized ORM object
def download_file(file_id: uuid.UUID, session: SessionDep) -> StreamingResponse:
    row, stream = _service.open_stream(session, file_id)
    return StreamingResponse(
        _iter_blob(stream),
        media_type=row.content_type,
        headers={
            "Content-Disposition": _content_disposition(row.filename),
            # The stored size is append-only and derived from the streamed bytes at create
            # time, so it is authoritative: declaring it keeps download progress / resume
            # working, and a blob truncated out-of-band surfaces as a protocol error
            # instead of a silently short body.
            "Content-Length": str(row.size),
        },
    )


@router.patch("/{file_id}", response_model=FileRead)
def update_file(
    file_id: uuid.UUID, payload: FileUpdate, session: SessionDep
) -> FileRead:
    return FileRead.model_validate(_service.update(session, file_id, payload))


@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: uuid.UUID, session: SessionDep) -> None:
    _service.remove(session, file_id)


module = ModuleSpec(
    name="files",
    router=router,
    policy=Policy(read=ADMIN, write=ADMIN),
    # The declared request-body allowance for /api/v1/files (ADR 0067): the default
    # stored-bytes cap plus multipart framing headroom, so a maximum-size upload fits
    # through the kernel's request-size middleware without widening the global cap.
    max_request_bytes=MAX_UPLOAD_BYTES + _MULTIPART_HEADROOM_BYTES,
)


__all__ = [
    "MAX_UPLOAD_BYTES",
    "active_upload_limit",
    "configure_upload_limit",
    "module",
    "reset_upload_limit",
    "router",
]
