"""The Azure Blob adapter: a file's bytes in a container, handed out by a SAS (ADR 0201).

One class per provider, one instance per profile (ADR 0057): the composition root builds the
SDK's ``ContainerClient`` with the credential it chooses and registers the adapter under a
profile name::

    register_storage_backend("media", AzureBlobStorage(container))

``put`` / ``open`` / ``delete`` are the port's streaming contract over the container. ``link``
is a read-only blob SAS carrying the download's media type and disposition (``rsct`` and
``rscd``), signed one of two ways: with a **user-delegation key** when a ``BlobServiceClient``
authenticated by an Entra credential is given as ``delegation`` (the key is requested once,
kept for a day and replaced before a link could outlive it), or with the **account key** when
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
from threading import Lock
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, BinaryIO, Final

from terp.capabilities.files.links import LINK_TTL_MAX, link_ttl
from terp.capabilities.files.storage import (
    FileStorageError,
    StorageBackend,
    StorageSdkMissingError,
)

if TYPE_CHECKING:  # the SDK is an extra: names only, never an import at load time
    from azure.storage.blob import BlobServiceClient, ContainerClient, UserDelegationKey

#: How long a user-delegation key is requested for: the longest link (``LINK_TTL_MAX``) plus
#: an hour, so every link signed under a key expires before the key does, and a key is
#: replaced at most once a day under steady use.
_DELEGATION_KEY_LIFETIME: Final[timedelta] = LINK_TTL_MAX + timedelta(hours=1)

#: The key's validity starts this much before now, so a clock a little ahead of the service's
#: never signs a link the service reads as not yet valid.
_DELEGATION_KEY_SKEW: Final[timedelta] = timedelta(minutes=5)


def _now() -> datetime:
    return datetime.now(UTC)


def _sdk() -> tuple[Any, Any, Any, Any]:
    """The four names the adapter needs from the extra; fail closed, with the remedy, without it."""
    try:
        from azure.core.exceptions import AzureError, ResourceNotFoundError
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas
    except ImportError as exc:
        raise StorageSdkMissingError(
            "The Azure Blob storage adapter needs the 'azure-storage-blob' package — "
            "install the terp-cap-files[azure] extra."
        ) from exc
    return AzureError, ResourceNotFoundError, BlobSasPermissions, generate_blob_sas


class _DownloadStream(io.RawIOBase):
    """The SDK's downloader as a readable binary stream: it reads, but is no file object."""

    def __init__(self, downloader: Any) -> None:
        super().__init__()
        self._downloader = downloader

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        data = self._downloader.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


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
        self._errors, self._not_found, self._permissions, self._generate_sas = _sdk()
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
        try:
            downloader = self._container.download_blob(key)
        except self._not_found as exc:
            raise FileNotFoundError(key) from exc
        except self._errors as exc:
            raise self._failed("open", key, exc) from exc
        return io.BufferedReader(_DownloadStream(downloader))

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
        return f"{self._container.get_blob_client(key).url}?{sas}"

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
