"""The pluggable storage seam: a byte-store port + a **named-profile** backend registry.

The files capability owns all *metadata* in the platform database; the *bytes* flow through
this port (the engine-adapter pattern of ADR 0046/0048 applied to storage): a tiny
:class:`StorageBackend` ABC with exactly ``put`` / ``open`` / ``delete`` (streaming through
readable binary objects, ADR 0066) to implement, ``open_range`` for an adapter that reads a
part of a blob itself, and a registry of
**storage profiles** — named backend instances installed at the composition root
(:func:`register_storage_backend`) and resolved fail-closed by name
(:func:`resolve_storage_backend`). One provider class serves many uses: the same
S3/Azure-style adapter registered twice under two profiles (two buckets / containers) routes
different modules' bytes to different stores with no service / router / schema edit
(ADR 0057).

The ``"default"`` profile (:data:`DEFAULT_STORAGE_PROFILE`) is the shipped
:class:`LocalFilesystemStorage` reference adapter; the original single-backend seam
(:func:`set_storage_backend` / :func:`active_storage_backend` / :func:`reset_storage_backend`,
mirroring the webhook-sender seam) still works and operates on that default profile.

Resolution is **fail-closed**: an unknown profile raises
:class:`UnknownStorageProfileError` — never a silent fall-through to a different,
differently-permissioned store. Keys are **server-generated** (opaque UUID-derived, see
the service) and never client-influenceable; the local adapter still fail-closes on any
key that would escape its root directory (defense in depth against a future adapter /
key-shape change reintroducing path traversal).
"""

from __future__ import annotations

import abc
import logging
import os
import pathlib
import shutil
import tempfile
from datetime import timedelta
from typing import BinaryIO, Final

from terp.core import AppError, get_settings
from terp.core.boot_checks import register_boot_check

_logger = logging.getLogger("terp.capabilities.files")

#: How much the default :meth:`StorageBackend.open_range` reads and discards at a time, on a
#: stream that cannot seek: one bounded buffer, never the bytes before the range at once.
_SKIP_CHUNK_BYTES: Final[int] = 64 * 1024

# The profile every file rides unless a service / call selects another; also the hard cap
# mirrored by the ``File.storage_profile`` column (a profile name is code-side vocabulary,
# never client data, but the column is capped like every other str — defense in depth).
DEFAULT_STORAGE_PROFILE: Final[str] = "default"
STORAGE_PROFILE_MAX: Final[int] = 64


class FileStorageError(AppError):
    """502 — the storage backend failed to store, load, or remove a blob."""

    status_code = 502
    code = "file_storage_failed"
    default_message = "The file storage backend could not complete the operation."


class UnknownStorageProfileError(FileStorageError):
    """500 — a storage profile no backend was registered for (fail-closed, never a fallback).

    Raised by :func:`resolve_storage_backend` for an unregistered profile: routing bytes to
    a *different* store than the one named would silently change where (and under whose
    permissions) data lands, so resolution refuses instead. This is a server wiring error
    (the composition root must register every profile the app's services name), never a
    caller mistake — profiles are code-side vocabulary, not client input.
    """

    status_code = 500
    code = "storage_profile_unknown"
    default_message = "No storage backend is registered for the requested profile."


class StorageSdkMissingError(FileStorageError):
    """500 — a storage adapter was built without the provider SDK its extra installs.

    Raised by the constructor of an adapter that imports its SDK itself (the Azure Blob
    adapter, ``terp-cap-files[azure]``), so a composition root that registers it without
    the extra fails at boot with the install line, never at the first upload. The S3
    adapter takes the SDK's own client and imports nothing, so there the missing extra
    surfaces where the client is built. A wiring error, like
    :class:`UnknownStorageProfileError`: nothing a client did or can see.
    """

    status_code = 500
    code = "storage_sdk_missing"
    default_message = "A storage adapter's provider SDK is not installed."


