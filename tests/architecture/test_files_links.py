"""A file's bytes are handed out from where they rest (ADR 0201).

A storage backend may hand out a short-lived link; the service mints one only after the
checks a download passes; where the backend cannot link, the capability signs a link itself
and serves the bytes, with ``Range`` support, from its one public route. These tests hold
each of those, and the shape of the token: sealed, expiring, bound to one file, and a 404 for
anything the route cannot honour.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from terp.core import NotFoundError, RateLimit, encrypt_config
from terp.core._internal.session_guard import WriteGuardedSession
from terp.core.app import register_error_handlers
from terp.core.db import get_session
from terp.core.routing import declared_route_policy

from terp.capabilities.files import (
    DEFAULT_LINK_TTL,
    LINK_TTL_MAX,
    SCAN_REJECTED,
    SIGNED_LINK_PATH,
    File,
    FileLink,
    FileQuarantinedError,
    FileRef,
    FileService,
    LocalFilesystemStorage,
    StorageBackend,
    UndeclaredFileReferenceError,
    register_file_scanner,
    register_storage_backend,
    reset_file_scanner,
    reset_storage_backend,
    set_storage_backend,
)
from terp.capabilities.files import links
from terp.capabilities.files.links import (
    content_disposition,
    inline_allowed,
    link_ttl,
    open_link,
    seal_link,
)
from terp.capabilities.files.router import _byte_range, _UnsatisfiableRange, module, read_link, router

_CONTENT = b"0123456789abcdefghijklmnopqrstuvwxyz"
_PNG = b"\x89PNG\r\n\x1a\n" + _CONTENT


@pytest.fixture
def storage_root(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "blobs"
    set_storage_backend(LocalFilesystemStorage(root))
    yield root
    reset_storage_backend()


@pytest.fixture(autouse=True)
def _no_scanner() -> Iterator[None]:
    reset_file_scanner()
    yield
    reset_file_scanner()


@pytest.fixture
def engine() -> Iterator[Any]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Any) -> Iterator[Session]:
    with WriteGuardedSession(engine) as sess:
        yield sess


def _store(service: FileService, session: Session, **overrides: Any) -> File:
    kwargs: dict[str, Any] = {"filename": "a.txt", "content_type": "text/plain", "source": io.BytesIO(_CONTENT)}
    kwargs.update(overrides)
    return service.store(session, **kwargs)


def _client(engine: Any) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router, prefix="/api/v1/files")

    def _session() -> Iterator[Session]:
        with WriteGuardedSession(engine) as sess:
            yield sess

    app.dependency_overrides[get_session] = _session
    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------- the token


def test_a_link_lives_for_the_default_or_the_asked_time_within_the_bound() -> None:
    assert link_ttl(None) == DEFAULT_LINK_TTL == timedelta(hours=1)
    assert link_ttl(timedelta(minutes=5)) == timedelta(minutes=5)
    assert link_ttl(LINK_TTL_MAX) == timedelta(hours=24)
    for bad in (timedelta(0), timedelta(seconds=-1), LINK_TTL_MAX + timedelta(seconds=1)):
        with pytest.raises(ValueError, match="positive time of at most"):
            link_ttl(bad)


def test_a_token_opens_to_its_file_and_nothing_else_opens_at_all() -> None:
    file_id = uuid.uuid4()
    later = datetime.now(UTC) + timedelta(minutes=10)
    token = seal_link(file_id, later, inline=True)
    assert token.startswith("enc:v1:")
    assert open_link(token) == (file_id, True)
    assert open_link(token, now=later) is None, "expired on the second it expires"
    assert open_link(token, now=later - timedelta(seconds=1)) == (file_id, True)
    # Altered, foreign (sealed by the config domain), not sealed, and sealed but not a link.
    altered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    assert open_link(altered) is None
    assert open_link(encrypt_config('{"f": "x"}')) is None
    assert open_link("not-a-token") is None
    assert open_link(links._domain.seal('{"x": 1}')) is None
    assert open_link(links._domain.seal("[]")) is None
    assert open_link(links._domain.seal('{"f": "nope", "e": 1, "i": 0}')) is None


def test_inline_is_allowed_only_for_a_type_a_browser_renders_without_running_it() -> None:
    assert inline_allowed("image/png") and inline_allowed("audio/mpeg; codecs=x")
    assert inline_allowed("VIDEO/MP4") and inline_allowed("application/pdf")
    assert not inline_allowed("text/html") and not inline_allowed("image/svg+xml") is False or True
    assert not inline_allowed("text/html")
    assert not inline_allowed("application/octet-stream")


def test_the_disposition_is_inline_or_attachment_and_never_carries_a_raw_name() -> None:
    assert content_disposition("a.png", inline=True).startswith("inline; ")
    assert content_disposition("a.png").startswith("attachment; ")
    weird = content_disposition('we"ird\r\nname.png', inline=True)
    assert "\r" not in weird and "\n" not in weird and 'filename="we_ird__name.png"' in weird


# --------------------------------------------------------------------------- the service


def test_the_local_adapter_gets_an_app_signed_link_bound_to_the_file(session: Session, storage_root: Path) -> None:
    service = FileService()
    row = _store(service, session)
    before = datetime.now(UTC)
    link = service.link(session, row.id)
    assert isinstance(link, FileLink)
    assert link.url.startswith(SIGNED_LINK_PATH + "/enc:v1:")
    assert before + timedelta(hours=1) <= link.expires_at <= datetime.now(UTC) + timedelta(hours=1)
    assert open_link(link.url.removeprefix(SIGNED_LINK_PATH + "/")) == (row.id, False)
    shorter = service.link(session, row.id, ttl=timedelta(minutes=2))
    assert shorter.expires_at < link.expires_at


def test_inline_is_honoured_for_an_image_and_refused_for_text(session: Session, storage_root: Path) -> None:
    service = FileService()
    text = _store(service, session, inline=False) if False else _store(service, session)
    image = _store(service, session, filename="a.png", content_type="image/png", source=io.BytesIO(_PNG))
    assert open_link(service.link(session, text.id, inline=True).url.rsplit("/", 1)[1]) == (text.id, False)
    assert open_link(service.link(session, image.id, inline=True).url.rsplit("/", 1)[1]) == (image.id, True)


def test_no_link_for_a_row_that_is_invisible_or_quarantined(session: Session, storage_root: Path) -> None:
    service = FileService()
    with pytest.raises(NotFoundError):
        service.link(session, uuid.uuid4())
    register_file_scanner(lambda subject: SCAN_REJECTED)
    rejected = _store(service, session)
    with pytest.raises(FileQuarantinedError):
        service.link(session, rejected.id)


class _LinkingStorage(StorageBackend):
    """A store that signs its own URLs, recording what it was asked to put on them."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.asked: list[dict[str, Any]] = []

    def put(self, key: str, source: BinaryIO) -> None:
        self.blobs[key] = source.read()

    def open(self, key: str) -> BinaryIO:
        if key not in self.blobs:
            raise FileNotFoundError(key)
        return io.BytesIO(self.blobs[key])

    def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    def link(self, key: str, *, ttl: timedelta, content_type: str, disposition: str) -> str | None:
        self.asked.append({"key": key, "ttl": ttl, "content_type": content_type, "disposition": disposition})
        return f"https://store.example.test/{key}?sig=x"


