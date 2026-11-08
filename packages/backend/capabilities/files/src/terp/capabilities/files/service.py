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
* :meth:`FileService.open_stream` / :meth:`FileService.load` — the quarantine gate and
  the scope-honoring ``get``
  resolves the metadata (so an invisible row 404s before any storage I/O), then a readable
  stream (``open_stream``, for the streamed download) or the full bytes (``load``, a
  buffered convenience for the serve-through read) are fetched from the backend the **row
  itself** names; a missing blob maps to a typed 404 rather than a stack trace. The two
  halves are :meth:`FileService.servable` and :meth:`FileService.open_content`, which the
  download routes call apart, so a ``Range`` request asks the store for its range alone.
* :meth:`FileService.load_for` — the serve-through delegation read (ADR 0057): serve a
  file through an already-authorized referencing row, fail-closed on any column not
  declared with :func:`~terp.capabilities.files.FileRef`.
* :meth:`FileService.link` / :meth:`FileService.link_for` /
  :meth:`FileService.open_link_stream` — a short-lived link to a file's bytes, minted
  where a download is authorized (ADR 0201): the same scope and quarantine checks, then
  the row's own backend signs a URL, or the capability seals an app-signed token that
  ``open_link_stream`` opens for the public route, re-checking the verdict first.
* :meth:`FileService.remove` — the delete folds both stores into **one** owner-gated,
  audited transaction (:meth:`FileService._after_write`): the kernel authorizes the
  per-row write first (a caller who may not delete the row never reaches the bytes), then
  the profile's backend resolves fail-closed and the blob is removed *before* the row
  delete commits — so a backend failure rolls the whole unit back (the row, which alone
  holds the key, survives and the delete stays retryable by id) and a committed delete
  never leaves an orphan blob behind.

What an upload may claim to be — the content-type allowlist (ADR 0068) and the magic-byte
check (ADR 0076) — lives in :mod:`terp.capabilities.files.content_types`; ``store`` is the
chokepoint that applies both before any byte lands.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import BinaryIO, ClassVar

from sqlmodel import Session, SQLModel

from terp.core import (
    AuditAction,
    BaseService,
    NotFoundError,
    ValidationFailedError,
)

from terp.capabilities.files.content_types import (
    SNIFF_LEN,
    ContentTypeMalformedError,
    ContentTypeMismatchError,
    UnsupportedContentTypeError,
    active_allowed_content_types,
    configure_allowed_content_types,
    reset_allowed_content_types,
    ensure_bytes_match_declared_type,
    ensure_content_type_allowed,
    ensure_one_media_type,
    served_media_type,
)
from terp.capabilities.files.links import (
    SIGNED_LINK_PATH,
    FileLink,
    content_disposition,
    inline_allowed,
    link_ttl,
    open_link,
    seal_link,
)
from terp.capabilities.files.models import File
from terp.capabilities.files.references import (
    UndeclaredFileReferenceError,
    is_file_reference,
)
from terp.capabilities.files.scanning import ScanSubject, ensure_servable, scan
from terp.capabilities.files.schemas import FileCreate, FileUpdate
from terp.capabilities.files.storage import (
    DEFAULT_STORAGE_PROFILE,
    resolve_storage_backend,
)


def _new_storage_key() -> str:
    """A fresh opaque blob address: UUID-derived, two-level sharded, never client data."""
    token = uuid.uuid4().hex
    return f"{token[:2]}/{token}"


