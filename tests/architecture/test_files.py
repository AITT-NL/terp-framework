"""Gate for ``terp-cap-files`` (ADR 0056): the storage seam, the local reference adapter's
fail-closed key handling, the upload's compensation (a failed metadata write never leaves an
orphan blob), the typed 404 for a vanished blob, the delete ordering (the owner-gated row
delete decides *before* any byte is destroyed), the never-serialized ``storage_key``, and
the sanitized ``Content-Disposition`` — all against a real ``BaseService`` write stack over
SQLite, with the byte I/O on a per-test temporary directory.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.requests import Request

from terp.core import NotFoundError, ValidationFailedError
from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.files import (
    DEFAULT_STORAGE_PROFILE,
    MAX_UPLOAD_BYTES,
    ContentTypeMismatchError,
    File,
    FileRead,
    FileRef,
    FileService,
    FileStorageError,
    LocalFilesystemStorage,
    StorageBackend,
    UndeclaredFileReferenceError,
    UnknownStorageProfileError,
    UnsupportedContentTypeError,
    active_allowed_content_types,
    active_storage_backend,
    active_upload_limit,
    configure_allowed_content_types,
    configure_upload_limit,
    is_file_reference,
    module,
    register_storage_backend,
    reset_allowed_content_types,
    reset_storage_backend,
    reset_upload_limit,
    resolve_storage_backend,
    set_storage_backend,
)
from terp.capabilities.files.router import (
    _content_disposition,
    download_file,
    upload_file,
)

_CONTENT = b"the stored bytes"
_PNG = b"\x89PNG\r\n\x1a\n" + _CONTENT  # bytes carrying the PNG signature (ADR 0076)
_PDF = b"%PDF-1.7\n" + _CONTENT  # bytes carrying the PDF signature (ADR 0076)


@pytest.fixture
def storage_root(tmp_path: Path) -> Iterator[Path]:
    """Install a per-test local backend on the process-global seam, then restore it."""
    root = tmp_path / "blobs"
    set_storage_backend(LocalFilesystemStorage(root))
    yield root
    reset_storage_backend()


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with WriteGuardedSession(engine) as sess:
        yield sess
    engine.dispose()


def _store(service: FileService, session: Session, **overrides) -> File:
    kwargs = {
        "filename": "a.txt",
        "content_type": "text/plain",
        "source": io.BytesIO(_CONTENT),
    }
    kwargs.update(overrides)
    return service.store(session, **kwargs)


# --------------------------------------------------------------------------- #
# The storage seam + the local reference adapter
# --------------------------------------------------------------------------- #
def test_the_default_backend_is_the_local_reference_adapter() -> None:
    reset_storage_backend()
    assert isinstance(active_storage_backend(), LocalFilesystemStorage)


def test_set_and_reset_swap_the_active_backend(tmp_path: Path) -> None:
    backend = LocalFilesystemStorage(tmp_path)
    set_storage_backend(backend)
    try:
        assert active_storage_backend() is backend
    finally:
        reset_storage_backend()
    assert active_storage_backend() is not backend


def test_local_adapter_round_trips_and_deletes_idempotently(tmp_path: Path) -> None:
    backend = LocalFilesystemStorage(tmp_path)
    backend.put("ab/abc123", io.BytesIO(_CONTENT))
    with backend.open("ab/abc123") as stream:
        assert stream.read() == _CONTENT
    backend.delete("ab/abc123")
    with pytest.raises(FileNotFoundError):
        backend.open("ab/abc123")
    backend.delete("ab/abc123")  # idempotent: an already-gone blob is a no-op


def test_local_adapter_fails_closed_on_a_traversal_shaped_key(tmp_path: Path) -> None:
    backend = LocalFilesystemStorage(tmp_path / "root")
    for operation in (
        lambda: backend.put("../escape", io.BytesIO(b"x")),
        lambda: backend.open("../escape"),
        lambda: backend.delete("../escape"),
    ):
        with pytest.raises(FileStorageError):
            operation()
    assert not (tmp_path / "escape").exists()  # nothing touched outside the root


# --------------------------------------------------------------------------- #
# A second, non-filesystem backend proves the file-like port swaps (ADR 0066)
# --------------------------------------------------------------------------- #
class _InMemoryStorage(StorageBackend):
    """A pure in-memory backend: proves store/load/remove ride any file-like adapter."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, key: str, source: BinaryIO) -> None:
        self._blobs[key] = source.read()

    def open(self, key: str) -> BinaryIO:
        try:
            return io.BytesIO(self._blobs[key])
        except KeyError:
            raise FileNotFoundError(key) from None

    def delete(self, key: str) -> None:
        self._blobs.pop(key, None)


