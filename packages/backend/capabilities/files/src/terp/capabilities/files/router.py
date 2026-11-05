"""The files router: upload, download, list, rename, delete, and a link to a file's bytes.

Self-registering (``module``): the kernel's entry-point discovery mounts it at
``/api/v1/files`` with no composition-root edit. File storage is a privileged,
disk/backend-consuming capability, so the policy requires ``ADMIN``; ``File`` also
composes ``OwnedMixin``, so the **per-row** write gate (an admin may rename / delete only
their *own* file) is enforced centrally by ``BaseService`` — the routes carry no ownership
logic. One route steps outside that policy on purpose and says so on its own line
(ADR 0148): ``GET /link/{token}`` serves the bytes an **app-signed link** names, to a
client that cannot send a bearer, for as long as the sealed token lives (ADR 0201). It is
rate-limited on its own, answers a token it cannot open with a 404 that says nothing about
why, and re-checks the scan verdict before it streams; ``GET /{id}/link`` mints such a link
under the module's policy, exactly as the download is.

**Writes are owner-scoped; reads are not**, and the distinction is worth stating because
this docstring used to open with "owner-scoped" unqualified and mean only the first half.
``OwnedMixin`` is a write gate by construction — a post-load boolean cannot paginate a
list — so ``GET /``, ``GET /{id}`` and the download stream return any file to any caller
who clears ``ADMIN``. For a deployment where that is wrong, one composition-root line
(:func:`terp.core.register_owner_read_scope`) installs the matching read filter for every
``OwnedMixin`` model and the two seams compose into "only the owner sees **or** changes
the row". It is opt-in rather than the default because it narrows what an
already-authorized caller can see, which is a decision about a product.

The raw ``storage_key`` never leaves the boundary (``FileRead`` omits it); the
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

import re
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, BinaryIO, Final

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from terp.core import (
    ADMIN,
    ModuleSpec,
    Page,
    PaginationDep,
    Policy,
    RateLimit,
    SessionDep,
    ValidationFailedError,
    operation,
    route_policy,
)

from terp.capabilities.files.links import LINK_TTL_MAX, content_disposition
from terp.capabilities.files.models import CONTENT_TYPE_MAX, FILENAME_MAX, File
from terp.capabilities.files.operations import (
    FILES_DELETE,
    FILES_DOWNLOAD,
    FILES_GET,
    FILES_LINK,
    FILES_LINK_CONTENT,
    FILES_LIST,
    FILES_UPDATE,
    FILES_UPLOAD,
)
from terp.capabilities.files.schemas import FileLinkRead, FileRead, FileUpdate
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


def _iter_blob(stream: BinaryIO, remaining: int | None = None) -> Iterator[bytes]:
    """Yield a backend blob stream in fixed-size chunks, closing it when exhausted.

    Feeds ``StreamingResponse`` so a download never materializes the whole file in memory;
    the ``finally`` guarantees the backend handle is released even if the client disconnects
    mid-stream. With *remaining*, exactly that many bytes are yielded from the stream's
    current position: the body of a ``206``.
    """
    try:
        while True:
            size = _DOWNLOAD_CHUNK_BYTES if remaining is None else min(_DOWNLOAD_CHUNK_BYTES, remaining)
            if size <= 0:
                return
            chunk = stream.read(size)
            if not chunk:
                return
            if remaining is not None:
                remaining -= len(chunk)
            yield chunk
    finally:
        stream.close()


# One range, in bytes, as RFC 9110 writes it: ``bytes=first-last``, ``bytes=first-`` or the
# suffix form ``bytes=-count``. Several ranges, or any other unit, are answered whole, and so
# is a number longer than any size a file can have: the digits are bounded here, so a header
# built to exhaust the integer parser is not read at all rather than refused with a 500.
_ONE_RANGE: Final[re.Pattern[str]] = re.compile(r"^bytes=(\d{0,19})-(\d{0,19})$")


class _UnsatisfiableRange(Exception):
    """A single range that selects no byte of the file: a ``416``."""


def _byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """``(first, last)`` for one satisfiable range in *header*, or ``None`` for the whole file.

    A header the route does not read (absent, another unit, several ranges, malformed)
    means the whole file with ``200``, as RFC 9110 allows a server to answer. A single range
    that selects nothing raises :class:`_UnsatisfiableRange`.
    """
    if header is None:
        return None
    match = _ONE_RANGE.match(header.strip())
    if match is None:
        return None
    first_text, last_text = match.groups()
    if not first_text and not last_text:
        return None
    if not first_text:  # bytes=-count: the last `count` bytes
        count = int(last_text)
        if count == 0 or size == 0:
            raise _UnsatisfiableRange()
        return max(size - count, 0), size - 1
    first = int(first_text)
    if first >= size:
        raise _UnsatisfiableRange()
    last = size - 1 if not last_text else min(int(last_text), size - 1)
    if last < first:
        return None
    return first, last


def _skip_to(stream: BinaryIO, offset: int) -> None:
    """Position *stream* at *offset*: a seek where the stream can, a read-and-discard where it cannot."""
    seekable = getattr(stream, "seekable", None)
    if callable(seekable) and seekable():
        stream.seek(offset)
        return
    while offset > 0:
        chunk = stream.read(min(_DOWNLOAD_CHUNK_BYTES, offset))
        if not chunk:
            return
        offset -= len(chunk)


def _serve(row: File, stream: BinaryIO, request: Request, *, inline: bool = False) -> Response:
    """The bytes of *row* from *stream*, whole or the one range the request asks for (ADR 0201).

    Every answer says ``Accept-Ranges: bytes``; a satisfiable single range is a ``206`` with
    ``Content-Range``; a range the file cannot satisfy is a ``416`` naming the size; anything
    else is the whole file with ``200``. The stored size is append-only and derived from the
    streamed bytes at create time, so it is authoritative for both lengths, and a blob
    truncated out-of-band surfaces as a protocol error instead of a silently short body.
    """
    headers = {
        "Content-Disposition": content_disposition(row.filename, inline=inline),
        "Accept-Ranges": "bytes",
    }
    try:
        part = _byte_range(request.headers.get("range"), row.size)
    except _UnsatisfiableRange:
        stream.close()
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{row.size}", "Accept-Ranges": "bytes"},
        )
    if part is None:
        headers["Content-Length"] = str(row.size)
        return StreamingResponse(_iter_blob(stream), media_type=row.content_type, headers=headers)
    first, last = part
    _skip_to(stream, first)
    headers["Content-Length"] = str(last - first + 1)
    headers["Content-Range"] = f"bytes {first}-{last}/{row.size}"
    return StreamingResponse(
        _iter_blob(stream, last - first + 1),
        status_code=206,
        media_type=row.content_type,
        headers=headers,
    )


router = APIRouter(tags=["files"])
_service = FileService()


def _content_disposition(filename: str) -> str:
    """The attachment disposition a download carries; the one definition is in ``links``."""
    return content_disposition(filename)


@router.post("/", response_model=FileRead, status_code=201)
@operation(FILES_UPLOAD)
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
@operation(FILES_LIST)
def list_files(session: SessionDep, pagination: PaginationDep) -> Page[FileRead]:
    rows, total = _service.list(session, skip=pagination.skip, limit=pagination.limit)
    return Page[FileRead].of(
        [FileRead.model_validate(row) for row in rows], total, pagination
    )


@router.get("/{file_id}", response_model=FileRead)
@operation(FILES_GET)
def get_file(file_id: uuid.UUID, session: SessionDep) -> FileRead:
    return FileRead.model_validate(_service.get(session, file_id))


@router.get("/link/{token}")  # arch-allow-routes-declare-response-model: binary download through an app-signed link — the bytes stream out through a StreamingResponse, never a serialized ORM object
@route_policy(
    Policy.public(
        reason="an app-signed link is read by a player or a viewer that cannot send a bearer; "
        "the sealed, expiring token is the credential, minted only where a download was authorized"
    )
)
@operation(FILES_LINK_CONTENT)
def read_link(
    token: Annotated[str, Path(min_length=1, max_length=2048)],
    session: SessionDep,
    request: Request,
) -> Response:
    row, stream, inline = _service.open_link_stream(session, token)
    return _serve(row, stream, request, inline=inline)


@router.get("/{file_id}/content")  # arch-allow-routes-declare-response-model: binary download — the bytes stream out through a StreamingResponse (stored media type + sanitized attachment disposition), never a serialized ORM object
@operation(FILES_DOWNLOAD)
def download_file(file_id: uuid.UUID, session: SessionDep, request: Request) -> Response:
    row, stream = _service.open_stream(session, file_id)
    return _serve(row, stream, request)


@router.get("/{file_id}/link", response_model=FileLinkRead)
@operation(FILES_LINK)
def link_file(
    file_id: uuid.UUID,
    session: SessionDep,
    ttl_seconds: Annotated[int | None, Query(ge=1, le=int(LINK_TTL_MAX.total_seconds()))] = None,
    inline: bool = False,
) -> FileLinkRead:
    link = _service.link(
        session,
        file_id,
        ttl=None if ttl_seconds is None else timedelta(seconds=ttl_seconds),
        inline=inline,
    )
    return FileLinkRead(url=link.url, expires_at=link.expires_at)


@router.patch("/{file_id}", response_model=FileRead)
@operation(FILES_UPDATE)
def update_file(
    file_id: uuid.UUID, payload: FileUpdate, session: SessionDep
) -> FileRead:
    return FileRead.model_validate(_service.update(session, file_id, payload))


@router.delete("/{file_id}", status_code=204)
@operation(FILES_DELETE)
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
    # The one public route verifies a credential (the sealed link token), so it declares
    # its own rate limit (ADR 0138). Opening a sealed token is cheap, and a player makes
    # many range requests over one session, so the general allowance is the right cap;
    # declaring it here is what makes it visible beside the route it protects.
    rate_limit={"/link": RateLimit()},
)


__all__ = [
    "MAX_UPLOAD_BYTES",
    "active_upload_limit",
    "configure_upload_limit",
    "module",
    "reset_upload_limit",
    "router",
]