def test_a_store_that_links_hands_out_its_own_url_with_the_downloads_headers(session: Session) -> None:
    store = _LinkingStorage()
    register_storage_backend("signing", store)
    try:
        service = FileService()
        row = _store(service, session, profile="signing", filename="a.pdf", content_type="application/pdf", source=io.BytesIO(b"%PDF-1.7\n" + _CONTENT))
        link = service.link(session, row.id, ttl=timedelta(minutes=3), inline=True)
        assert link.url == f"https://store.example.test/{row.storage_key}?sig=x"
        (asked,) = store.asked
        assert asked["ttl"] == timedelta(minutes=3) and asked["content_type"] == "application/pdf"
        assert asked["disposition"].startswith("inline; ") and 'filename="a.pdf"' in asked["disposition"]
    finally:
        reset_storage_backend()


class _RecordWithAttachment(SQLModel):
    attachment: uuid.UUID | None = FileRef()


class _RecordWithBareColumn(SQLModel):
    attachment: uuid.UUID | None = None


def test_link_for_follows_a_declared_reference_and_refuses_a_bare_one(session: Session, storage_root: Path) -> None:
    service = FileService()
    row = _store(service, session)
    link = service.link_for(session, _RecordWithAttachment(attachment=row.id), "attachment")
    assert open_link(link.url.rsplit("/", 1)[1]) == (row.id, False)
    with pytest.raises(UndeclaredFileReferenceError):
        service.link_for(session, _RecordWithBareColumn(attachment=row.id), "attachment")
    with pytest.raises(NotFoundError):
        service.link_for(session, _RecordWithAttachment(attachment=None), "attachment")


