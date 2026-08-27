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

__all__ = [
    "FILES_DELETE",
    "FILES_DOWNLOAD",
    "FILES_GET",
    "FILES_LIST",
    "FILES_UPDATE",
    "FILES_UPLOAD",
]
