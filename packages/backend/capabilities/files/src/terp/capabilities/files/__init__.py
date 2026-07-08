"""terp.capabilities.files — owner-scoped file objects on a pluggable storage backend.

The last of the planned foundation capabilities (design §3.1, §6): an app stores and
retrieves **file objects** through a maintained, secure-by-default surface, with all
*metadata* owned in the platform database and the *bytes* behind a tiny storage port.

* :class:`File` (``BaseTable`` + ``OwnedMixin``) is the metadata row — name, type, size,
  digest, the server-generated ``storage_key`` addressing the bytes, and the
  ``storage_profile`` naming the backend that holds them. Both are server-side-only
  material: no Read DTO ever serializes them.
* :class:`StorageBackend` is the pluggable byte-store seam (``put`` / ``open`` /
  ``delete``, streamed through readable binary objects — ADR 0066) behind a
  **named-profile registry** (ADR 0057): the ``"default"`` profile
  is the shipped :class:`LocalFilesystemStorage` reference adapter, and a deployment
  installs any provider — another root, S3, Azure Blob, a NAS mount — under one or many
  profiles (one per container / module use) with one :func:`register_storage_backend`
  line each; resolution (:func:`resolve_storage_backend`) is fail-closed
  (:class:`UnknownStorageProfileError`). A service or call selects a store by profile
  name; a client never does.
* :func:`FileRef` declares a model column that references a stored file, and
  :meth:`FileService.load_for` is the serve-through delegation read: a module serves a
  file through its **own**, already-authorized row, fail-closed on any undeclared
  reference (:class:`UndeclaredFileReferenceError`; build-time twin: the
  ``no_raw_file_references`` rule).
* The discovered, admin-only router at ``/api/v1/files`` uploads, downloads, lists
  (``Page[T]``), renames, and deletes; ``OwnedMixin`` makes edit / delete owner-gated
  centrally in ``BaseService`` with zero module code.

It depends only on ``terp-core`` (plus the multipart parser FastAPI needs for uploads) —
never a sibling capability or a storage engine SDK.
"""

from __future__ import annotations

from terp.capabilities.files.models import File
from terp.capabilities.files.references import (
    FileRef,
    UndeclaredFileReferenceError,
    is_file_reference,
)
from terp.capabilities.files.router import (
    MAX_UPLOAD_BYTES,
    active_upload_limit,
    configure_upload_limit,
    module,
    reset_upload_limit,
    router,
)
from terp.capabilities.files.schemas import FileCreate, FileRead, FileUpdate
from terp.capabilities.files.service import (
    ContentTypeMismatchError,
    FileService,
    UnsupportedContentTypeError,
    active_allowed_content_types,
    configure_allowed_content_types,
    reset_allowed_content_types,
)
from terp.capabilities.files.storage import (
    DEFAULT_STORAGE_PROFILE,
    FileStorageError,
    LocalFilesystemStorage,
    StorageBackend,
    UnknownStorageProfileError,
    active_storage_backend,
    register_storage_backend,
    reset_storage_backend,
    resolve_storage_backend,
    set_storage_backend,
)

__all__ = [
    "DEFAULT_STORAGE_PROFILE",
    "MAX_UPLOAD_BYTES",
    "ContentTypeMismatchError",
    "File",
    "FileCreate",
    "FileRead",
    "FileRef",
    "FileService",
    "FileStorageError",
    "FileUpdate",
    "LocalFilesystemStorage",
    "StorageBackend",
    "UndeclaredFileReferenceError",
    "UnknownStorageProfileError",
    "UnsupportedContentTypeError",
    "active_allowed_content_types",
    "active_storage_backend",
    "active_upload_limit",
    "configure_allowed_content_types",
    "configure_upload_limit",
    "is_file_reference",
    "module",
    "register_storage_backend",
    "reset_allowed_content_types",
    "reset_storage_backend",
    "reset_upload_limit",
    "resolve_storage_backend",
    "router",
    "set_storage_backend",
]
