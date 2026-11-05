"""Gate for the two object-store adapters of ``terp-cap-files`` (ADR 0201).

Each adapter is driven through the SDK's own offline surface rather than a network: S3 through
``boto3``'s real client under botocore's stubber (the presigner runs for real, the wire calls
are stubbed), Azure Blob through a container-client fake whose shape is checked against the
real ``ContainerClient``, with the SDK's real SAS signer, delegation-key type and exception
classes. What is held: the port's round trip and idempotent delete on each, a vanished blob as
``FileNotFoundError`` (the service's typed 404), a provider failure as the typed 502 with the
provider's text kept in ``log_context``, a link that carries the download's media type and
disposition and expires when asked, the Azure signing precedence (delegation key, then account
key, then no link at all), the delegation key's cache and replacement, and that the service
hands out the provider's link for a row on such a profile.
"""

from __future__ import annotations

import base64
import inspect
import io
import sys
import urllib.parse
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.storage.blob import ContainerClient, StorageStreamDownloader, UserDelegationKey
from botocore.config import Config
from botocore.stub import Stubber
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from terp.core._internal.session_guard import WriteGuardedSession

from terp.capabilities.files import (
    LINK_TTL_MAX,
    AzureBlobStorage,
    FileService,
    FileStorageError,
    S3Storage,
    StorageSdkMissingError,
    register_storage_backend,
    reset_file_scanner,
    reset_storage_backend,
)
from terp.capabilities.files import azure_blob

_CONTENT = b"0123456789abcdefghijklmnopqrstuvwxyz"
_ACCOUNT_KEY = base64.b64encode(b"k" * 32).decode()
_DISPOSITION = "attachment; filename=\"a.txt\"; filename*=UTF-8''a.txt"


@pytest.fixture(autouse=True)
def _isolated_seams() -> Iterator[None]:
    reset_file_scanner()
    reset_storage_backend()
    yield
    reset_file_scanner()
    reset_storage_backend()


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with WriteGuardedSession(engine) as sess:
        yield sess
    engine.dispose()


# --------------------------------------------------------------------------- #
# S3: the real client, the wire stubbed
# --------------------------------------------------------------------------- #
def _s3_client() -> Any:
    return boto3.client(
        "s3",
        region_name="eu-west-1",
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        config=Config(signature_version="s3v4"),
    )


@pytest.fixture
def s3() -> Iterator[tuple[S3Storage, Stubber]]:
    client = _s3_client()
    with Stubber(client) as stub:
        yield S3Storage(client, bucket="media"), stub
        stub.assert_no_pending_responses()


def test_s3_refuses_a_client_that_is_not_s3_and_an_empty_bucket() -> None:
    with pytest.raises(ValueError, match="bucket"):
        S3Storage(_s3_client(), bucket="")
    with pytest.raises(ValueError, match="S3 client"):
        S3Storage(SimpleNamespace(), bucket="media")


def test_s3_round_trips_through_the_sdk_and_deletes_idempotently(s3: tuple[S3Storage, Stubber]) -> None:
    backend, stub = s3
    stub.add_response("put_object", {})
    stub.add_response("get_object", {"Body": io.BytesIO(_CONTENT)}, {"Bucket": "media", "Key": "ab/k"})
    stub.add_response("delete_object", {}, {"Bucket": "media", "Key": "ab/k"})
    stub.add_response("delete_object", {}, {"Bucket": "media", "Key": "ab/k"})

    backend.put("ab/k", io.BytesIO(_CONTENT))
    stream = backend.open("ab/k")
    assert stream.read(4) == _CONTENT[:4] and stream.read() == _CONTENT[4:]
    stream.close()
    backend.delete("ab/k")
    backend.delete("ab/k")  # the provider's delete is idempotent: the same call, no error


