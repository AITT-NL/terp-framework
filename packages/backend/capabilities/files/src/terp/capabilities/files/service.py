"""The files service: owner-scoped metadata CRUD orchestrated with the storage seam.

``FileService`` is a plain ``BaseService`` — ``File`` composes ``OwnedMixin``, so the
per-row write gate (only the owner may rename / delete a file) is enforced centrally by
the kernel with **no** code here. On top of the inherited CRUD it adds the byte-carrying
orchestrations, each keeping the metadata write transactional while the byte I/O rides
the storage backend registered under the file's **storage profile** (ADR 0057):

* :meth:`FileService.store` — resolve the profile's backend fail-closed *first* (an
  unregistered profile refuses before any byte lands), **stream** the source into it (under
  a fresh server-generated opaque key, hashing + size-capping the bytes as they flow —
  never buffering the whole upload), then create the metadata row — stamped with the
  profile — through the audited chokepoint; the ``put`` runs inside the compensation guard,
  so an over-cap upload or a failed row write deletes the partial blob (``delete`` is
  idempotent), so a failed upload never leaves an orphan blob **and** a committed row always
  has its bytes. The profile is selected per call (``profile=``) or per service (the
  ``storage_profile`` class default — a module binds its own store by subclassing), never by
  a client.
* :meth:`FileService.open_stream` / :meth:`FileService.load` — the scope-honoring ``get``
  resolves the metadata (so an invisible row 404s before any storage I/O), then a readable
  stream (``open_stream``, for the streamed download) or the full bytes (``load``, a
  buffered convenience for the serve-through read) are fetched from the backend the **row
  itself** names; a missing blob maps to a typed 404 rather than a stack trace.
* :meth:`FileService.load_for` — the serve-through delegation read (ADR 0057): serve a
  file through an already-authorized referencing row, fail-closed on any column not
  declared with :func:`~terp.capabilities.files.FileRef`.
* :meth:`FileService.remove` — the delete folds both stores into **one** owner-gated,
  audited transaction (:meth:`FileService._after_write`): the kernel authorizes the
  per-row write first (a caller who may not delete the row never reaches the bytes), then
  the profile's backend resolves fail-closed and the blob is removed *before* the row
  delete commits — so a backend failure rolls the whole unit back (the row, which alone
  holds the key, survives and the delete stays retryable by id) and a committed delete
  never leaves an orphan blob behind.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from typing import BinaryIO, ClassVar

from sqlmodel import Session, SQLModel

from terp.core import (
    AppError,
    AuditAction,
    BaseService,
    NotFoundError,
    ValidationFailedError,
)

from terp.capabilities.files.models import File
from terp.capabilities.files.references import (
    UndeclaredFileReferenceError,
    is_file_reference,
)
from terp.capabilities.files.schemas import FileCreate, FileUpdate
from terp.capabilities.files.storage import (
    DEFAULT_STORAGE_PROFILE,
    resolve_storage_backend,
)


def _new_storage_key() -> str:
    """A fresh opaque blob address: UUID-derived, two-level sharded, never client data."""
    token = uuid.uuid4().hex
    return f"{token[:2]}/{token}"


class UnsupportedContentTypeError(AppError):
    """415 — the upload's content type is not in the deployment's allowlist (ADR 0068)."""

    status_code = 415
    code = "content_type_not_allowed"
    default_message = "The uploaded file's content type is not allowed."


class ContentTypeMismatchError(AppError):
    """415 — the upload's bytes do not carry the declared content type's signature (ADR 0076)."""

    status_code = 415
    code = "content_type_mismatch"
    default_message = "The uploaded bytes do not match the declared content type."


def _normalized_media_type(value: str) -> str:
    """The bare, lowercased media type: parameters stripped (``TEXT/Plain; q=1`` → ``text/plain``)."""
    return value.split(";", 1)[0].strip().lower()


# The deployment's upload content-type allowlist (ADR 0068). ``None`` — the default —
# allows every type (content type is descriptive metadata; ADR 0056's shipped posture).
# A composition root narrows it with one line; the check is enforced in the service
# chokepoint so no upload path (router or programmatic ``store``) can bypass it.
_allowed_content_types: tuple[str, ...] | None = None


def configure_allowed_content_types(allowed: Iterable[str]) -> None:
    """Restrict uploads to *allowed* media types (a composition-root line, ADR 0068).

    Entries are exact media types (``"application/pdf"``) or whole-subtype wildcards
    (``"image/*"``); they are normalized (lowercased, parameters stripped) and validated
    eagerly — an empty allowlist or a shapeless entry raises ``ValueError`` at boot, not
    at the first upload. Allow-everything is expressed by *not* configuring an allowlist
    (or :func:`reset_allowed_content_types`), never by a ``*/*`` entry — a visible,
    greppable default rather than a wildcard that reads like a restriction.
    """
    global _allowed_content_types
    normalized = tuple(dict.fromkeys(_normalized_media_type(item) for item in allowed))
    if not normalized:
        raise ValueError("the content-type allowlist must name at least one media type")
    for entry in normalized:
        base, separator, subtype = entry.partition("/")
        if not base or base == "*" or not separator or not subtype:
            raise ValueError(
                f"content-type allowlist entry {entry!r} must be 'type/subtype' or 'type/*'"
            )
    _allowed_content_types = normalized


def active_allowed_content_types() -> tuple[str, ...] | None:
    """The configured allowlist, or ``None`` when every content type is allowed."""
    return _allowed_content_types


def reset_allowed_content_types() -> None:
    """Restore the allow-everything default (the test-isolation reset)."""
    global _allowed_content_types
    _allowed_content_types = None


def _ensure_content_type_allowed(content_type: str) -> None:
    """Fail closed when an allowlist is configured and *content_type* is not on it."""
    allowed = _allowed_content_types
    if allowed is None:
        return
    media_type = _normalized_media_type(content_type)
    for entry in allowed:
        if media_type == entry:
            return
        if entry.endswith("/*") and media_type.startswith(entry[:-1]):
            return
    raise UnsupportedContentTypeError(log_context={"content_type": media_type})


# Magic-byte sniffing (ADR 0076): for a media type whose file format carries a
# well-known signature, the upload's *bytes* must actually carry it — a declared
# content type is client input, and a later consumer (a browser rendering the
# stored `content_type`, a downstream parser choosing a decoder by it) must not
# be handed mislabeled bytes. Each entry maps a media type to its accepted
# signature alternatives; an alternative is a set of (offset, bytes) constraints
# that must **all** hold. A type not listed here has no canonical signature
# (text/*, application/json, …) and is not sniffed — the control refuses proven
# mismatches, never guesses.
_MAGIC_SIGNATURES: dict[str, tuple[tuple[tuple[int, bytes], ...], ...]] = {
    "image/png": (((0, b"\x89PNG\r\n\x1a\n"),),),
    "image/jpeg": (((0, b"\xff\xd8\xff"),),),
    "image/gif": (((0, b"GIF87a"),), ((0, b"GIF89a"),)),
    "image/webp": (((0, b"RIFF"), (8, b"WEBP")),),
    "image/bmp": (((0, b"BM"),),),
    "image/tiff": (((0, b"II*\x00"),), ((0, b"MM\x00*"),)),
    "application/pdf": (((0, b"%PDF-"),),),
    "application/zip": (((0, b"PK\x03\x04"),), ((0, b"PK\x05\x06"),), ((0, b"PK\x07\x08"),)),
    "application/gzip": (((0, b"\x1f\x8b"),),),
}

# The longest constraint ends at offset 8 + len(b"WEBP") = 12; peeking 16 keeps headroom.
_SNIFF_LEN = 16


def _ensure_bytes_match_declared_type(content_type: str, head: bytes) -> None:
    """Fail closed when the declared type has a known signature the bytes lack (ADR 0076)."""
    alternatives = _MAGIC_SIGNATURES.get(_normalized_media_type(content_type))
    if alternatives is None:
        return
    for constraints in alternatives:
        if all(
            head[offset : offset + len(signature)] == signature
            for offset, signature in constraints
        ):
            return
    raise ContentTypeMismatchError(
        log_context={"content_type": _normalized_media_type(content_type)}
    )


class _PrefixedReader:
    """Replays an already-peeked *prefix* ahead of the remaining *source* stream.

    The sniff check (:func:`_ensure_bytes_match_declared_type`) consumes the first
    bytes of an upload before any byte lands in storage; this wrapper hands those
    bytes back first, so the stored blob (and its streamed digest / size) covers
    exactly the full upload.
    """

    def __init__(self, prefix: bytes, source: BinaryIO) -> None:
        self._prefix = prefix
        self._offset = 0
        self._source = source

    def read(self, size: int = -1) -> bytes:
        remaining = self._prefix[self._offset :]
        if not remaining:
            return self._source.read(size)
        if size < 0:
            self._offset = len(self._prefix)
            return remaining + self._source.read(size)
        chunk = remaining[:size]
        self._offset += len(chunk)
        if len(chunk) < size:
            chunk += self._source.read(size - len(chunk))
        return chunk


class _DigestingReader:
    """A read-only file-like wrapper that hashes, counts, and size-caps a stream in flight.

    ``StorageBackend.put`` pulls bytes through ``read`` in chunks (``shutil.copyfileobj``);
    this wrapper folds each chunk into a running SHA-256 and byte count and raises a typed
    :class:`~terp.core.ValidationFailedError` the instant the total exceeds *max_bytes* — so
    the size cap is enforced mid-stream without ever buffering the whole upload, and the
    resulting digest / size describe exactly the bytes handed to the backend.
    """

    def __init__(self, source: BinaryIO, max_bytes: int | None) -> None:
        self._source = source
        self._max_bytes = max_bytes
        self._digest = hashlib.sha256()
        self.size = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(size)
        self.size += len(chunk)
        if self._max_bytes is not None and self.size > self._max_bytes:
            raise ValidationFailedError(
                f"The uploaded file exceeds the {self._max_bytes}-byte limit."
            )
        self._digest.update(chunk)
        return chunk

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


class FileService(BaseService[File, FileCreate, FileUpdate]):
    model = File

    # The profile this service stores new files under when a call selects none. A module
    # that owns its store binds it by subclassing (``storage_profile = "azure-invoices"``)
    # — the profile is code-side vocabulary, never client input; the backend it names is
    # installed at the composition root (register_storage_backend).
    storage_profile: ClassVar[str] = DEFAULT_STORAGE_PROFILE

    def store(
        self,
        session: Session,
        *,
        filename: str,
        content_type: str,
        source: BinaryIO,
        profile: str | None = None,
        max_bytes: int | None = None,
    ) -> File:
        """Persist one uploaded file: bytes into the profile's backend, metadata into the DB.

        The deployment's content-type allowlist is checked **first** (a disallowed type
        refuses with a typed 415 before any byte lands — enforced here in the chokepoint
        so a programmatic caller cannot bypass the router, ADR 0068), then the profile
        resolves **fail-closed** (an unregistered profile refuses before any byte lands
        anywhere), then the upload's head is **magic-byte sniffed** (a declared type whose
        well-known signature the bytes lack refuses with a typed 415 — ADR 0076; the peeked
        bytes are replayed into the stream so the stored blob is byte-exact), then *source*
        is **streamed** into the backend under a
        fresh server-generated key through a :class:`_DigestingReader` that hashes and
        counts the bytes as they flow and refuses the instant they exceed *max_bytes* (a
        streamed size cap — the whole upload is never held in memory). The metadata row —
        stamped with the profile so every later read / delete routes to the store that holds
        the bytes, and with the streamed size + digest — is then created through the audited
        ``BaseService`` chokepoint (stamping ``owner_id`` from the request actor). The blob
        ``put`` runs **inside** the compensation guard, so an over-cap upload (or a failed
        row write) deletes the partial blob before the error propagates — keeping "a
        committed row always has its bytes; a failed upload leaves nothing behind" true.
        The profile is selected per call (``profile=``) or per service (the
        ``storage_profile`` class default), never by a client.
        """
        _ensure_content_type_allowed(content_type)
        selected = profile if profile is not None else type(self).storage_profile
        backend = resolve_storage_backend(selected)
        # Magic-byte sniff (ADR 0076): peek the head, refuse a declared type whose
        # known signature the bytes lack — before any byte lands in the backend.
        head = source.read(_SNIFF_LEN)
        _ensure_bytes_match_declared_type(content_type, head)
        key = _new_storage_key()
        reader = _DigestingReader(_PrefixedReader(head, source), max_bytes)
        try:
            backend.put(key, reader)
            return self.create(
                session,
                FileCreate(
                    filename=filename,
                    content_type=content_type,
                    size=reader.size,
                    sha256=reader.hexdigest(),
                    storage_key=key,
                    storage_profile=selected,
                ),
            )
        except Exception:
            backend.delete(key)
            raise

    def open_stream(
        self, session: Session, file_id: uuid.UUID
    ) -> tuple[File, BinaryIO]:
        """The metadata row plus a readable stream of its bytes; a typed 404 if either is gone.

        ``get`` honors the framework row scope (soft-delete / registered predicates), so an
        invisible row 404s before any storage I/O. The stream comes from the backend the
        **row itself** names (``storage_profile``) — never a process-wide current backend, so
        a later re-wiring can never read the wrong store. A row whose blob has vanished from
        its backend maps to the same typed 404 (never a raw backend stack trace). The caller
        owns the returned stream and must close it (the download route iterates then closes
        it; :meth:`load` reads and closes it).
        """
        row = self.get(session, file_id)
        try:
            stream = resolve_storage_backend(row.storage_profile).open(row.storage_key)
        except FileNotFoundError as exc:
            raise NotFoundError(
                "The file's content is no longer available.",
                log_context={"file_id": str(file_id)},
            ) from exc
        return row, stream

    def load(self, session: Session, file_id: uuid.UUID) -> tuple[File, bytes]:
        """The metadata row plus its full bytes — a buffered convenience over :meth:`open_stream`.

        Used by the serve-through delegation read (:meth:`load_for`); the streamed download
        route uses :meth:`open_stream` directly so a large file never lands in memory whole.
        """
        row, stream = self.open_stream(session, file_id)
        try:
            return row, stream.read()
        finally:
            stream.close()

    def load_for(
        self, session: Session, referencing: SQLModel, column: str
    ) -> tuple[File, bytes]:
        """Serve a file through an already-authorized referencing row (ADR 0057).

        The serve-through delegation read: the caller loaded *referencing* through its
        **own** service (so that row's policy + row scope + per-row gate already decided
        visibility), and this helper follows the row's **declared** reference to the
        bytes. Fail-closed twice: a *column* not declared with
        :func:`~terp.capabilities.files.FileRef` raises
        :class:`~terp.capabilities.files.UndeclaredFileReferenceError` (delegation flows
        only through declared references — the runtime half of the
        ``no_raw_file_references`` rule), and an empty reference is a typed 404. The
        delegation widens access to exactly one already-authorized row's file — never a
        blanket grant.
        """
        if not is_file_reference(type(referencing), column):
            raise UndeclaredFileReferenceError(
                log_context={
                    "model": type(referencing).__name__,
                    "column": column,
                }
            )
        file_id = getattr(referencing, column)
        if file_id is None:
            raise NotFoundError(
                "The record references no file.",
                log_context={
                    "model": type(referencing).__name__,
                    "column": column,
                },
            )
        return self.load(session, file_id)

    def remove(self, session: Session, file_id: uuid.UUID) -> None:
        """Delete a file: its bytes and its metadata row as one atomic, owner-gated unit.

        Delegates to the audited ``delete`` chokepoint; the blob removal is folded into
        that same transaction by :meth:`_after_write` (below). The kernel authorizes the
        per-row write **first** (a caller who may not delete the row is refused before any
        byte I/O), and the row — which alone carries the ``storage_key`` — is destroyed
        **only after** its bytes are gone: if the backend delete fails the whole unit rolls
        back, so the row survives and the delete stays **retryable by the same id** (never
        the silent, unretryable orphan a post-commit byte delete would leave, whose key
        died with the row and whose id now 404s). Blob delete is idempotent, so a replay is
        a safe no-op.
        """
        self.delete(session, file_id)

    def _after_write(
        self, session: Session, entity: File, action: AuditAction
    ) -> None:
        """Fold a deleted file's blob removal into its row delete's own transaction.

        The kernel calls this inside the write's unit of work — for a delete, *after* the
        per-row owner gate and *before* the row delete is staged and committed. Removing
        the bytes here (rather than after the commit) is what makes the two-store delete
        atomic and retryable: the backend resolves fail-closed first (an unregistered
        profile refuses before any byte I/O), and if the delete fails the exception aborts
        the whole unit, so the metadata row is not destroyed while its bytes remain — the
        orphan-free, id-retryable guarantee. Create / update writes carry no blob side
        effect, so they pass straight through.
        """
        super()._after_write(session, entity, action)
        if action is AuditAction.DELETED:
            resolve_storage_backend(entity.storage_profile).delete(entity.storage_key)


__all__ = [
    "ContentTypeMismatchError",
    "FileService",
    "UnsupportedContentTypeError",
    "active_allowed_content_types",
    "configure_allowed_content_types",
    "reset_allowed_content_types",
]