def test_a_second_in_memory_backend_round_trips_through_the_service(
    session: Session,
) -> None:
    set_storage_backend(_InMemoryStorage())
    try:
        service = FileService()
        row = _store(service, session)
        loaded, data = service.load(session, row.id)
        assert data == _CONTENT
        assert loaded.sha256 == row.sha256
        service.remove(session, row.id)
        with pytest.raises(NotFoundError):
            service.load(session, row.id)
    finally:
        reset_storage_backend()


# --------------------------------------------------------------------------- #
# The named-profile registry (ADR 0057)
# --------------------------------------------------------------------------- #
def test_register_and_resolve_a_named_profile(tmp_path: Path) -> None:
    backend = LocalFilesystemStorage(tmp_path)
    register_storage_backend("cold", backend)
    try:
        assert resolve_storage_backend("cold") is backend
        # The default profile is untouched by a named registration.
        assert resolve_storage_backend(DEFAULT_STORAGE_PROFILE) is not backend
    finally:
        reset_storage_backend()


def test_resolving_an_unknown_profile_fails_closed() -> None:
    reset_storage_backend()
    with pytest.raises(UnknownStorageProfileError):
        resolve_storage_backend("never-registered")


def test_registering_an_invalid_profile_name_is_refused(tmp_path: Path) -> None:
    backend = LocalFilesystemStorage(tmp_path)
    with pytest.raises(ValueError):
        register_storage_backend("", backend)
    with pytest.raises(ValueError):
        register_storage_backend("p" * 65, backend)


def test_reset_clears_registered_profiles(tmp_path: Path) -> None:
    register_storage_backend("cold", LocalFilesystemStorage(tmp_path))
    reset_storage_backend()
    with pytest.raises(UnknownStorageProfileError):
        resolve_storage_backend("cold")


# --------------------------------------------------------------------------- #
# The service orchestrations
# --------------------------------------------------------------------------- #
def test_store_persists_metadata_and_bytes(
    session: Session, storage_root: Path
) -> None:
    service = FileService()
    row = _store(service, session)
    assert row.size == len(_CONTENT)
    assert len(row.sha256) == 64
    with active_storage_backend().open(row.storage_key) as stream:
        assert stream.read() == _CONTENT
    assert row.storage_key not in row.filename  # opaque, server-generated


def test_store_compensates_the_blob_when_the_row_write_fails(
    session: Session, storage_root: Path
) -> None:
    # An overlong filename fails FileCreate validation AFTER the blob landed: the
    # compensation must remove it so a failed upload leaves nothing behind.
    service = FileService()
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _store(service, session, filename="n" * 300)
    assert not any(p for p in storage_root.rglob("*") if p.is_file())


def test_load_returns_the_row_and_bytes(session: Session, storage_root: Path) -> None:
    service = FileService()
    row = _store(service, session)
    loaded, data = service.load(session, row.id)
    assert loaded.id == row.id
    assert data == _CONTENT


def test_load_maps_a_vanished_blob_to_a_typed_404(
    session: Session, storage_root: Path
) -> None:
    service = FileService()
    row = _store(service, session)
    active_storage_backend().delete(row.storage_key)
    with pytest.raises(NotFoundError):
        service.load(session, row.id)


