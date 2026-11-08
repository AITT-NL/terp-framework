"""The S3 adapter: a file's bytes in an S3 bucket, handed out by a presigned URL (ADR 0201).

One class per provider, one instance per profile (ADR 0057): the composition root builds the
SDK's own client — ``boto3.client("s3", ...)`` with the credentials, region and, for an
S3-compatible store, the ``endpoint_url`` of the deployment — names the bucket, and registers
the adapter under a profile::

    register_storage_backend("media", S3Storage(boto3.client("s3"), bucket="app-media"))

The module imports nothing from the SDK, so it loads without the ``terp-cap-files[s3]`` extra,
and the extra is what makes a client. The errors it maps are the classes the client carries and
botocore's own base error, which a refused connection or a timeout raises, imported when an
adapter is built: without the extra that fails at boot, with the install line. ``put`` streams through the SDK's managed upload, ``open`` returns the SDK's response
body (a readable, non-seekable stream the router reads forward), ``open_range`` asks the store
for the one range a ``Range`` request names, so a seek far into a large object reads only the
bytes it serves, ``delete`` is the provider's
own idempotent delete, and ``link`` is a presigned ``GET`` carrying the download's media type
and disposition as response-header parameters, so the store tells a client the same thing the
API would. Nothing here decides who may read: the service asks for a link only after the
checks a download passes.

A URL signed with temporary credentials (a role's, an instance profile's, an SSO session's)
stops working when they expire, whatever its own expiry says. So ``link`` signs only when the
credentials the client signs with outlive the link; otherwise it hands out none, and the API
serves the bytes behind an app-signed link for the whole lifetime. A deployment whose links
should come from the store gives its role a session longer than its longest link.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, BinaryIO, Final

from terp.capabilities.files.links import link_ttl
from terp.capabilities.files.storage import (
    FileStorageError,
    StorageBackend,
    StorageSdkMissingError,
)

#: How long the signing credentials must outlast a link: a clock a little behind the store's
#: never hands out a link the store stops honouring before its stated expiry.
_CREDENTIAL_SKEW: Final[timedelta] = timedelta(minutes=1)


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
        try:
            from botocore.exceptions import BotoCoreError
        except ImportError as exc:
            raise StorageSdkMissingError(
                "The S3 storage adapter needs the 'boto3' package — "
                "install the terp-cap-files[s3] extra."
            ) from exc
        self._client = client
        self._bucket = bucket
        self._not_found: type[Exception] = not_found
        # A ClientError is the store's answer; a BotoCoreError is a connection refused, a
        # timeout or credentials that could not be read. Either is the typed 502.
        self._failures: tuple[type[Exception], ...] = (client_error, BotoCoreError)

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
        except self._failures as exc:
            raise self._failed("put", key, exc) from exc

    def open(self, key: str) -> BinaryIO:
        return self._get(key)

    def open_range(self, key: str, *, offset: int, length: int) -> BinaryIO:
        """*length* bytes of *key* from *offset*, read by the store: one ranged ``GET``."""
        return self._get(key, Range=f"bytes={offset}-{offset + length - 1}")

    def _get(self, key: str, **part: str) -> BinaryIO:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key, **part)["Body"]
        except self._not_found as exc:
            raise FileNotFoundError(key) from exc
        except self._failures as exc:
            raise self._failed("open", key, exc) from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except self._failures as exc:
            raise self._failed("delete", key, exc) from exc

    def link(
        self, key: str, *, ttl: timedelta, content_type: str, disposition: str
    ) -> str | None:
        """A presigned ``GET`` for *key*, good for *ttl* (bounded like every link), or ``None``
        where the credentials it would be signed with expire first."""
        lifetime = link_ttl(ttl)
        try:
            if not self._signing_outlives(lifetime):
                return None
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
        except self._failures as exc:
            raise self._failed("link", key, exc) from exc

    def _signing_outlives(self, lifetime: timedelta) -> bool:
        """Whether the credentials this client signs with are valid until a link signed now
        for *lifetime* expires.

        Long-term keys carry no session token, and a URL they sign lives its own expiry. A
        session token's credentials are judged by their expiry, read after the credentials
        are refreshed if they were about to lapse, and before the URL is signed, so the
        credentials that sign it are never older than the ones judged. A token whose expiry
        cannot be read, and a client whose credentials cannot be read at all, sign nothing.
        botocore reads a client's credentials only through ``_get_credentials``; were it
        gone, links would come from the API, never from credentials nobody judged.
        """
        read = getattr(self._client, "_get_credentials", None)
        credentials = read() if callable(read) else None
        if credentials is None:
            return False
        if not credentials.get_frozen_credentials().token:
            return True
        refresh_needed = getattr(credentials, "refresh_needed", None)
        return callable(refresh_needed) and not refresh_needed(
            refresh_in=(lifetime + _CREDENTIAL_SKEW).total_seconds()
        )


__all__ = ["S3Storage"]