class StorageBackend(abc.ABC):
    """The byte-store port: stream opaque blobs addressed by a server-generated key.

    Contract: ``put`` copies the readable binary *source* under *key* (overwriting an
    existing key) **streaming** — it reads the source in chunks and never materializes the
    whole blob in memory, so an adapter maps straight onto a cloud SDK's streamed upload
    (``boto3.upload_fileobj`` / Azure ``upload_blob``). ``open`` returns a readable binary
    stream positioned at the start of the blob, or raises :class:`FileNotFoundError` for an
    unknown key (the service maps it to a typed 404); the caller closes the stream.
    ``delete`` is **idempotent** (removing an unknown key is a no-op, so a compensation /
    retry can never fail on an already-gone blob). ``open_range`` has a default that works
    for every adapter; one that can read a part of a blob from its store overrides it.
    """

    @abc.abstractmethod
    def put(self, key: str, source: BinaryIO) -> None:
        """Stream *source*'s bytes under *key* (reads in chunks; never buffers the whole)."""

    @abc.abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Return a readable binary stream for *key*; raise ``FileNotFoundError`` if absent."""

    def open_range(self, key: str, *, offset: int, length: int) -> BinaryIO:
        """A readable stream of *key*'s bytes from *offset*, *length* of them (ADR 0201).

        The caller reads *length* bytes and closes the stream; raise ``FileNotFoundError``
        for an unknown key, as :meth:`open` does. The default opens the whole blob and moves
        to *offset*: by a seek where the stream can, by reading past the bytes before it where
        it cannot. An adapter whose store reads a range itself overrides it, so a range far
        into a large blob costs that range rather than every byte before it.
        """
        stream = self.open(key)
        try:
            _skip_to(stream, offset)
        except BaseException:
            stream.close()
            raise
        return stream

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        """Remove *key*'s bytes if present (idempotent: an unknown key is a no-op)."""

    def link(
        self, key: str, *, ttl: timedelta, content_type: str, disposition: str
    ) -> str | None:
        """A URL a client reads *key*'s bytes from for *ttl*, or ``None`` (ADR 0201).

        A store that signs URLs returns one that serves the bytes with *content_type* and
        the *disposition* header the download would carry, so a client is told the same by
        either path. The default, ``None``, leaves the bytes to the API: the service then
        signs a link of its own and serves them itself, with ``Range`` support. The service
        asks only after the checks a download passes, so an adapter never decides who may
        read; it decides where the bytes come from.
        """
        return None

    def boot_problem(self) -> str | None:
        """Why this process cannot use the store, or ``None`` (ADR 0218).

        Asked once by ``create_app`` before the app serves, through the boot check the files
        capability registers: a sentence here refuses the start outside ``ENVIRONMENT=local``
        and is a warning in local. It names what is wrong, where, and the remedy. The default
        is ``None``: a store behind a network adapter is not called at boot, so a slow or
        briefly unreachable provider never stops a process from starting. An adapter whose
        store the image itself must provide (a directory, a mount) overrides it.
        """
        return None

    def boot_warning(self) -> str | None:
        """Something a deployed process should be told about the store, or ``None``.

        Logged as a warning outside ``ENVIRONMENT=local``, never a refusal: for what may be
        intended on one host and a mistake on another (a root on the container's own disk).
        """
        return None


def _skip_to(stream: BinaryIO, offset: int) -> None:
    """Position *stream* at *offset*: a seek where it can, a bounded read-and-discard where not.

    A stream that ends first stops the skip, so a blob shorter than its row says gives a
    short body, which the response's length turns into a protocol error, never a hang.
    """
    seekable = getattr(stream, "seekable", None)
    if callable(seekable) and seekable():
        stream.seek(offset)
        return
    while offset > 0:
        chunk = stream.read(min(_SKIP_CHUNK_BYTES, offset))
        if not chunk:
            return
        offset -= len(chunk)


