"""The Azure Blob adapter: a file's bytes in a container, handed out by a SAS (ADR 0201).

One class per provider, one instance per profile (ADR 0057): the composition root builds the
SDK's ``ContainerClient`` with the credential it chooses and registers the adapter under a
profile name::

    register_storage_backend("media", AzureBlobStorage(container))

``put`` / ``open`` / ``delete`` are the port's streaming contract over the container. A blob is
read one bounded window per request, as the stream is read, rather than through the SDK's own
downloader, which fetches its first 32 MiB before it returns: so ``open`` costs nothing until it
is read, and ``open_range`` costs the range a ``Range`` request names. ``link``
is a read-only blob SAS carrying the download's media type and disposition (``rsct`` and
``rscd``), signed one of two ways: with a **user-delegation key** when a ``BlobServiceClient``
authenticated by an Entra credential is given as ``delegation`` (the key is requested for
twice the longest link and replaced before a link could outlive it, so under steady use it
is replaced at most once a day), or with the **account key** when
the container client itself was built with one. A container client that holds neither — a
token credential without a delegating service client, a SAS — gets no link, and the API serves
the bytes itself. Nothing here decides who may read: the service asks for a link only after
the checks a download passes.

The SDK is imported when an adapter is built, never when this module loads, so an app without
the ``terp-cap-files[azure]`` extra pays nothing for it and a composition root that registers
the adapter without the extra fails at boot, with the install line.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from threading import Lock
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, BinaryIO, Final
from urllib.parse import urlsplit

from terp.capabilities.files.links import LINK_TTL_MAX, link_ttl
from terp.capabilities.files.storage import (
    FileStorageError,
    StorageBackend,
    StorageSdkMissingError,
)

if TYPE_CHECKING:  # the SDK is an extra: names only, never an import at load time
    from azure.storage.blob import BlobServiceClient, ContainerClient, UserDelegationKey

#: How long a user-delegation key is requested for: twice the longest link (``LINK_TTL_MAX``),
#: well inside the seven days the service allows. A key is replaced when the next link would
#: outlive it, so every link expires before its key does, and a steady stream of even the
#: longest links replaces the key once a day, shorter links less often.
_DELEGATION_KEY_LIFETIME: Final[timedelta] = 2 * LINK_TTL_MAX

#: The key's validity starts this much before now, so a clock a little ahead of the service's
#: never signs a link the service reads as not yet valid.
_DELEGATION_KEY_SKEW: Final[timedelta] = timedelta(minutes=5)

#: The most one request reads of a blob: the SDK's own chunk size, and all a stream holds.
_WINDOW_BYTES: Final[int] = 4 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(UTC)


def _sdk() -> tuple[Any, Any, Any, Any, Any]:
    """The five names the adapter needs from the extra; fail closed, with the remedy, without it."""
    try:
        from azure.core import MatchConditions
        from azure.core.exceptions import AzureError, ResourceNotFoundError
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas
    except ImportError as exc:
        raise StorageSdkMissingError(
            "The Azure Blob storage adapter needs the 'azure-storage-blob' package — "
            "install the terp-cap-files[azure] extra."
        ) from exc
    return AzureError, ResourceNotFoundError, BlobSasPermissions, generate_blob_sas, MatchConditions


class _Windows(io.RawIOBase):
    """A blob's bytes from *start* up to *end*, one window per request, fetched as they are read.

    *first* is a window already read from *start*. *fetch* reads the window at an offset; it
    names the blob's ETag, so a blob replaced between two windows fails the read rather than
    splicing two versions into one body. A window shorter than asked is the blob's end.
    """

    def __init__(
        self, fetch: Callable[[int, int], bytes], start: int, end: int, first: bytes = b""
    ) -> None:
        super().__init__()
        self._fetch = fetch
        self._next = start + len(first)
        self._end = end
        self._window = memoryview(first)

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        if not self._window and self._next < self._end:
            asked = min(_WINDOW_BYTES, self._end - self._next)
            data = self._fetch(self._next, asked)
            self._next += len(data)
            if len(data) < asked:
                self._end = self._next
            self._window = memoryview(data)
        size = min(len(buffer), len(self._window))
        buffer[:size] = self._window[:size]
        self._window = self._window[size:]
        return size


class AzureBlobStorage(StorageBackend):
    """Blobs in one container, through the SDK's ``ContainerClient`` the composition root built.

    *container* holds every key of this profile; *delegation* is a ``BlobServiceClient`` of
    the same account, authenticated by an Entra credential, that links are signed through
    with user-delegation keys. Without it, links are signed with the account key when the
    container client carries one, and not minted at all otherwise.
    """

    def __init__(
        self, container: ContainerClient, *, delegation: BlobServiceClient | None = None
    ) -> None:
        self._errors, self._not_found, self._permissions, self._generate_sas, self._match = _sdk()
        self._container = container
        self._delegation = delegation
        self._key: UserDelegationKey | None = None
        self._key_expires_at = datetime.min.replace(tzinfo=UTC)
        self._lock = Lock()

    def _failed(self, operation: str, key: str, exc: Exception) -> FileStorageError:
        return FileStorageError(
            log_context={
                "operation": operation,
                "container": self._container.container_name,
                "key": key,
                "error": str(exc),
            }
        )

    def put(self, key: str, source: BinaryIO) -> None:
        try:
            self._container.upload_blob(name=key, data=source, overwrite=True)
        except self._errors as exc:
            raise self._failed("put", key, exc) from exc

    def open(self, key: str) -> BinaryIO:
        """*key*'s bytes: its properties are read now, so a vanished blob is a ``FileNotFoundError``
        here, and its first window when the stream is first read."""
        try:
            properties = self._container.get_blob_client(key).get_blob_properties()
        except self._not_found as exc:
            raise FileNotFoundError(key) from exc
        except self._errors as exc:
            raise self._failed("open", key, exc) from exc
        return self._stream(key, properties.etag, 0, properties.size)

    def open_range(self, key: str, *, offset: int, length: int) -> BinaryIO:
        """*length* bytes of *key* from *offset*: the first window is read now, the rest as read."""
        asked = min(_WINDOW_BYTES, length)
        try:
            downloader = self._container.download_blob(key, offset=offset, length=asked)
            first = downloader.readall()
        except self._not_found as exc:
            raise FileNotFoundError(key) from exc
        except self._errors as exc:
            raise self._failed("open", key, exc) from exc
        end = offset + length if len(first) == asked else offset + len(first)
        return self._stream(key, downloader.properties.etag, offset, end, first)

    def _stream(
        self, key: str, etag: str, start: int, end: int, first: bytes = b""
    ) -> BinaryIO:
        def fetch(offset: int, length: int) -> bytes:
            try:
                return self._container.download_blob(
                    key,
                    offset=offset,
                    length=length,
                    etag=etag,
                    match_condition=self._match.IfNotModified,
                ).readall()
            except self._errors as exc:
                raise self._failed("open", key, exc) from exc

        return io.BufferedReader(_Windows(fetch, start, end, first))

    def delete(self, key: str) -> None:
        try:
            self._container.delete_blob(key)
        except self._not_found:
            return
        except self._errors as exc:
            raise self._failed("delete", key, exc) from exc

    def link(
        self, key: str, *, ttl: timedelta, content_type: str, disposition: str
    ) -> str | None:
        """A read-only SAS URL for *key*, good for *ttl*, or ``None`` where nothing can sign."""
        expires_at = _now() + link_ttl(ttl)
        signing = self._signing(expires_at)
        if signing is None:
            return None
        sas = self._generate_sas(
            account_name=self._container.account_name,
            container_name=self._container.container_name,
            blob_name=key,
            permission=self._permissions(read=True),
            expiry=expires_at,
            content_type=content_type,
            content_disposition=disposition,
            **signing,
        )
        # The SDK keeps the query a client was built from (a SAS URL) in the blob URL; the
        # link carries this SAS and nothing else.
        blob_url = urlsplit(self._container.get_blob_client(key).url)
        return f"{blob_url._replace(query='', fragment='').geturl()}?{sas}"

    def _signing(self, until: datetime) -> dict[str, Any] | None:
        """The key a SAS expiring at *until* is signed with: delegated, shared, or none."""
        if self._delegation is not None:
            return {"user_delegation_key": self._delegation_key(self._delegation, until)}
        account_key = getattr(self._container.credential, "account_key", None)
        if account_key:
            return {"account_key": account_key}
        return None

    def _delegation_key(self, service: BlobServiceClient, until: datetime) -> UserDelegationKey:
        """The cached user-delegation key, replaced when a link would outlive it."""
        with self._lock:
            if self._key is None or self._key_expires_at < until:
                now = _now()
                expires_at = now + _DELEGATION_KEY_LIFETIME
                try:
                    self._key = service.get_user_delegation_key(
                        now - _DELEGATION_KEY_SKEW, expires_at
                    )
                except self._errors as exc:
                    raise self._failed("delegation_key", "", exc) from exc
                self._key_expires_at = expires_at
            return self._key


__all__ = ["AzureBlobStorage"]