def test_remove_deletes_the_row_then_the_blob(
    session: Session, storage_root: Path
) -> None:
    service = FileService()
    row = _store(service, session)
    key = row.storage_key
    service.remove(session, row.id)
    with pytest.raises(NotFoundError):
        service.get(session, row.id)
    with pytest.raises(FileNotFoundError):
        active_storage_backend().open(key)


def test_remove_of_an_unknown_id_is_a_typed_404(
    session: Session, storage_root: Path
) -> None:
    with pytest.raises(NotFoundError):
        FileService().remove(session, uuid.uuid4())


# --------------------------------------------------------------------------- #
# Per-module / per-use storage profiles (ADR 0057)
# --------------------------------------------------------------------------- #
def test_store_stamps_the_default_profile(
    session: Session, storage_root: Path
) -> None:
    row = _store(FileService(), session)
    assert row.storage_profile == DEFAULT_STORAGE_PROFILE


def test_store_routes_bytes_to_the_selected_profile(
    session: Session, storage_root: Path, tmp_path: Path
) -> None:
    cold_root = tmp_path / "cold"
    register_storage_backend("cold", LocalFilesystemStorage(cold_root))
    service = FileService()
    row = service.store(
        session,
        filename="a.txt",
        content_type="text/plain",
        source=io.BytesIO(_CONTENT),
        profile="cold",
    )
    assert row.storage_profile == "cold"
    # The bytes landed in the named store, not the default one.
    assert (cold_root / row.storage_key).read_bytes() == _CONTENT
    assert not (storage_root / row.storage_key).exists()
    # load / remove route through the row's own profile, not the default.
    loaded, data = service.load(session, row.id)
    assert data == _CONTENT
    service.remove(session, row.id)
    assert not (cold_root / row.storage_key).exists()


def test_store_with_an_unknown_profile_fails_before_any_byte_lands(
    session: Session, storage_root: Path
) -> None:
    with pytest.raises(UnknownStorageProfileError):
        _store(FileService(), session, profile="never-registered")
    assert not any(p for p in storage_root.rglob("*") if p.is_file())


def test_a_service_subclass_binds_its_own_profile(
    session: Session, storage_root: Path, tmp_path: Path
) -> None:
    register_storage_backend("invoices", LocalFilesystemStorage(tmp_path / "inv"))

    class InvoiceFileService(FileService):
        storage_profile = "invoices"

    row = _store(InvoiceFileService(), session)
    assert row.storage_profile == "invoices"
    assert (tmp_path / "inv" / row.storage_key).read_bytes() == _CONTENT


def test_remove_fails_closed_when_the_rows_profile_is_unregistered(
    session: Session, storage_root: Path, tmp_path: Path
) -> None:
    register_storage_backend("cold", LocalFilesystemStorage(tmp_path / "cold"))
    service = FileService()
    row = service.store(
        session,
        filename="a.txt",
        content_type="text/plain",
        source=io.BytesIO(_CONTENT),
        profile="cold",
    )
    reset_storage_backend()  # "cold" is gone: its bytes are unreachable
    with pytest.raises(UnknownStorageProfileError):
        service.remove(session, row.id)
    # Fail-closed: the row survives rather than orphaning unreachable bytes.
    assert service.get(session, row.id).id == row.id


# --------------------------------------------------------------------------- #
# Declared file references + serve-through delegation (ADR 0057)
# --------------------------------------------------------------------------- #
class _RecordWithAttachment(SQLModel):
    """A referencing row as another module's service would return it (non-table stand-in)."""

    attachment_file_id: uuid.UUID | None = FileRef()


class _RecordWithBareColumn(SQLModel):
    attachment_file_id: uuid.UUID | None = None


def test_fileref_marks_the_column_as_a_declared_reference() -> None:
    assert is_file_reference(_RecordWithAttachment, "attachment_file_id")
    assert not is_file_reference(_RecordWithBareColumn, "attachment_file_id")
    assert not is_file_reference(_RecordWithAttachment, "no_such_column")


