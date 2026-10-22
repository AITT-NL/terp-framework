"""Fixtures for the reference app's end-to-end tests.

Each test gets the real composition (``app.main.build``) over its own migrated database,
on both verified dialects (``terp_db_url``: SQLite always, PostgreSQL when
``TERP_TEST_POSTGRES_URL`` names a server). Nothing here stands in for a capability; the
three seams faked are the three that leave the process — the network, the mail relay and
the disk — and each is faked through the capability's own documented seam.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable, Iterator, Mapping

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from terp.core import Roles, get_session

# The session a request gets: persistence only through the audited service chokepoint.
# The kernel keeps it internal because app code never builds one; a test that stands the
# app up over its own database has to, exactly as the platform's example app does.
from terp.core._internal.session_guard import WriteGuardedSession
from terp.migrations import upgrade

from terp.capabilities.auth import create_access_token
from terp.capabilities.egress import EgressClient, EgressResponse, PinnedTarget
from terp.capabilities.files import (
    DEFAULT_STORAGE_PROFILE,
    LocalFilesystemStorage,
    register_storage_backend,
    reset_storage_backend,
)
from terp.capabilities.mail import (
    CapturingMailTransport,
    MailSettings,
    configure_mail,
    reset_mail,
)
from terp.capabilities.outbox import DrainResult, OutboxWorker
from terp.capabilities.users import UserProvision, UsersService

from app.main import build
from app.modules.notices import upstream

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "app"

#: A public address for the upstream's name, so the SSRF denylist has something real to
#: pass. Nothing ever connects to it: the sender below answers instead.
UPSTREAM_ADDRESS = "93.184.215.14"


@pytest.fixture
def db_engine(terp_db_url: str) -> Iterator[Engine]:
    """A database migrated to head by the app's own revisions, and an engine on it."""
    upgrade(terp_db_url, APP_ROOT, package="app")
    engine = create_engine(terp_db_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def application(db_engine: Engine) -> Iterator[FastAPI]:
    """The composed app, every request served from *db_engine*."""
    app = build()

    def _session() -> Iterator[Session]:
        with WriteGuardedSession(db_engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client_as(application: FastAPI, db_engine: Engine) -> Callable[[Roles | None], TestClient]:
    """A client signed in as a real, active user of *role* (or anonymous for ``None``)."""

    def _make(role: Roles | None) -> TestClient:
        client = TestClient(application)
        if role is None:
            return client
        with Session(db_engine) as session:
            user = UsersService().create(
                session,
                UserProvision(
                    email=f"{role.name.lower()}@reference.test",
                    password="a passphrase long enough for the policy",
                    role=int(role),
                ),
            )
        token = create_access_token(subject=user.id, role=role)
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    return _make


@pytest.fixture
def mailbox(application: FastAPI) -> Iterator[CapturingMailTransport]:
    """Every mail the worker delivers, captured instead of sent.

    Configured after the app is built, because ``build`` declares the relay from the
    environment and a test environment names none.
    """
    sent = CapturingMailTransport()
    configure_mail(
        MailSettings(sender="Terp Reference <noreply@reference.example>", host="smtp.example.test"),
        transport=sent,
    )
    try:
        yield sent
    finally:
        reset_mail()


@pytest.fixture
def storage(tmp_path: pathlib.Path) -> Iterator[pathlib.Path]:
    """The default file-storage profile, rooted in this test's own directory."""
    root = tmp_path / "files"
    register_storage_backend(DEFAULT_STORAGE_PROFILE, LocalFilesystemStorage(root))
    try:
        yield root
    finally:
        reset_storage_backend()


class FakeUpstream:
    """The egress transport, answering for the upstream without touching the network."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = b"<!doctype html><title>Example Domain</title>",
        headers: Mapping[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = dict(headers or {"content-type": "text/html; charset=UTF-8"})
        self.error = error
        self.targets: list[PinnedTarget] = []

    def __call__(
        self,
        target: PinnedTarget,
        method: str,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> EgressResponse:
        self.targets.append(target)
        if self.error is not None:
            raise self.error
        return EgressResponse(self.status_code, self.headers, self.content)


@pytest.fixture
def fake_upstream(monkeypatch: pytest.MonkeyPatch) -> FakeUpstream:
    """Point the module's client at :class:`FakeUpstream`, keeping the declared policy."""
    fake = FakeUpstream()
    monkeypatch.setattr(
        upstream,
        "client",
        EgressClient(upstream.UPSTREAM_POLICY, sender=fake, resolve=lambda host: [UPSTREAM_ADDRESS]),
    )
    return fake


@pytest.fixture
def drain(db_engine: Engine) -> Callable[[], DrainResult]:
    """Run the outbox worker over *db_engine* until nothing is due, as ``terp jobs worker`` does."""

    def _drain() -> DrainResult:
        worker = OutboxWorker(
            lambda: Session(db_engine),
            job_session_factory=lambda: WriteGuardedSession(db_engine),
        )
        return worker.run(max_cycles=5)

    return _drain