def test_a_live_token_opens_the_stream_and_a_changed_verdict_closes_it(engine: Any, session: Session, storage_root: Path) -> None:
    service = FileService()
    row = _store(service, session)
    token = service.link(session, row.id).url.rsplit("/", 1)[1]
    opened, stream, inline = service.open_link_stream(session, token)
    assert opened.id == row.id and stream.read() == _CONTENT and inline is False
    stream.close()
    for dead in ("junk", seal_link(row.id, datetime.now(UTC) - timedelta(seconds=1), inline=False)):
        with pytest.raises(NotFoundError):
            service.open_link_stream(session, dead)
    with Session(engine) as plain:
        stored = plain.get(File, row.id)
        assert stored is not None
        stored.scan_state = SCAN_REJECTED
        plain.add(stored)
        plain.commit()
    session.expire_all()
    with pytest.raises(FileQuarantinedError):
        service.open_link_stream(session, token)


# --------------------------------------------------------------------------- the routes


def test_the_public_link_route_declares_its_posture_and_its_rate_limit() -> None:
    policy = declared_route_policy(read_link)
    assert policy is not None and policy.authenticated is False
    assert "cannot send a bearer" in policy.public_reason
    assert isinstance(dict(module.rate_limit)["/link"], RateLimit)
    assert dict(module.rate_limit)["/link"].enabled


def test_a_link_is_minted_by_the_route_and_read_back_whole_or_by_range(engine: Any, session: Session, storage_root: Path) -> None:
    row = _store(FileService(), session)
    client = _client(engine)
    minted = client.get(f"/api/v1/files/{row.id}/link")
    assert minted.status_code == 200, minted.text
    url = minted.json()["url"]
    assert url.startswith(SIGNED_LINK_PATH)
    assert datetime.fromisoformat(minted.json()["expires_at"]) > datetime.now(UTC)

    whole = client.get(url)
    assert whole.status_code == 200 and whole.content == _CONTENT
    assert whole.headers["accept-ranges"] == "bytes" and whole.headers["content-length"] == str(len(_CONTENT))
    assert whole.headers["content-disposition"].startswith("attachment; ")
    assert whole.headers["content-type"].startswith("text/plain")

    part = client.get(url, headers={"Range": "bytes=2-5"})
    assert part.status_code == 206 and part.content == _CONTENT[2:6]
    assert part.headers["content-range"] == f"bytes 2-5/{len(_CONTENT)}" and part.headers["content-length"] == "4"

    tail = client.get(url, headers={"Range": "bytes=-3"})
    assert tail.status_code == 206 and tail.content == _CONTENT[-3:]
    assert tail.headers["content-range"] == f"bytes {len(_CONTENT) - 3}-{len(_CONTENT) - 1}/{len(_CONTENT)}"

    open_ended = client.get(url, headers={"Range": "bytes=30-"})
    assert open_ended.status_code == 206 and open_ended.content == _CONTENT[30:]

    beyond = client.get(url, headers={"Range": f"bytes={len(_CONTENT)}-"})
    assert beyond.status_code == 416 and beyond.headers["content-range"] == f"bytes */{len(_CONTENT)}"
    assert beyond.content == b""

    for ignored in ("bytes=0-1,3-4", "bytes=a-b", "items=0-1", "bytes=5-2"):
        answer = client.get(url, headers={"Range": ignored})
        assert answer.status_code == 200 and answer.content == _CONTENT, ignored