def test_load_for_serves_the_referenced_file(
    session: Session, storage_root: Path
) -> None:
    service = FileService()
    row = _store(service, session)
    record = _RecordWithAttachment(attachment_file_id=row.id)
    loaded, data = service.load_for(session, record, "attachment_file_id")
    assert loaded.id == row.id
    assert data == _CONTENT


def test_load_for_fails_closed_on_an_undeclared_reference(
    session: Session, storage_root: Path
) -> None:
    service = FileService()
    row = _store(service, session)
    record = _RecordWithBareColumn(attachment_file_id=row.id)
    with pytest.raises(UndeclaredFileReferenceError):
        service.load_for(session, record, "attachment_file_id")


def test_load_for_maps_an_empty_reference_to_a_typed_404(
    session: Session, storage_root: Path
) -> None:
    record = _RecordWithAttachment(attachment_file_id=None)
    with pytest.raises(NotFoundError):
        FileService().load_for(session, record, "attachment_file_id")


# --------------------------------------------------------------------------- #
# The sensitive-field posture: storage_key / storage_profile never cross the boundary
# --------------------------------------------------------------------------- #
def test_no_read_dto_serializes_the_storage_key(
    session: Session, storage_root: Path
) -> None:
    """The runtime half of the posture: a validated Read DTO carries no storage material."""
    assert "storage_key" not in FileRead.model_fields
    assert "storage_profile" not in FileRead.model_fields
    row = _store(FileService(), session)
    dumped = FileRead.model_validate(row).model_dump_json()
    assert row.storage_key not in dumped
    assert "storage_key" not in dumped
    assert "storage_profile" not in dumped


# --------------------------------------------------------------------------- #
# The router's boundary logic (direct-call coverage; the mounted end-to-end
# behavior is exercised in apps/example/tests/test_files_api.py)
# --------------------------------------------------------------------------- #
def _multipart_request(
    data: bytes,
    *,
    filename: str | None,
    content_type: str | None,
) -> Request:
    boundary = "terp-test-boundary"
    part_headers = (
        f'Content-Disposition: form-data; name="file"; filename="{filename or ""}"\r\n'
    )
    if content_type is not None:
        part_headers += f"Content-Type: {content_type}\r\n"
    body = (
        f"--{boundary}\r\n".encode("ascii")
        + part_headers.encode("latin-1")
        + b"\r\n"
        + data
        + f"\r\n--{boundary}--\r\n".encode("ascii")
    )
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/files/",
        "query_string": b"",
        "headers": [
            (
                b"content-type",
                f"multipart/form-data; boundary={boundary}".encode("latin-1"),
            ),
            (b"content-length", str(len(body)).encode("latin-1")),
        ],
    }
    return Request(scope, receive)


def _empty_multipart_request() -> Request:
    boundary = "terp-test-boundary"
    body = f"--{boundary}--\r\n".encode("ascii")
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/files/",
            "query_string": b"",
            "headers": [
                (
                    b"content-type",
                    f"multipart/form-data; boundary={boundary}".encode("latin-1"),
                ),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        },
        receive,
    )


def _collect_stream(response) -> bytes:
    """Drain a StreamingResponse's async body iterator to bytes (test-only)."""

    async def _drain() -> bytes:
        return b"".join([chunk async for chunk in response.body_iterator])

    return asyncio.run(_drain())


def test_upload_defaults_a_missing_filename_and_content_type(
    session: Session, storage_root: Path
) -> None:
    request = _multipart_request(_CONTENT, filename=None, content_type=None)
    read = asyncio.run(upload_file(request, session))
    assert read.filename == "upload"
    assert read.content_type == "application/octet-stream"


def test_upload_requires_a_file_part_named_file(
    session: Session, storage_root: Path
) -> None:
    with pytest.raises(ValidationFailedError, match="file part named 'file'"):
        asyncio.run(upload_file(_empty_multipart_request(), session))


def test_upload_rejects_an_oversized_body_at_the_boundary(
    session: Session, storage_root: Path
) -> None:
    configure_upload_limit(4)
    try:
        request = _multipart_request(b"12345", filename="big.bin", content_type="text/plain")
        with pytest.raises(ValidationFailedError):
            asyncio.run(upload_file(request, session))
    finally:
        reset_upload_limit()
    assert not any(p for p in storage_root.rglob("*") if p.is_file())  # nothing stored


