"""Framework-owned end-to-end coverage of the bundled capability stack.

The bundled capabilities (auth login/logout, users admin, access grants, the audit
log) and the tenancy middleware are otherwise exercised only by ``apps/example``. This
suite assembles the *same* stack from framework packages alone over an in-memory
database, so ``terp.*`` reaches full coverage without the dogfood, keeping the example
purely additive (the STATUS self-coverage gap, ADR 0035). It mirrors the example wiring:
the revocable identity provider, the durable audit sink, the permission enforcer, and
``TenantMiddleware`` through the sanctioned ``create_app`` middleware seam (ADR 0021).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.middleware import Middleware

from terp.core import (
    AuthenticationError,
    PermissionDeniedError,
    Roles,
    create_app,
    get_session,
    settings,
)
from terp.core._internal.session_guard import WriteGuardedSession

import terp.capabilities.access.models  # noqa: F401  (register Grant table)
import terp.capabilities.audit.models  # noqa: F401  (register AuditEvent table)
import terp.capabilities.identity.models  # noqa: F401  (register User table)
from terp.capabilities.access import AccessService, enforce_permission, require_permission
from terp.capabilities.audit import persist_audit
from terp.capabilities.auth import build_login_module, create_access_token, tenant_from_bearer
from terp.capabilities.identity import IdentityService
from terp.capabilities.tenancy import TenantMiddleware
from terp.capabilities.users import UserProvision, UsersService
from terp.capabilities.users.router import module as users_module
from terp.capabilities.access.router import module as access_module
from terp.capabilities.audit.router import module as audit_module

_PASSWORD = "correct horse battery"  # 12+ chars, 2 classes; satisfies the default policy
settings.SECRET_KEY = "terp-framework-stack-secret-key-0123456789ab"


@pytest.fixture
def engine() -> Iterator[Engine]:
    db = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(db)
    try:
        yield db
    finally:
        SQLModel.metadata.drop_all(db)
        db.dispose()


@pytest.fixture
def app(engine: Engine) -> Iterator[FastAPI]:
    """The bundled stack: login + users + access + audit, tenant-aware, audited."""
    identity = IdentityService()
    users = UsersService()
    application = create_app(
        [
            build_login_module(
                identity.authenticate,
                tenant_resolver=lambda s, p: None,
                token_version_resolver=identity.token_version_for,
                revoke_sessions=users.revoke_sessions,
            ),
            users_module,
            access_module,
            audit_module,
        ],
        principal_provider=identity.principal_provider(),
        audit_sink=persist_audit,
        permission_enforcer=enforce_permission,
        middleware=[Middleware(TenantMiddleware, resolve_tenant=tenant_from_bearer)],
    )

    def _session() -> Iterator[Session]:
        with WriteGuardedSession(engine) as session:
            yield session

    application.dependency_overrides[get_session] = _session
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


def _provision(engine: Engine, email: str, role: Roles) -> uuid.UUID:
    with Session(engine) as session:
        user = UsersService().create(
            session, UserProvision(email=email, password=_PASSWORD, role=role)
        )
        return user.id


def _client(app: FastAPI, subject: uuid.UUID, role: Roles) -> TestClient:
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {create_access_token(subject=subject, role=role)}"
    return client


# --------------------------------------------------------------------------- #
# auth login / logout + identity authenticate / token epoch
# --------------------------------------------------------------------------- #
def test_login_logout_round_trip_and_revocation(app: FastAPI, engine: Engine) -> None:
    admin = _provision(engine, "admin@x.test", Roles.ADMIN)
    anon = TestClient(app)
    ok = anon.post("/api/v1/auth/login", json={"email": "admin@x.test", "password": _PASSWORD})
    assert ok.status_code == 200, ok.text
    token = ok.json()["access_token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert TestClient(app).get("/api/v1/users/", headers=bearer).status_code == 200
    assert anon.post("/api/v1/auth/logout", headers=bearer).status_code == 204
    # The epoch bumped at logout: the old token is now rejected mid-session.
    assert TestClient(app).get("/api/v1/users/", headers=bearer).status_code == 401
    bad = anon.post("/api/v1/auth/login", json={"email": "admin@x.test", "password": "wrong-credential"})
    assert bad.status_code == 401
    assert anon.post("/api/v1/auth/logout").status_code == 204  # unauthenticated logout = no-op


# --------------------------------------------------------------------------- #
# users admin surface (router + service)
# --------------------------------------------------------------------------- #
def test_users_admin_lifecycle(app: FastAPI, engine: Engine) -> None:
    admin = _provision(engine, "admin@x.test", Roles.ADMIN)
    _provision(engine, "admin2@x.test", Roles.ADMIN)  # a 2nd admin so demote/deactivate is allowed
    c = _client(app, admin, Roles.ADMIN)

    created = c.post("/api/v1/users/", json={"email": "e@x.test", "password": _PASSWORD, "role": int(Roles.EDITOR)})
    assert created.status_code == 201
    uid = created.json()["id"]
    assert "hashed_password" not in created.json()
    assert c.get("/api/v1/users/").json()["total"] >= 3
    assert c.get(f"/api/v1/users/{uid}").json()["email"] == "e@x.test"

    version = c.get(f"/api/v1/users/{uid}").json()["version"]
    patched = c.patch(f"/api/v1/users/{uid}", json={"role": int(Roles.VIEWER), "version": version})
    assert patched.status_code == 200
    assert c.post(f"/api/v1/users/{uid}/deactivate").json()["is_active"] is False
    assert c.post(f"/api/v1/users/{uid}/reactivate").json()["is_active"] is True
    assert c.post(f"/api/v1/users/{uid}/reset-password", json={"password": _PASSWORD}).status_code == 200


def test_users_self_and_last_admin_guards(app: FastAPI, engine: Engine) -> None:
    admin = _provision(engine, "solo@x.test", Roles.ADMIN)
    c = _client(app, admin, Roles.ADMIN)
    # Self-deactivate is refused; sole admin cannot be removed either.
    assert c.post(f"/api/v1/users/{admin}/deactivate").status_code == 409
    other = _provision(engine, "ed@x.test", Roles.EDITOR)
    assert c.post(f"/api/v1/users/{other}/deactivate").json()["is_active"] is False


# --------------------------------------------------------------------------- #
# access grants router + audit log router
# --------------------------------------------------------------------------- #
def test_access_grants_and_audit_log(app: FastAPI, engine: Engine) -> None:
    admin = _provision(engine, "admin@x.test", Roles.ADMIN)
    c = _client(app, admin, Roles.ADMIN)
    subject = uuid.uuid4()
    created = c.post("/api/v1/access/grants", json={"subject_id": str(subject), "permission": "reports:export"})
    assert created.status_code == 201
    grant_id = created.json()["id"]
    assert c.get("/api/v1/access/grants", params={"subject_id": str(subject)}).json()["total"] == 1
    assert c.delete(f"/api/v1/access/grants/{grant_id}").status_code == 204
    assert c.get("/api/v1/audit/").json()["total"] >= 1  # grant + provision were audited


def test_unauthenticated_is_denied(app: FastAPI) -> None:
    assert TestClient(app).get("/api/v1/users/").status_code == 401


# --------------------------------------------------------------------------- #
# unit: access service + require_permission dependency
# --------------------------------------------------------------------------- #
def test_access_service_revoke_and_permissions(engine: Engine) -> None:
    with Session(engine) as session:
        service = AccessService()
        subject = uuid.uuid4()
        assert service.revoke(session, subject, "absent") is False  # nothing to remove
        service.grant(session, subject, "a:b")
        assert service.permissions_for(session, subject) == {"a:b"}
        dep = require_permission("a:b")
        with pytest.raises(AuthenticationError):
            dep(session=session, principal=None)
        from terp.core import Principal

        with pytest.raises(PermissionDeniedError):
            dep(session=session, principal=Principal(id=uuid.uuid4(), role=Roles.EDITOR))
        dep(session=session, principal=Principal(id=subject, role=Roles.EDITOR))  # holds it -> no raise
        assert enforce_permission(session, subject, "a:b") is True


# --------------------------------------------------------------------------- #
# unit: identity service + base-service conflict mapping
# --------------------------------------------------------------------------- #
def test_identity_authenticate_paths(engine: Engine) -> None:
    identity = IdentityService()
    with Session(engine) as session:
        UsersService().create(
            session, UserProvision(email="i@x.test", password=_PASSWORD, role=Roles.EDITOR)
        )
        assert identity.authenticate(session, "i@x.test", _PASSWORD) is not None
        assert identity.authenticate(session, "i@x.test", "wrong-credential") is None
        assert identity.authenticate(session, "missing@x.test", _PASSWORD) is None
        assert identity.token_version_for(session, identity.authenticate(session, "i@x.test", _PASSWORD)) == 0


def test_authenticate_refusals_burn_a_dummy_verify(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every pre-verify refusal path equalizes timing (no user-enumeration side channel)."""
    import terp.capabilities.identity.service as identity_service_module

    burned: list[bool] = []
    monkeypatch.setattr(
        identity_service_module, "verify_password_dummy", lambda: burned.append(True)
    )
    identity = IdentityService()
    with Session(engine) as session:
        UsersService().create(
            session, UserProvision(email="t@x.test", password=_PASSWORD, role=Roles.EDITOR)
        )
        # Unknown email → dummy verify.
        assert identity.authenticate(session, "missing@x.test", _PASSWORD) is None
        assert len(burned) == 1
        # Inactive account → dummy verify.
        row = identity.get_by_email(session, "t@x.test")
        row.is_active = False
        session.add(row)
        session.commit()
        assert identity.authenticate(session, "t@x.test", _PASSWORD) is None
        assert len(burned) == 2
        # SSO-only user (no local credential) → dummy verify.
        row.is_active = True
        row.hashed_password = None
        session.add(row)
        session.commit()
        assert identity.authenticate(session, "t@x.test", _PASSWORD) is None
        assert len(burned) == 3