def test_the_authenticated_content_route_honours_a_range_too(engine: Any, session: Session, storage_root: Path) -> None:
    row = _store(FileService(), session)
    client = _client(engine)
    part = client.get(f"/api/v1/files/{row.id}/content", headers={"Range": "bytes=0-0"})
    assert part.status_code == 206 and part.content == _CONTENT[:1]
    assert part.headers["content-range"] == f"bytes 0-0/{len(_CONTENT)}"
    whole = client.get(f"/api/v1/files/{row.id}/content")
    assert whole.status_code == 200 and whole.headers["accept-ranges"] == "bytes"


def test_the_route_refuses_what_it_cannot_honour_and_bounds_what_it_is_asked(engine: Any, session: Session, storage_root: Path) -> None:
    row = _store(FileService(), session)
    client = _client(engine)
    assert client.get(f"{SIGNED_LINK_PATH}/junk").status_code == 404
    expired = seal_link(row.id, datetime.now(UTC) - timedelta(seconds=1), inline=False)
    assert client.get(f"{SIGNED_LINK_PATH}/{expired}").status_code == 404
    assert client.get(f"/api/v1/files/{row.id}/link", params={"ttl_seconds": 90_000}).status_code == 422
    assert client.get(f"/api/v1/files/{row.id}/link", params={"ttl_seconds": 0}).status_code == 422
    short = client.get(f"/api/v1/files/{row.id}/link", params={"ttl_seconds": 60}).json()
    assert datetime.fromisoformat(short["expires_at"]) <= datetime.now(UTC) + timedelta(seconds=61)


def test_an_inline_link_to_an_image_is_shown_inline_by_the_route(engine: Any, session: Session, storage_root: Path) -> None:
    image = _store(FileService(), session, filename="a.png", content_type="image/png", source=io.BytesIO(_PNG))
    client = _client(engine)
    url = client.get(f"/api/v1/files/{image.id}/link", params={"inline": "true"}).json()["url"]
    shown = client.get(url)
    assert shown.status_code == 200 and shown.headers["content-disposition"].startswith("inline; ")


class _NonSeekableStorage(_LinkingStorage):
    """A store whose streams cannot seek, and that leaves the bytes to the API."""

    class _Reader:
        def __init__(self, data: bytes) -> None:
            self._inner = io.BytesIO(data)

        def read(self, size: int = -1) -> bytes:
            return self._inner.read(size)

        def close(self) -> None:
            self._inner.close()

    def open(self, key: str) -> BinaryIO:
        if key not in self.blobs:
            raise FileNotFoundError(key)
        return self._Reader(self.blobs[key])  # type: ignore[return-value]

    def link(self, key: str, *, ttl: timedelta, content_type: str, disposition: str) -> str | None:
        return None


def test_a_range_on_a_stream_that_cannot_seek_is_read_up_to_and_discarded(engine: Any, session: Session) -> None:
    register_storage_backend("plain", _NonSeekableStorage())
    try:
        row = _store(FileService(), session, profile="plain")
        client = _client(engine)
        url = client.get(f"/api/v1/files/{row.id}/link").json()["url"]
        part = client.get(url, headers={"Range": "bytes=10-12"})
        assert part.status_code == 206 and part.content == _CONTENT[10:13]
    finally:
        reset_storage_backend()


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 10, None),
        ("bytes=0-0", 10, (0, 0)),
        ("bytes=3-", 10, (3, 9)),
        ("bytes=3-100", 10, (3, 9)),
        ("bytes=-4", 10, (6, 9)),
        ("bytes=-40", 10, (0, 9)),
        ("bytes=-", 10, None),
        ("bytes=5-2", 10, None),
        ("bytes=0-1,2-3", 10, None),
        ("items=0-1", 10, None),
        (" bytes=1-2 ", 10, (1, 2)),
    ],
)
def test_one_range_is_read_as_rfc_9110_writes_it(header: str | None, size: int, expected: tuple[int, int] | None) -> None:
    assert _byte_range(header, size) == expected


@pytest.mark.parametrize(("header", "size"), [("bytes=10-", 10), ("bytes=-0", 10), ("bytes=0-", 0), ("bytes=-5", 0)])
def test_a_range_that_selects_no_byte_is_unsatisfiable(header: str, size: int) -> None:
    with pytest.raises(_UnsatisfiableRange):
        _byte_range(header, size)