def test_s3_maps_a_missing_key_to_not_found_and_anything_else_to_the_typed_error(
    s3: tuple[S3Storage, Stubber],
) -> None:
    backend, stub = s3
    stub.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    with pytest.raises(FileNotFoundError):
        backend.open("gone")

    stub.add_client_error("get_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(FileStorageError) as opened:
        backend.open("ab/k")
    assert opened.value.log_context["operation"] == "open" and opened.value.log_context["key"] == "ab/k"
    assert "AccessDenied" in opened.value.log_context["error"]
    assert "AccessDenied" not in opened.value.message

    stub.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(FileStorageError) as put:
        backend.put("ab/k", io.BytesIO(_CONTENT))
    assert put.value.log_context["operation"] == "put"

    stub.add_client_error("delete_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(FileStorageError) as deleted:
        backend.delete("ab/k")
    assert deleted.value.log_context["operation"] == "delete"


def test_s3_links_with_a_presigned_get_carrying_type_disposition_and_expiry(
    s3: tuple[S3Storage, Stubber],
) -> None:
    backend, _ = s3
    url = backend.link("ab/k", ttl=timedelta(minutes=10), content_type="text/plain", disposition=_DISPOSITION)
    assert url is not None
    parts = urllib.parse.urlsplit(url)
    assert parts.scheme == "https" and "media" in (parts.netloc + parts.path) and parts.path.endswith("/ab/k")
    query = urllib.parse.parse_qs(parts.query)
    assert query["response-content-type"] == ["text/plain"]
    assert query["response-content-disposition"] == [_DISPOSITION]
    assert query["X-Amz-Expires"] == ["600"]
    assert "X-Amz-Signature" in query


def test_s3_bounds_a_link_lifetime_like_every_link(s3: tuple[S3Storage, Stubber]) -> None:
    backend, _ = s3
    with pytest.raises(ValueError):
        backend.link("ab/k", ttl=LINK_TTL_MAX + timedelta(seconds=1), content_type="text/plain", disposition="attachment")


def test_the_service_hands_out_the_provider_link_for_a_row_on_an_s3_profile(
    session: Session, s3: tuple[S3Storage, Stubber]
) -> None:
    backend, stub = s3
    register_storage_backend("s3-media", backend)
    stub.add_response("put_object", {})
    row = FileService().store(
        session, filename="a.txt", content_type="text/plain", source=io.BytesIO(_CONTENT), profile="s3-media"
    )
    link = FileService().link(session, row.id, ttl=timedelta(minutes=5))
    assert link.url.startswith("https://") and "X-Amz-Signature" in link.url
    assert row.storage_key in urllib.parse.unquote(link.url)
    assert link.expires_at <= datetime.now(UTC) + timedelta(minutes=5)


# --------------------------------------------------------------------------- #
# Azure Blob: a container fake shaped like the SDK's client, the SDK's own signer
# --------------------------------------------------------------------------- #
class _Downloader:
    """What ``download_blob`` returns: it reads in sizes, and nothing else the adapter uses."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


class _Container:
    """The slice of ``ContainerClient`` the adapter touches, over a dict."""

    account_name = "acct"
    container_name = "media"
    url = "https://acct.blob.core.windows.net/media"

    def __init__(self, credential: Any = None) -> None:
        self.credential = credential
        self.blobs: dict[str, bytes] = {}
        self.failing: HttpResponseError | None = None

    def _maybe_fail(self) -> None:
        if self.failing is not None:
            raise self.failing

    def upload_blob(self, name: str, data: Any, overwrite: bool = False) -> None:
        self._maybe_fail()
        assert overwrite, "the port overwrites an existing key"
        chunks = []
        while chunk := data.read(8):  # the SDK streams a file-like body; so does the fake
            chunks.append(chunk)
        self.blobs[name] = b"".join(chunks)

    def download_blob(self, blob: str) -> _Downloader:
        self._maybe_fail()
        if blob not in self.blobs:
            raise ResourceNotFoundError("The specified blob does not exist.")
        return _Downloader(self.blobs[blob])

    def delete_blob(self, blob: str) -> None:
        self._maybe_fail()
        if blob not in self.blobs:
            raise ResourceNotFoundError("The specified blob does not exist.")
        del self.blobs[blob]

    def get_blob_client(self, blob: str) -> Any:
        return SimpleNamespace(url=f"{self.url}/{urllib.parse.quote(blob)}")


class _DelegatingService:
    """The one call the adapter makes on a ``BlobServiceClient``: a user-delegation key."""

    def __init__(self) -> None:
        self.requests: list[tuple[datetime, datetime]] = []

    def get_user_delegation_key(self, key_start_time: datetime, key_expiry_time: datetime) -> UserDelegationKey:
        self.requests.append((key_start_time, key_expiry_time))
        key = UserDelegationKey()
        key.signed_oid = "object-id"
        key.signed_tid = "tenant-id"
        key.signed_start = key_start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        key.signed_expiry = key_expiry_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        key.signed_service = "b"
        key.signed_version = "2020-10-02"
        key.value = _ACCOUNT_KEY
        return key


def test_the_container_fake_is_shaped_like_the_sdk_client() -> None:
    """The adapter calls the SDK by these names; the fake answers to the same ones."""
    for method, parameter in (
        ("upload_blob", "name"),
        ("upload_blob", "data"),
        ("download_blob", "blob"),
        ("delete_blob", "blob"),
        ("get_blob_client", "blob"),
    ):
        assert parameter in inspect.signature(getattr(ContainerClient, method)).parameters
        assert parameter in inspect.signature(getattr(_Container, method)).parameters
    assert "size" in inspect.signature(StorageStreamDownloader.read).parameters
    real = ContainerClient("https://acct.blob.core.windows.net", "media", credential=_ACCOUNT_KEY)
    assert (real.account_name, real.container_name, real.url) == ("acct", "media", _Container.url)
    assert real.credential.account_key == _ACCOUNT_KEY  # the shared-key path reads this
    assert real.get_blob_client("ab/c d").url == _Container().get_blob_client("ab/c d").url


def test_azure_fails_closed_at_construction_without_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "azure.storage.blob", None)
    with pytest.raises(StorageSdkMissingError, match=r"terp-cap-files\[azure\]"):
        AzureBlobStorage(_Container())


def test_azure_round_trips_streams_and_deletes_idempotently() -> None:
    container = _Container()
    backend = AzureBlobStorage(container)
    backend.put("ab/k", io.BytesIO(_CONTENT))
    assert container.blobs["ab/k"] == _CONTENT
    with backend.open("ab/k") as stream:
        assert not stream.seekable()
        assert stream.read(5) == _CONTENT[:5] and stream.read() == _CONTENT[5:]
    backend.delete("ab/k")
    assert "ab/k" not in container.blobs
    backend.delete("ab/k")  # idempotent: the provider's not-found is swallowed
    with pytest.raises(FileNotFoundError):
        backend.open("ab/k")


def test_azure_maps_a_provider_failure_to_the_typed_error_with_the_text_kept_out_of_the_message() -> None:
    container = _Container()
    backend = AzureBlobStorage(container)
    container.failing = HttpResponseError("Server busy, try again")
    for operation, call in (
        ("put", lambda: backend.put("ab/k", io.BytesIO(_CONTENT))),
        ("open", lambda: backend.open("ab/k")),
        ("delete", lambda: backend.delete("ab/k")),
    ):
        with pytest.raises(FileStorageError) as failed:
            call()
        assert failed.value.log_context["operation"] == operation
        assert failed.value.log_context["container"] == "media"
        assert "Server busy" in failed.value.log_context["error"]
        assert "Server busy" not in failed.value.message


def _sas_query(url: str) -> dict[str, list[str]]:
    parts = urllib.parse.urlsplit(url)
    assert parts.scheme == "https" and parts.path == "/media/ab/k"
    return urllib.parse.parse_qs(parts.query)


def test_azure_signs_with_the_account_key_the_container_client_holds() -> None:
    backend = AzureBlobStorage(_Container(credential=SimpleNamespace(account_key=_ACCOUNT_KEY)))
    url = backend.link("ab/k", ttl=timedelta(minutes=10), content_type="text/plain", disposition=_DISPOSITION)
    assert url is not None
    query = _sas_query(url)
    assert query["sp"] == ["r"] and query["sr"] == ["b"] and "sig" in query
    assert query["rsct"] == ["text/plain"] and query["rscd"] == [_DISPOSITION]
    assert "skoid" not in query
    expiry = datetime.strptime(query["se"][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert timedelta(minutes=9) < expiry - datetime.now(UTC) <= timedelta(minutes=10)


def test_azure_signs_with_a_user_delegation_key_first_and_keeps_it_until_a_link_would_outlive_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _DelegatingService()
    # The account key is present too: delegation wins, so the key never signs anything.
    backend = AzureBlobStorage(_Container(credential=SimpleNamespace(account_key=_ACCOUNT_KEY)), delegation=service)
    first = backend.link("ab/k", ttl=timedelta(hours=1), content_type="image/png", disposition="inline")
    assert first is not None and _sas_query(first)["skoid"] == ["object-id"]
    second = backend.link("ab/k", ttl=LINK_TTL_MAX, content_type="image/png", disposition="inline")
    assert second is not None and len(service.requests) == 1  # one key signs both
    start, expiry = service.requests[0]
    assert expiry - start == azure_blob._DELEGATION_KEY_LIFETIME + azure_blob._DELEGATION_KEY_SKEW
    assert expiry - datetime.now(UTC) > LINK_TTL_MAX  # the longest link fits inside the key

    # A day later the cached key would expire before a new link: it is replaced.
    later = datetime.now(UTC) + azure_blob._DELEGATION_KEY_LIFETIME
    monkeypatch.setattr(azure_blob, "_now", lambda: later)
    third = backend.link("ab/k", ttl=timedelta(hours=1), content_type="image/png", disposition="inline")
    assert third is not None and len(service.requests) == 2


def test_azure_reports_a_failed_delegation_key_request_as_the_typed_error() -> None:
    class _Refusing:
        def get_user_delegation_key(self, key_start_time: datetime, key_expiry_time: datetime) -> UserDelegationKey:
            raise HttpResponseError("AuthorizationPermissionMismatch")

    backend = AzureBlobStorage(_Container(), delegation=_Refusing())
    with pytest.raises(FileStorageError) as failed:
        backend.link("ab/k", ttl=timedelta(hours=1), content_type="text/plain", disposition="attachment")
    assert failed.value.log_context["operation"] == "delegation_key"


def test_azure_mints_no_link_where_nothing_can_sign_so_the_api_serves_the_bytes(session: Session) -> None:
    class _TokenCredential:  # an Entra token on the container client alone: it cannot sign a SAS
        def get_token(self, *scopes: str) -> None:  # pragma: no cover - never called
            return None

    for credential in (None, _TokenCredential(), "sv=2020-10-02&sig=abc"):
        backend = AzureBlobStorage(_Container(credential=credential))
        assert backend.link("ab/k", ttl=timedelta(hours=1), content_type="text/plain", disposition="attachment") is None

    register_storage_backend("azure-media", AzureBlobStorage(_Container()))
    row = FileService().store(
        session, filename="a.txt", content_type="text/plain", source=io.BytesIO(_CONTENT), profile="azure-media"
    )
    link = FileService().link(session, row.id)
    assert link.url.startswith("/api/v1/files/link/")  # the app-signed fallback of ADR 0201


def test_azure_bounds_a_link_lifetime_like_every_link() -> None:
    backend = AzureBlobStorage(_Container(credential=SimpleNamespace(account_key=_ACCOUNT_KEY)))
    with pytest.raises(ValueError):
        backend.link("ab/k", ttl=timedelta(0), content_type="text/plain", disposition="attachment")