def test_verify_password_dummy_builds_lazily_and_reuses_the_hash() -> None:
    from terp.capabilities.auth import hashing

    # Reset the lazy cache so both branches are exercised deterministically.
    hashing._dummy_hash = None
    hashing.verify_password_dummy()  # first call builds the dummy hash
    built = hashing._dummy_hash
    assert built is not None
    hashing.verify_password_dummy()  # second call reuses it
    assert hashing._dummy_hash is built


def test_duplicate_email_maps_to_conflict(engine: Engine) -> None:
    from terp.core import ConflictError

    with Session(engine) as session:
        UsersService().create(session, UserProvision(email="dup@x.test", password=_PASSWORD, role=Roles.EDITOR))
        with pytest.raises(ConflictError):
            UsersService().create(session, UserProvision(email="dup@x.test", password=_PASSWORD, role=Roles.EDITOR))


def test_users_update_guards_and_session_writes(engine: Engine) -> None:
    from terp.core import StaleDataError

    from terp.capabilities.users import UserAdminUpdate
    from terp.capabilities.users.service import LastAdminError, SelfAdminActionError

    service = UsersService()
    with Session(engine) as session:
        admin = service.create(session, UserProvision(email="a@x.test", password=_PASSWORD, role=Roles.ADMIN))
        # A stale version is refused before any epoch bump.
        with pytest.raises(StaleDataError):
            service.update(session, admin.id, UserAdminUpdate(role=Roles.ADMIN, version=admin.version + 5))
        # Demoting the only admin (and self-demotion) is refused.
        with pytest.raises(SelfAdminActionError):
            service.update(session, admin.id, UserAdminUpdate(role=Roles.VIEWER, version=admin.version), actor_id=admin.id)
        with pytest.raises(LastAdminError):
            service.update(session, admin.id, UserAdminUpdate(role=Roles.VIEWER, version=admin.version))
        # revoke_sessions bumps the epoch (logout write-back).
        before = service.get(session, admin.id).token_version
        service.revoke_sessions(session, admin.id)
        assert service.get(session, admin.id).token_version == before + 1
        with pytest.raises(LastAdminError):  # deactivating the sole admin (no actor) is refused
            service.set_active(session, admin.id, active=False, actor_id=None)


