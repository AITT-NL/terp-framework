"""The S3 adapter: a file's bytes in an S3 bucket, handed out by a presigned URL (ADR 0201).

One class per provider, one instance per profile (ADR 0057): the composition root builds the
SDK's own client — ``boto3.client("s3", ...)`` with the credentials, region and, for an
S3-compatible store, the ``endpoint_url`` of the deployment — names the bucket, and registers
the adapter under a profile::

    register_storage_backend("media", S3Storage(boto3.client("s3"), bucket="app-media"))

The adapter imports nothing from the SDK: every error it maps is a class the client carries,
so the module loads without the ``terp-cap-files[s3]`` extra, and the extra is what makes a
client. ``put`` streams through the SDK's managed upload, ``open`` returns the SDK's response
body (a readable, non-seekable stream the router reads forward), ``delete`` is the provider's
own idempotent delete, and ``link`` is a presigned ``GET`` carrying the download's media type
and disposition as response-header parameters, so the store tells a client the same thing the
API would. Nothing here decides who may read: the service asks for a link only after the
checks a download passes.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, BinaryIO

from terp.capabilities.files.links import link_ttl
from terp.capabilities.files.storage import FileStorageError, StorageBackend


class S3Storage(StorageBackend):
    """Blobs in one S3 bucket, through the SDK's S3 client the composition root built.

    *client* is a ``boto3`` S3 client (any S3-compatible endpoint it was built for) and
    *bucket* the bucket every key of this profile lives in. A client that is not S3's is
    refused at construction, so a mis-wired composition root fails at boot.
    """

    def __init__(self, client: Any, *, bucket: str) -> None:
        if not bucket:
            raise ValueError("an S3 storage adapter needs the name of its bucket")
        exceptions = getattr(client, "exceptions", None)
        not_found = getattr(exceptions, "NoSuchKey", None)
        client_error = getattr(exceptions, "ClientError", None)
        if not_found is None or client_error is None:
            raise ValueError(
                "an S3 storage adapter takes the SDK's S3 client (boto3.client('s3', ...))"
            )
        self._client = client
        self._bucket = bucket
        self._not_found: type[Exception] = not_found
        self._client_error: type[Exception] = client_error

    def _failed(self, operation: str, key: str, exc: Exception) -> FileStorageError:
        return FileStorageError(
            log_context={
                "operation": operation,
                "bucket": self._bucket,
                "key": key,
                "error": str(exc),
            }
        )

    def put(self, key: str, source: BinaryIO) -> None:
        try:
            self._client.upload_fileobj(source, self._bucket, key)
        except self._client_error as exc:
            raise self._failed("put", key, exc) from exc

    def open(self, key: str) -> BinaryIO:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        except self._not_found as exc:
            raise FileNotFoundError(key) from exc
        except self._client_error as exc:
            raise self._failed("open", key, exc) from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except self._client_error as exc:
            raise self._failed("delete", key, exc) from exc

    def link(
        self, key: str, *, ttl: timedelta, content_type: str, disposition: str
    ) -> str | None:
        """A presigned ``GET`` for *key*, good for *ttl* (bounded like every link)."""
        lifetime = link_ttl(ttl)
        return self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentType": content_type,
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=int(lifetime.total_seconds()),
        )


__all__ = ["S3Storage"]