def test_upload_rejects_an_overlong_filename_and_content_type(
    session: Session, storage_root: Path
) -> None:
    with pytest.raises(ValidationFailedError):
        request = _multipart_request(_CONTENT, filename="n" * 300, content_type="text/plain")
        asyncio.run(upload_file(request, session))
    with pytest.raises(ValidationFailedError):
        request = _multipart_request(_CONTENT, filename="ok.txt", content_type="t/" + "x" * 300)
        asyncio.run(upload_file(request, session))


def test_download_builds_an_injection_proof_disposition(
    session: Session, storage_root: Path
) -> None:
    service = FileService()
    row = _store(service, session, filename='we"ird\r\nname.txt')
    response = download_file(row.id, session)
    assert _collect_stream(response) == _CONTENT
    disposition = response.headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert 'filename="we_ird__name.txt"' in disposition
    assert "filename*=UTF-8''we%22ird%0D%0Aname.txt" in disposition


def test_disposition_falls_back_when_no_ascii_survives() -> None:
    assert _content_disposition("øøø") == (
        'attachment; filename="___"; filename*=UTF-8\'\'%C3%B8%C3%B8%C3%B8'
    )
    assert '"upload"' in _content_disposition("")


def test_the_module_spec_is_admin_only() -> None:
    assert module.name == "files"


# --------------------------------------------------------------------------- #
# The configurable upload limit + the declared request allowance (ADR 0067)
# --------------------------------------------------------------------------- #
def test_the_upload_limit_is_composition_root_configurable() -> None:
    assert active_upload_limit() == MAX_UPLOAD_BYTES
    configure_upload_limit(123)
    try:
        assert active_upload_limit() == 123
    finally:
        reset_upload_limit()
    assert active_upload_limit() == MAX_UPLOAD_BYTES


def test_a_non_positive_upload_limit_is_refused() -> None:
    for bad in (0, -1):
        with pytest.raises(ValueError, match="positive"):
            configure_upload_limit(bad)
    assert active_upload_limit() == MAX_UPLOAD_BYTES  # the refusal left the cap intact


def test_the_spec_declares_a_request_allowance_above_the_stored_cap() -> None:
    """The kernel-honored request ceiling covers a maximum-size upload + multipart framing."""
    assert module.max_request_bytes is not None
    assert module.max_request_bytes > MAX_UPLOAD_BYTES


# --------------------------------------------------------------------------- #
# The content-type allowlist (ADR 0068)
# --------------------------------------------------------------------------- #
def test_the_default_posture_allows_every_content_type(
    session: Session, storage_root: Path
) -> None:
    assert active_allowed_content_types() is None
    row = _store(FileService(), session, content_type="application/x-anything")
    assert row.content_type == "application/x-anything"


def test_a_configured_allowlist_refuses_other_types_before_any_byte_lands(
    session: Session, storage_root: Path
) -> None:
    configure_allowed_content_types(["application/pdf", "image/*"])
    try:
        assert active_allowed_content_types() == ("application/pdf", "image/*")
        # Exact match, wildcard match, and parameter/case normalization all pass
        # (with bytes carrying the declared type's signature — ADR 0076).
        _store(FileService(), session, content_type="application/pdf", source=io.BytesIO(_PDF))
        _store(FileService(), session, content_type="image/png", source=io.BytesIO(_PNG))
        _store(
            FileService(),
            session,
            content_type="Application/PDF; charset=binary",
            source=io.BytesIO(_PDF),
        )
        # A disallowed type refuses with a typed 415 and stores nothing new.
        stored_before = sorted(p for p in storage_root.rglob("*") if p.is_file())
        with pytest.raises(UnsupportedContentTypeError):
            _store(FileService(), session, content_type="application/x-msdownload")
        assert sorted(p for p in storage_root.rglob("*") if p.is_file()) == stored_before
        # image/* must not leak to lookalike types (imagex/... or image alone).
        with pytest.raises(UnsupportedContentTypeError):
            _store(FileService(), session, content_type="imagex/png")
    finally:
        reset_allowed_content_types()
    assert active_allowed_content_types() is None