#: The remedy a refused start names: what makes the default root writable in the image the
#: template renders, and how an app rendered before template 0.35 gets it. Followed as
#: written it must leave a compose file that loads, so the volume the service mounts is
#: declared under the top-level ``volumes`` too.
_WRITABLE_ROOT_REMEDY: Final[str] = (
    "make that directory writable by the user the app runs as, and mount a named volume "
    "there so the files outlive the container. An app rendered from a template older than "
    "0.35 re-renders it (`copier update`; the volume comes only when the recorded use_files "
    "answer is true, so where it is false: `copier update --data use_files=true`), or adds "
    "what the 0.35 production profile has: `&& mkdir -p /srv/var/files && chown appuser "
    "/srv/var/files` on the `RUN useradd` line of Dockerfile.prod, and a "
    "`files-data:/srv/var/files` volume on `api` in docker-compose.prod.yml, with "
    "`files-data:` under its top-level `volumes` - see: terp guide files"
)


def _running_as() -> str:
    """The user this process runs as, for a sentence an operator reads (uid where there is one)."""
    getuid = getattr(os, "getuid", None)
    return f"uid {getuid()}" if getuid is not None else "the current user"


class LocalFilesystemStorage(StorageBackend):
    """The default reference adapter: blobs as files under one root directory.

    The root is created by the boot probe (:meth:`boot_problem`), and again on a write if
    it has gone since. Every key is resolved and verified to stay **inside** the root
    before any I/O (fail-closed: a traversal-shaped key raises :class:`FileStorageError`
    rather than touching the filesystem) — a second layer under the server-generated key
    invariant. An ``OSError`` from the filesystem is a typed :class:`FileStorageError`
    (502), its cause in ``log_context`` and never in the response; an unknown key stays a
    ``FileNotFoundError``, which the service answers with a 404.
    """

    def __init__(self, root: pathlib.Path | str) -> None:
        self._root = pathlib.Path(root).resolve()

    def boot_problem(self) -> str | None:
        """Create the root, then write and remove a probe file in it; a sentence if that fails.

        A real write, not ``os.access``: permission bits do not tell the whole truth on a
        network filesystem, under ACLs, or on a read-only mount.
        """
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self._root, prefix=".terp-boot-probe-") as probe:
                probe.write(b"probe")
                probe.flush()
        except OSError as exc:
            return (
                f"the storage root {self._root} cannot be written "
                f"({type(exc).__name__}: {exc}; the app runs as "
                f"{_running_as()}): " + _WRITABLE_ROOT_REMEDY
            )
        return None

    def boot_warning(self) -> str | None:
        """A root on the same filesystem as ``/``: in a container, not on a mounted volume."""
        anchor = pathlib.Path(self._root.anchor)
        if self._root.stat().st_dev != anchor.stat().st_dev:
            return None
        return (
            f"the storage root {self._root} is on the same filesystem as {anchor}, not on a "
            "mounted volume: in a container, the files stored there go with it at the next "
            "deploy. Mount a named volume there (see: terp guide files), or ignore this on a "
            "host that keeps its files on that disk on purpose"
        )

    def _path_for(self, key: str) -> pathlib.Path:
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise FileStorageError(
                "storage key escapes the storage root",
                log_context={"key": key},
            )
        return candidate

    def _failed(self, operation: str, key: str, exc: OSError) -> FileStorageError:
        """The typed error for a filesystem failure: the cause logged, never answered."""
        return FileStorageError(
            log_context={
                "operation": operation,
                "root": str(self._root),
                "key": key,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )

    def put(self, key: str, source: BinaryIO) -> None:
        path = self._path_for(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as destination:
                shutil.copyfileobj(source, destination)
        except OSError as exc:
            raise self._failed("put", key, exc) from exc

    def open(self, key: str) -> BinaryIO:
        path = self._path_for(key)
        try:
            return path.open("rb")
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise self._failed("open", key, exc) from exc

    def delete(self, key: str) -> None:
        path = self._path_for(key)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise self._failed("delete", key, exc) from exc


# The profile registry: named backend instances, installed at the composition root and
# resolved fail-closed by name. The "default" profile is the local reference adapter
# rooted at ./var/files; a deployment installs its own adapters — another root, or the
# same S3/Azure-style provider registered under several profiles (one per bucket /
# container / module use) — with one composition-root line each.
_DEFAULT_ROOT = pathlib.Path("var") / "files"
_backends: dict[str, StorageBackend] = {
    DEFAULT_STORAGE_PROFILE: LocalFilesystemStorage(_DEFAULT_ROOT)
}


def register_storage_backend(profile: str, backend: StorageBackend) -> None:
    """Install *backend* under the profile name *profile* (a composition-root line).

    A profile is code-side vocabulary — a stable, greppable name a service or call
    selects a store by (``"default"``, ``"azure-invoices"``, …) — never client data.
    Registering an already-registered profile replaces its backend (the same semantics
    as the original single-backend seam). The name is validated eagerly (non-empty,
    within the column cap) so a mis-wired composition root fails at boot, not at the
    first upload.
    """
    if not profile or len(profile) > STORAGE_PROFILE_MAX:
        raise ValueError(
            "a storage profile must be a non-empty name of at most "
            f"{STORAGE_PROFILE_MAX} characters"
        )
    _backends[profile] = backend


def resolve_storage_backend(profile: str) -> StorageBackend:
    """The backend registered under *profile* — fail-closed for an unknown name.

    Never falls through to another profile: routing bytes to a different store than the
    one named would silently change where (and under whose permissions) data lands.
    """
    try:
        return _backends[profile]
    except KeyError:
        raise UnknownStorageProfileError(log_context={"profile": profile}) from None


def set_storage_backend(backend: StorageBackend) -> None:
    """Install *backend* as the ``"default"`` profile (the original one-line seam)."""
    register_storage_backend(DEFAULT_STORAGE_PROFILE, backend)


def reset_storage_backend() -> None:
    """Restore the registry to just the default local adapter (the test-isolation reset)."""
    _backends.clear()
    _backends[DEFAULT_STORAGE_PROFILE] = LocalFilesystemStorage(_DEFAULT_ROOT)


def active_storage_backend() -> StorageBackend:
    """The ``"default"``-profile backend (the original single-backend accessor)."""
    return resolve_storage_backend(DEFAULT_STORAGE_PROFILE)


def storage_boot_problem() -> str | None:
    """Every registered profile's boot problem, one line each, or ``None`` (ADR 0218).

    The files capability's boot check, registered with the kernel when this module is
    imported, so ``create_app`` asks it before the app serves: outside
    ``ENVIRONMENT=local`` a profile whose store this process cannot use refuses the start.
    A profile with no problem may still carry a warning (a root on the container's own
    disk), which a deployed process logs and a local one leaves unsaid.

    Every profile registered when the app is composed is asked, so a composition root
    registers its profiles before it calls ``create_app``.
    """
    local = get_settings().ENVIRONMENT == "local"
    problems: list[str] = []
    for profile in sorted(_backends):
        backend = _backends[profile]
        problem = backend.boot_problem()
        if problem is not None:
            problems.append(f"files storage profile {profile!r}: {problem}")
            continue
        if not local:
            warning = backend.boot_warning()
            if warning is not None:
                _logger.warning("files storage profile %r: %s", profile, warning)
    return "\n".join(problems) if problems else None


register_boot_check("files_storage", storage_boot_problem)


__all__ = [
    "DEFAULT_STORAGE_PROFILE",
    "STORAGE_PROFILE_MAX",
    "FileStorageError",
    "LocalFilesystemStorage",
    "StorageBackend",
    "StorageSdkMissingError",
    "UnknownStorageProfileError",
    "active_storage_backend",
    "register_storage_backend",
    "reset_storage_backend",
    "resolve_storage_backend",
    "set_storage_backend",
    "storage_boot_problem",
]