class _PrefixedReader:
    """Replays an already-peeked *prefix* ahead of the remaining *source* stream.

    The sniff check (:func:`ensure_bytes_match_declared_type`) consumes the first
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

        The deployment's scanner (``scanning``) then sees the **stored** bytes — what a
        download would actually hand out — and its verdict is stamped onto the row. A
        rejected upload still returns a row: the bytes stay in quarantine, flagged and
        unservable, because an operator needs to know what arrived and the uploader is
        told by ``scan_state`` on the response. With no scanner registered the verdict
        is ``not_scanned`` and nothing about this path changes.
        """
        ensure_one_media_type(content_type)
        ensure_content_type_allowed(content_type)
        selected = profile if profile is not None else type(self).storage_profile
        backend = resolve_storage_backend(selected)
        # Magic-byte sniff (ADR 0076): peek the head, refuse a declared type whose
        # known signature the bytes lack — before any byte lands in the backend.
        head = source.read(SNIFF_LEN)
        ensure_bytes_match_declared_type(content_type, head)
        key = _new_storage_key()
        reader = _DigestingReader(_PrefixedReader(head, source), max_bytes)
        try:
            backend.put(key, reader)
            # Scanned from the STORED bytes, not from the request stream: the scanner
            # must see what a later download would hand out, and the upload stream has
            # been consumed by the digesting copy above in any case. It is handed an
            # opener rather than the bytes so a scanner needing only a head can stop
            # early, on a path that has taken care never to hold an upload whole.
            verdict = scan(
                ScanSubject(
                    filename=filename,
                    content_type=content_type,
                    size=reader.size,
                    sha256=reader.hexdigest(),
                    open_stream=lambda: backend.open(key),
                )
            )
            return self.create(
                session,
                FileCreate(
                    filename=filename,
                    content_type=content_type,
                    size=reader.size,
                    sha256=reader.hexdigest(),
                    storage_key=key,
                    storage_profile=selected,
                    scan_state=verdict,
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
        invisible row 404s before any storage I/O, and a **quarantined** row is refused
        immediately after — here rather than on the download route, so the serve-through
        delegation read and any programmatic ``load`` are covered by the same decision.
        Rejected bytes are unreachable through every path this capability owns, not only
        the one with a URL. The stream comes from the backend the
        **row itself** names (``storage_profile``) — never a process-wide current backend, so
        a later re-wiring can never read the wrong store. A row whose blob has vanished from
        its backend maps to the same typed 404 (never a raw backend stack trace). The caller
        owns the returned stream and must close it (the download route iterates then closes
        it; :meth:`load` reads and closes it).
        """
        row = self.servable(session, file_id)
        return row, self.open_content(row)

    def servable(self, session: Session, file_id: uuid.UUID) -> File:
        """The row of a file whose bytes may be served to this caller; typed errors otherwise.

        ``get`` honours the row scope, so an invisible row is a 404, and a quarantined one is
        refused: the checks :meth:`open_stream` makes, without opening anything yet.
        """
        row = self.get(session, file_id)
        ensure_servable(row.scan_state)
        return row

    def open_content(self, row: File, part: tuple[int, int] | None = None) -> BinaryIO:
        """A stream of *row*'s bytes: all of them, or the *part* ``(first, last)`` inclusive.

        A part is read through the backend's ``open_range``, so a store that reads a range
        itself serves only that range (ADR 0201). The quarantine verdict is checked again
        here, so a row that reached this method another way is still refused. A blob gone
        from its backend is the typed 404 :meth:`open_stream` gives; the caller closes the
        stream.
        """
        ensure_servable(row.scan_state)
        backend = resolve_storage_backend(row.storage_profile)
        try:
            if part is None:
                return backend.open(row.storage_key)
            first, last = part
            if not 0 <= first <= last:
                raise ValueError(f"a part of a file runs from its first byte to its last: {part}")
            return backend.open_range(row.storage_key, offset=first, length=last - first + 1)
        except FileNotFoundError as exc:
            raise NotFoundError(
                "The file's content is no longer available.",
                log_context={"file_id": str(row.id)},
            ) from exc

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

    def link(
        self,
        session: Session,
        file_id: uuid.UUID,
        *,
        ttl: timedelta | None = None,
        inline: bool = False,
    ) -> FileLink:
        """A short-lived link to the file's bytes, minted where a download is authorized (ADR 0201).

        The same checks :meth:`open_stream` makes come first: ``get`` honours the row scope,
        so an invisible row is a 404 before any store is asked, and a quarantined row is
        refused. Then the backend the **row itself** names is asked for a link; a backend
        that hands out none (the local adapter, a store that cannot sign) gets an
        app-signed one instead: a sealed token the capability's own public route serves,
        with ``Range`` support. *ttl* is bounded by :data:`~terp.capabilities.files.links.LINK_TTL_MAX`;
        *inline* is honoured only for a type a browser renders without running it, so a
        stored HTML page is an attachment whatever was asked.
        """
        row = self.get(session, file_id)
        ensure_servable(row.scan_state)
        lifetime = link_ttl(ttl)
        expires_at = datetime.now(UTC) + lifetime
        shown_inline = inline and inline_allowed(row.content_type)
        url = resolve_storage_backend(row.storage_profile).link(
            row.storage_key,
            ttl=lifetime,
            content_type=served_media_type(row.content_type),
            disposition=content_disposition(row.filename, inline=shown_inline),
        )
        if url is None:
            url = f"{SIGNED_LINK_PATH}/{seal_link(row.id, expires_at, inline=shown_inline)}"
        return FileLink(url=url, expires_at=expires_at)

    def link_for(
        self,
        session: Session,
        referencing: SQLModel,
        column: str,
        *,
        ttl: timedelta | None = None,
        inline: bool = False,
    ) -> FileLink:
        """A link through an already-authorized referencing row: the serve-through form of :meth:`link`.

        Mirrors :meth:`load_for` (ADR 0057): the caller loaded *referencing* through its own
        service, so that row's policy and scope already decided visibility; this follows the
        row's **declared** reference (fail-closed on a column not declared with ``FileRef``,
        a typed 404 on an empty one) and mints the link for exactly that one file.
        """
        if not is_file_reference(type(referencing), column):
            raise UndeclaredFileReferenceError(
                log_context={"model": type(referencing).__name__, "column": column}
            )
        file_id = getattr(referencing, column)
        if file_id is None:
            raise NotFoundError(
                "The record references no file.",
                log_context={"model": type(referencing).__name__, "column": column},
            )
        return self.link(session, file_id, ttl=ttl, inline=inline)

    def open_link_stream(self, session: Session, token: str) -> tuple[File, BinaryIO, bool]:
        """The row, its stream and whether to show it inline, for a live app-signed *token*.

        A token the link domain cannot open, one whose claims are not a link's, and an
        expired one are all the same typed 404, which says nothing about which it was. A
        live token goes through :meth:`open_stream` again: the row must still exist and
        still be servable, because a scan verdict can change after a link was minted. The
        public route runs with no actor, so the owner read scope does not narrow this read
        (an actor-less read is not narrowed, by that scope's own rule); the authorization
        was the mint, and the expiry bounds it.
        """
        row, inline = self.linked(session, token)
        return row, self.open_content(row), inline

    def linked(self, session: Session, token: str) -> tuple[File, bool]:
        """The servable row a live app-signed *token* names, and whether to show it inline.

        The checks :meth:`open_link_stream` makes, without opening anything yet.
        """
        opened = open_link(token)
        if opened is None:
            raise NotFoundError(
                "The link is not valid.", log_context={"reason": "link_not_honoured"}
            )
        file_id, inline = opened
        return self.servable(session, file_id), inline

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
    "ContentTypeMalformedError",
    "ContentTypeMismatchError",
    "FileService",
    "UnsupportedContentTypeError",
    "active_allowed_content_types",
    "configure_allowed_content_types",
    "reset_allowed_content_types",
]