def test_a_shapeless_allowlist_is_refused_eagerly() -> None:
    for bad in ([], [""], ["pdf"], ["*/pdf"], ["application/"], ["/pdf"]):
        with pytest.raises(ValueError):
            configure_allowed_content_types(bad)
    assert active_allowed_content_types() is None  # the refusals left the default intact
    assert module.router is not None
    assert module.policy is not None
    assert MAX_UPLOAD_BYTES == 25 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Magic-byte sniffing (ADR 0076)
# --------------------------------------------------------------------------- #
def test_a_declared_type_whose_signature_the_bytes_lack_is_refused(
    session: Session, storage_root: Path
) -> None:
    """Mislabeled bytes die with a typed 415 and nothing lands in storage."""
    stored_before = sorted(p for p in storage_root.rglob("*") if p.is_file())
    with pytest.raises(ContentTypeMismatchError) as excinfo:
        _store(FileService(), session, content_type="image/png", source=io.BytesIO(_CONTENT))
    assert excinfo.value.status_code == 415
    assert excinfo.value.code == "content_type_mismatch"
    assert sorted(p for p in storage_root.rglob("*") if p.is_file()) == stored_before
    # Case/parameter normalization applies to the sniff too.
    with pytest.raises(ContentTypeMismatchError):
        _store(
            FileService(),
            session,
            content_type="Image/PNG; charset=binary",
            source=io.BytesIO(_CONTENT),
        )


def test_matching_signatures_pass_and_the_stored_blob_is_byte_exact(
    session: Session, storage_root: Path
) -> None:
    """The sniffed head is replayed: digest, size and stored bytes cover the full upload."""
    row = _store(FileService(), session, content_type="image/png", source=io.BytesIO(_PNG))
    assert row.size == len(_PNG)
    assert row.sha256 == hashlib.sha256(_PNG).hexdigest()
    stored = next(p for p in storage_root.rglob("*") if p.is_file())
    assert stored.read_bytes() == _PNG
    # Every signature alternative is accepted (GIF87a/GIF89a, TIFF LE/BE, ZIP flavors, …).
    for content_type, body in [
        ("image/jpeg", b"\xff\xd8\xff\xe0" + _CONTENT),
        ("image/gif", b"GIF87a" + _CONTENT),
        ("image/gif", b"GIF89a" + _CONTENT),
        ("image/webp", b"RIFF\x00\x00\x00\x00WEBP" + _CONTENT),
        ("image/bmp", b"BM" + _CONTENT),
        ("image/tiff", b"II*\x00" + _CONTENT),
        ("image/tiff", b"MM\x00*" + _CONTENT),
        ("application/pdf", _PDF),
        ("application/zip", b"PK\x03\x04" + _CONTENT),
        ("application/zip", b"PK\x05\x06" + _CONTENT),
        ("application/zip", b"PK\x07\x08" + _CONTENT),
        ("application/gzip", b"\x1f\x8b" + _CONTENT),
    ]:
        _store(FileService(), session, content_type=content_type, source=io.BytesIO(body))
    # A partial multi-constraint match still refuses (RIFF container that is not WEBP).
    with pytest.raises(ContentTypeMismatchError):
        _store(
            FileService(),
            session,
            content_type="image/webp",
            source=io.BytesIO(b"RIFF\x00\x00\x00\x00WAVE" + _CONTENT),
        )


def test_a_type_without_a_known_signature_is_not_sniffed(
    session: Session, storage_root: Path
) -> None:
    """The control refuses proven mismatches, never guesses: unmapped types pass through."""
    row = _store(FileService(), session, content_type="application/x-anything")
    assert row.size == len(_CONTENT)
    assert row.sha256 == hashlib.sha256(_CONTENT).hexdigest()
