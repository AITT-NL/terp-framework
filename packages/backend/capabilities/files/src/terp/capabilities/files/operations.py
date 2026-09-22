"""Operation declarations for the ``files`` capability's admin-only routes.

Each route below declares what it does in plain English (ADR 0102), so a
non-technical reader can see the effect of uploading, viewing, downloading,
renaming, or deleting a stored file without having to read HTTP verbs and
paths.
"""

from __future__ import annotations

from terp.core import OperationDefinition

FILES_UPLOAD = OperationDefinition(id="files.upload_file", label="Upload a new file")
FILES_LIST = OperationDefinition(id="files.list_files", label="List every uploaded file")
FILES_GET = OperationDefinition(id="files.get_file", label="View a file's details")
FILES_DOWNLOAD = OperationDefinition(
    id="files.download_file", label="Download a file's contents"
)
FILES_UPDATE = OperationDefinition(id="files.update_file", label="Edit a file's details")
FILES_DELETE = OperationDefinition(id="files.delete", label="Delete a file")

#: Every operation this capability's routes declare, in declaration order.
#:
#: An app folds the capability into its :class:`~terp.core.OperationCatalog` by
#: splatting this (``*FILES_OPERATIONS``) rather than naming each constant, so a
#: release that adds a route here cannot refuse a ``STRICT`` app's boot (ADR 0126).
#: Held exhaustive against the router by
#: ``tests/architecture/test_capability_operations.py``.
FILES_OPERATIONS: tuple[OperationDefinition, ...] = (
    FILES_UPLOAD,
    FILES_LIST,
    FILES_GET,
    FILES_DOWNLOAD,
    FILES_UPDATE,
    FILES_DELETE,
)

__all__ = [
    "FILES_DELETE",
    "FILES_DOWNLOAD",
    "FILES_GET",
    "FILES_LIST",
    "FILES_OPERATIONS",
    "FILES_UPDATE",
    "FILES_UPLOAD",
]
