"""End-to-end slice: the files capability on the example app (ADR 0056).

Proves the real composition: an ADMIN uploads a file (multipart), the metadata row is
owner-stamped and the server-side ``storage_key`` never crosses the API boundary, the
bytes round-trip through the pluggable storage backend on download (with a sanitized
``Content-Disposition``), the list paginates, a rename is an OCC-bearing metadata patch,
a *different* admin cannot rename or delete another's file (the ``OwnedMixin`` per-row
gate), a non-admin is refused outright, and delete removes both the row and the blob.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from terp.core import Principal, Roles

from terp.capabilities.files import (
    FileStorageError,
    LocalFilesystemStorage,
    configure_allowed_content_types,
    configure_upload_limit,
    reset_allowed_content_types,
    reset_storage_backend,
    reset_upload_limit,
    set_storage_backend,
)

_CONTENT = b"terp example file body"
_PNG = b"\x89PNG\r\n\x1a\n" + _CONTENT  # bytes carrying the PNG signature (ADR 0076)


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path: Path) -> Iterator[Path]:
    """Point the process-global storage seam at a per-test directory, then restore it."""
    root = tmp_path / "blobs"
    set_storage_backend(LocalFilesystemStorage(root))
    yield root
    reset_storage_backend()


def _admin(client_factory):
    return client_factory(Principal(id=uuid.uuid4(), role=Roles.ADMIN))


def _upload(client, *, name: str = "report.txt", data: bytes = _CONTENT) -> dict:
    response = client.post(
        "/api/v1/files/", files={"file": (name, data, "text/plain")}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_stamps_the_owner_and_never_leaks_the_storage_key(client_factory) -> None:
    principal = Principal(id=uuid.uuid4(), role=Roles.ADMIN)
    client = client_factory(principal)
    response = client.post(
        "/api/v1/files/", files={"file": ("report.txt", _CONTENT, "text/plain")}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["owner_id"] == str(principal.id)  # the creator is stamped as the owner
    assert body["filename"] == "report.txt"
    assert body["content_type"] == "text/plain"
    assert body["size"] == len(_CONTENT)
    assert body["sha256"] == hashlib.sha256(_CONTENT).hexdigest()
    assert "storage_key" not in body  # the raw storage address never crosses the boundary


def test_download_round_trips_the_bytes_with_a_safe_disposition(client_factory) -> None:
    admin = _admin(client_factory)
    file_id = _upload(admin, name="weird name.txt")["id"]

    response = admin.get(f"/api/v1/files/{file_id}/content")
    assert response.status_code == 200
    assert response.content == _CONTENT
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-length"] == str(len(_CONTENT))
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "\n" not in disposition  # a hostile stored filename cannot inject headers
    assert 'filename="weird_name.txt"' in disposition
    assert "filename*=UTF-8''weird%20name.txt" in disposition


def test_list_paginates_and_get_returns_metadata(client_factory) -> None:
    admin = _admin(client_factory)
    first = _upload(admin, name="a.txt")
    _upload(admin, name="b.txt")

    listing = admin.get("/api/v1/files/", params={"limit": 1})
    assert listing.status_code == 200
    page = listing.json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert "storage_key" not in page["items"][0]

    got = admin.get(f"/api/v1/files/{first['id']}")
    assert got.status_code == 200
    assert got.json()["filename"] == "a.txt"


def test_rename_is_an_occ_metadata_patch(client_factory) -> None:
    admin = _admin(client_factory)
    created = _upload(admin)

    patched = admin.patch(
        f"/api/v1/files/{created['id']}",
        json={"filename": "renamed.txt", "version": created["version"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["filename"] == "renamed.txt"
    assert patched.json()["sha256"] == created["sha256"]  # content untouched

    stale = admin.patch(
        f"/api/v1/files/{created['id']}",
        json={"filename": "again.txt", "version": created["version"]},
    )
    assert stale.status_code == 409  # optimistic concurrency


def test_only_the_owner_may_rename_or_delete(client_factory) -> None:
    owner = _admin(client_factory)
    created = _upload(owner)
    other = _admin(client_factory)

    denied = other.patch(
        f"/api/v1/files/{created['id']}",
        json={"filename": "seized.txt", "version": created["version"]},
    )
    assert denied.status_code == 403  # the per-row OwnedMixin write gate

    assert other.delete(f"/api/v1/files/{created['id']}").status_code == 403
    assert owner.delete(f"/api/v1/files/{created['id']}").status_code == 204


def test_delete_removes_the_row_and_the_blob(
    client_factory, _isolated_storage: Path
) -> None:
    admin = _admin(client_factory)
    file_id = _upload(admin)["id"]
    assert any(_isolated_storage.rglob("*"))  # the blob landed on disk

    assert admin.delete(f"/api/v1/files/{file_id}").status_code == 204
    assert admin.get(f"/api/v1/files/{file_id}").status_code == 404
    assert not any(p for p in _isolated_storage.rglob("*") if p.is_file())


class _FlakyDeleteStorage(LocalFilesystemStorage):
    """A local backend whose ``delete`` fails a fixed number of times, then recovers."""

    def __init__(self, root: Path, *, fail_times: int) -> None:
        super().__init__(root)
        self._remaining_failures = fail_times

    def delete(self, key: str) -> None:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise FileStorageError("the storage backend refused the delete")
        super().delete(key)


def test_delete_is_atomic_and_retryable_when_the_blob_backend_fails(
    client_factory, _isolated_storage: Path
) -> None:
    """A failed blob delete rolls the row delete back — no orphan, retryable by the id."""
    set_storage_backend(_FlakyDeleteStorage(_isolated_storage, fail_times=1))
    admin = _admin(client_factory)
    file_id = _upload(admin)["id"]

    # First attempt: the backend blob-delete fails, so the whole unit rolls back.
    failed = admin.delete(f"/api/v1/files/{file_id}")
    assert failed.status_code == 502

    # The metadata row (which alone holds the storage key) survived, and its bytes are
    # still on disk: no silent, unretryable orphan — the delete can be retried by id.
    assert admin.get(f"/api/v1/files/{file_id}").status_code == 200
    assert any(p for p in _isolated_storage.rglob("*") if p.is_file())

    # Retry now that the backend recovers: both the row and the blob are gone.
    assert admin.delete(f"/api/v1/files/{file_id}").status_code == 204
    assert admin.get(f"/api/v1/files/{file_id}").status_code == 404
    assert not any(p for p in _isolated_storage.rglob("*") if p.is_file())


def test_upload_rejects_an_oversized_body(
    client_factory, _isolated_storage: Path
) -> None:
    configure_upload_limit(8)
    try:
        response = _admin(client_factory).post(
            "/api/v1/files/", files={"file": ("big.bin", b"123456789", "text/plain")}
        )
    finally:
        reset_upload_limit()
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"
    # The streamed cap refuses mid-copy and compensates, so nothing is ever stored.
    assert not any(p for p in _isolated_storage.rglob("*") if p.is_file())


def test_an_upload_larger_than_the_global_request_cap_succeeds(
    client_factory,
) -> None:
    """The declared module allowance (ADR 0067) lifts the kernel's 1 MiB request cap.

    The example app ships the default ``SecurityConfig`` (1 MiB ``max_request_bytes``),
    so before the per-module allowance this exact upload died at the socket with a 413
    — the ADR 0066 review flagged the 25 MiB files cap as unreachable. The files spec's
    ``max_request_bytes`` now applies to ``/api/v1/files`` alone: this 1.5 MiB upload
    round-trips, while the same body on another module's prefix stays refused (the
    global cap is not widened).
    """
    admin = _admin(client_factory)
    big = b"x" * (1536 * 1024)  # 1.5 MiB: over the global cap, under the files allowance
    created = _upload(admin, name="big.bin", data=big)
    assert created["size"] == len(big)

    downloaded = admin.get(f"/api/v1/files/{created['id']}/content")
    assert downloaded.status_code == 200
    assert downloaded.content == big

    # Containment: every other prefix keeps the global 1 MiB cap.
    refused = admin.post("/api/v1/notes/", content=big)
    assert refused.status_code == 413
    assert refused.json()["code"] == "request_too_large"


def test_upload_rejects_an_overlong_filename_or_content_type(client_factory) -> None:
    admin = _admin(client_factory)
    long_name = "n" * 256 + ".txt"
    response = admin.post(
        "/api/v1/files/", files={"file": (long_name, _CONTENT, "text/plain")}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"

    long_type = "text/" + "x" * 256
    response = admin.post(
        "/api/v1/files/", files={"file": ("ok.txt", _CONTENT, long_type)}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


def test_a_disallowed_content_type_is_refused_with_a_415(
    client_factory, _isolated_storage: Path
) -> None:
    """With an allowlist configured, a disallowed upload dies at the chokepoint (ADR 0068)."""
    configure_allowed_content_types(["image/*"])
    try:
        admin = _admin(client_factory)
        refused = admin.post(
            "/api/v1/files/",
            files={"file": ("evil.exe", b"MZ...", "application/x-msdownload")},
        )
        assert refused.status_code == 415
        assert refused.json()["code"] == "content_type_not_allowed"
        assert not any(p for p in _isolated_storage.rglob("*") if p.is_file())
        # An allowlisted type whose bytes lack its signature dies at the sniff (ADR 0076).
        mislabeled = admin.post(
            "/api/v1/files/", files={"file": ("fake.png", _CONTENT, "image/png")}
        )
        assert mislabeled.status_code == 415
        assert mislabeled.json()["code"] == "content_type_mismatch"
        assert not any(p for p in _isolated_storage.rglob("*") if p.is_file())
        # An allowlisted type still round-trips.
        allowed = admin.post(
            "/api/v1/files/", files={"file": ("ok.png", _PNG, "image/png")}
        )
        assert allowed.status_code == 201
    finally:
        reset_allowed_content_types()


def test_non_admins_are_refused(client_factory) -> None:
    editor = client_factory(Principal(id=uuid.uuid4(), role=Roles.EDITOR))
    assert editor.get("/api/v1/files/").status_code == 403
    assert (
        editor.post(
            "/api/v1/files/", files={"file": ("x.txt", _CONTENT, "text/plain")}
        ).status_code
        == 403
    )
    anonymous = client_factory(None)
    assert anonymous.get("/api/v1/files/").status_code == 401


def test_unauthenticated_malformed_upload_is_refused_before_multipart_parse(
    client_factory,
) -> None:
    anonymous = client_factory(None)
    response = anonymous.post(
        "/api/v1/files/",
        content=b"not-a-valid-multipart-body",
        headers={"content-type": "multipart/form-data; boundary=x"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