def test_last_admin_count_locks_the_admin_rows_for_update() -> None:
    """The admin-count guard locks the active-admin rows (``FOR UPDATE``) inside the
    same transaction as the demotion / deactivation write, so two instances mutating
    admins concurrently serialise **at the database** — the multi-instance half of the
    last-admin invariant (review L3). The in-process ``RLock`` only covers a single
    process (SQLite dev/test, where ``FOR UPDATE`` is a no-op); this build-time pin
    keeps the row lock from being silently dropped.
    """
    from sqlalchemy.dialects import postgresql

    captured: list[object] = []

    class _Result:
        def all(self) -> list[object]:
            return [object()]

    class _SpySession:
        def exec(self, statement: object) -> _Result:
            captured.append(statement)
            return _Result()

    count = UsersService()._active_admin_count(_SpySession())  # type: ignore[arg-type]
    assert count == 1
    compiled = str(captured[0].compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]
    assert "FOR UPDATE" in compiled


def test_build_get_principal_validator_rejects() -> None:
    from starlette.requests import Request

    from terp.capabilities.auth import build_get_principal, create_access_token

    token = create_access_token(subject=uuid.uuid4(), role=Roles.EDITOR)
    request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})
    provider = build_get_principal(token_validator=lambda s, c: False)
    assert provider(request, object()) is None  # validator fails -> unauthenticated
    garbage = Request({"type": "http", "headers": [(b"authorization", b"Bearer not.a.jwt")]})
    assert provider(garbage, object()) is None  # undecodable token -> unauthenticated


# --------------------------------------------------------------------------- #
# unit: tenancy context + the registered row-scope predicate
# --------------------------------------------------------------------------- #
def test_tenant_context_and_scope_predicate() -> None:
    from sqlmodel import Field, select

    from terp.capabilities.tenancy import (
        TenantScopedMixin,
        current_tenant_id,
        require_tenant,
        tenant_context,
    )
    from terp.capabilities.tenancy.context import TenantContextError
    from terp.capabilities.tenancy.models import _tenant_scope_predicate

    assert current_tenant_id() is None
    with pytest.raises(TenantContextError):
        require_tenant()  # no tenant bound -> fail closed

    class _Row(TenantScopedMixin, table=True):
        __tablename__ = "framework_stack_scoped_row"
        id: int = Field(default=None, primary_key=True)

    # Unbound: the predicate filters everything out (false()); bound: it scopes by tenant.
    assert "false" in str(_tenant_scope_predicate(_Row, select(_Row))).lower()
    with tenant_context(uuid.uuid4()):
        assert require_tenant() is not None
        assert "tenant_id" in str(_tenant_scope_predicate(_Row, select(_Row)))
