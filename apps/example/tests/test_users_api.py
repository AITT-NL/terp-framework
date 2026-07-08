"""End-to-end: the ``users`` capability — admin user management over identity's store.

The ``users`` router is **not** passed to ``create_app`` explicitly — it is mounted
purely via entry-point discovery (``discover_capabilities=True``) and owns
``/api/v1/users`` (the identity capability is now a library store). Every endpoint
is admin-only; every write is audited through the ``BaseService`` chokepoint.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from terp.capabilities.auth import create_access_token
from terp.core import Roles

# The shipped app uses the revocable principal provider (ADR 0031): every request
# re-checks that the bearer's subject is a real, active user at the current token epoch,
# so an acting principal needs a backing user row. We persist it with a LOW stored role
# so the acting admin never counts toward the last-admin invariant these tests exercise —
# authorization comes from the token rank, the admin count from the stored role, and the
# two are deliberately independent in Terp.
_backing_session: Session | None = None


@pytest.fixture(autouse=True)
def _bind_backing_session(db_session: Session):
    global _backing_session
    _backing_session = db_session
    yield
    _backing_session = None


def _back(subject: uuid.UUID) -> None:
    """Persist a minimal active (low-role) user for *subject* if not already present."""
    from terp.capabilities.identity.models import User

    assert _backing_session is not None
    if _backing_session.get(User, subject) is None:
        _backing_session.add(
            User(
                id=subject,
                email=f"principal-{subject}@backing.test",
                hashed_password="not-a-login-fixture",
                role=int(Roles.VIEWER),
                is_active=True,
                token_version=0,
            )
        )
        _backing_session.commit()


def _client_as(app_db: FastAPI, role: Roles) -> TestClient:
    subject = uuid.uuid4()
    _back(subject)
    token = create_access_token(subject=subject, role=role)
    client = TestClient(app_db)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _client_for_subject(app_db: FastAPI, subject: str, role: Roles) -> TestClient:
    _back(uuid.UUID(subject))
    token = create_access_token(subject=uuid.UUID(subject), role=role)
    client = TestClient(app_db)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_users_router_is_discovered_and_lists_for_admin(app_db: FastAPI, make_user) -> None:
    make_user("admin@example.com", "correct horse battery", Roles.ADMIN)
    make_user("viewer@example.com", "correct horse battery", Roles.VIEWER)

    client = _client_as(app_db, Roles.ADMIN)
    response = client.get("/api/v1/users/")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 2
    # UserRead never leaks the password hash.
    assert all("hashed_password" not in item for item in body["items"])


def test_users_list_filters_by_email_substring(app_db: FastAPI, make_user) -> None:
    """The directory lookup behind the admin member picker: `?email=` narrows the page.

    Case-insensitive substring match, so an admin resolves an account by typing part
    of its address instead of paging through the whole directory.
    """
    make_user("finance.lead@example.com", "correct horse battery", Roles.EDITOR)
    make_user("ops.lead@example.com", "correct horse battery", Roles.EDITOR)

    client = _client_as(app_db, Roles.ADMIN)
    filtered = client.get("/api/v1/users/", params={"email": "FINANCE"})
    assert filtered.status_code == 200, filtered.text
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "finance.lead@example.com"
    # An unmatched needle is an empty page, not an error.
    assert client.get("/api/v1/users/", params={"email": "no-such"}).json()["total"] == 0


def test_users_router_denies_non_admin(app_db: FastAPI) -> None:
    client = _client_as(app_db, Roles.VIEWER)
    assert client.get("/api/v1/users/").status_code == 403
    # Writes are admin-only too.
    denied = client.post("/api/v1/users/", json={"email": "x@y.z", "password": "pw"})
    assert denied.status_code == 403


def test_admin_provisions_and_fetches_a_user(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    created = admin.post(
        "/api/v1/users/",
        json={"email": "new@example.com", "password": "correct horse battery", "role": int(Roles.EDITOR)},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == int(Roles.EDITOR)
    assert body["is_active"] is True
    assert "hashed_password" not in body

    fetched = admin.get(f"/api/v1/users/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_admin_can_provision_a_custom_role_rank(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    created = admin.post(
        "/api/v1/users/",
        json={"email": "lead@example.com", "password": "correct horse battery", "role": 25},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == 25
    listed = admin.get("/api/v1/users/")
    assert listed.status_code == 200, listed.text
    assert any(item["role"] == 25 for item in listed.json()["items"])


def test_provisioning_rejects_a_weak_password(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    # A short, common password is refused with the uniform WeakPasswordError envelope
    # (422, code=weak_password) before any user is created (PasswordPolicy, ADR 0032).
    weak = admin.post("/api/v1/users/", json={"email": "weak@example.com", "password": "pw"})
    assert weak.status_code == 422, weak.text
    assert weak.json()["code"] == "weak_password"
    # A policy-passing passphrase is accepted, so the gate refuses values, not all writes.
    strong = admin.post(
        "/api/v1/users/", json={"email": "weak@example.com", "password": "correct horse battery"}
    )
    assert strong.status_code == 201, strong.text


def test_reset_password_rejects_a_weak_password(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    created = admin.post(
        "/api/v1/users/",
        json={"email": "weakreset@example.com", "password": "correct horse battery"},
    ).json()
    weak = admin.post(f"/api/v1/users/{created['id']}/reset-password", json={"password": "short"})
    assert weak.status_code == 422, weak.text
    assert weak.json()["code"] == "weak_password"


def test_admin_updates_role_with_optimistic_concurrency(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    created = admin.post(
        "/api/v1/users/", json={"email": "role@example.com", "password": "correct horse battery"}
    ).json()
    assert created["role"] == int(Roles.VIEWER)

    updated = admin.patch(
        f"/api/v1/users/{created['id']}",
        json={"role": int(Roles.ADMIN), "version": created["version"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["role"] == int(Roles.ADMIN)
    assert updated.json()["version"] == created["version"] + 1


def test_stale_admin_update_does_not_leave_token_epoch_dirty(
    app_db: FastAPI, db_session: Session
) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    created = admin.post(
        "/api/v1/users/", json={"email": "stale@example.com", "password": "correct horse battery"}
    ).json()
    stale = admin.patch(
        f"/api/v1/users/{created['id']}",
        json={"role": int(Roles.EDITOR), "version": 0},
    )
    assert stale.status_code == 409, stale.text
    db_session.commit()
    from terp.capabilities.identity import User

    assert db_session.get(User, uuid.UUID(created["id"])).token_version == 0


def test_admin_deactivates_then_reactivates(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    created = admin.post(
        "/api/v1/users/", json={"email": "toggle@example.com", "password": "correct horse battery"}
    ).json()

    deactivated = admin.post(f"/api/v1/users/{created['id']}/deactivate")
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["is_active"] is False

    reactivated = admin.post(f"/api/v1/users/{created['id']}/reactivate")
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True


def test_admin_resets_password(app_db: FastAPI, db_engine) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    created = admin.post(
        "/api/v1/users/", json={"email": "reset@example.com", "password": "correct horse battery old"}
    ).json()

    response = admin.post(
        f"/api/v1/users/{created['id']}/reset-password", json={"password": "correct horse battery new"}
    )
    assert response.status_code == 200, response.text

    # The reset took effect: the new password authenticates, the old one no longer does.
    from terp.capabilities.identity import IdentityService

    with Session(db_engine) as session:
        service = IdentityService()
        assert service.authenticate(session, "reset@example.com", "correct horse battery new") is not None
        assert service.authenticate(session, "reset@example.com", "correct horse battery old") is None


def test_admin_writes_are_audited(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    created = admin.post(
        "/api/v1/users/", json={"email": "audit@example.com", "password": "correct horse battery"}
    ).json()
    admin.post(f"/api/v1/users/{created['id']}/deactivate")

    # Both admin writes (provision + deactivate) auto-emit an audit row for the User
    # target through the BaseService chokepoint — read back via the audit log itself.
    events = admin.get("/api/v1/audit/").json()["items"]
    actions = {
        event["action"]
        for event in events
        if event["target_type"] == "User" and event["target_id"] == created["id"]
    }
    assert actions == {"created", "updated"}


def test_provisioning_a_duplicate_email_conflicts(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    first = admin.post("/api/v1/users/", json={"email": "dup@example.com", "password": "correct horse battery"})
    assert first.status_code == 201, first.text

    # The unique-email constraint surfaces as a uniform 409 envelope, not a raw 500:
    # BaseService maps the IntegrityError to a typed ConflictError.
    duplicate = admin.post("/api/v1/users/", json={"email": "dup@example.com", "password": "correct horse battery"})
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["code"] == "conflict"


def _provision_admin(admin: TestClient, email: str) -> dict:
    created = admin.post(
        "/api/v1/users/",
        json={"email": email, "password": "correct horse battery", "role": int(Roles.ADMIN)},
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_cannot_deactivate_the_last_active_admin(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    only_admin = _provision_admin(admin, "solo-admin@example.com")

    # Deactivating the only active admin would lock everyone out of the admin surface.
    refused = admin.post(f"/api/v1/users/{only_admin['id']}/deactivate")
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "last_admin_protected"


def test_cannot_demote_the_last_active_admin(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    only_admin = _provision_admin(admin, "demote-me@example.com")

    refused = admin.patch(
        f"/api/v1/users/{only_admin['id']}",
        json={"role": int(Roles.VIEWER), "version": only_admin["version"]},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "last_admin_protected"


def test_admin_actions_allowed_while_another_admin_remains(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    first = _provision_admin(admin, "first-admin@example.com")
    second = _provision_admin(admin, "second-admin@example.com")

    # Two active admins: demoting one is fine (the other still administers).
    demoted = admin.patch(
        f"/api/v1/users/{first['id']}",
        json={"role": int(Roles.VIEWER), "version": first["version"]},
    )
    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["role"] == int(Roles.VIEWER)

    # Now only the second admin is active — deactivating *it* is refused.
    refused = admin.post(f"/api/v1/users/{second['id']}/deactivate")
    assert refused.status_code == 409, refused.text

    # But while it was the last admin we could still deactivate a *non*-admin freely,
    # and reactivating keeps the invariant satisfied (active=True is never blocked).
    reactivated = admin.post(f"/api/v1/users/{first['id']}/reactivate")
    assert reactivated.status_code == 200, reactivated.text


def test_can_deactivate_admin_when_another_admin_remains(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    first = _provision_admin(admin, "a1@example.com")
    _provision_admin(admin, "a2@example.com")

    # Two active admins: deactivating one leaves a second, so it is allowed.
    deactivated = admin.post(f"/api/v1/users/{first['id']}/deactivate")
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["is_active"] is False


def test_admin_cannot_deactivate_self_even_when_another_admin_remains(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    self_admin = _provision_admin(admin, "self-off@example.com")
    _provision_admin(admin, "other-admin@example.com")

    self_client = _client_for_subject(app_db, self_admin["id"], Roles.ADMIN)
    refused = self_client.post(f"/api/v1/users/{self_admin['id']}/deactivate")
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "self_admin_action_protected"


def test_admin_cannot_demote_self_even_when_another_admin_remains(app_db: FastAPI) -> None:
    admin = _client_as(app_db, Roles.ADMIN)
    self_admin = _provision_admin(admin, "self-demote@example.com")
    _provision_admin(admin, "other-admin-2@example.com")

    self_client = _client_for_subject(app_db, self_admin["id"], Roles.ADMIN)
    refused = self_client.patch(
        f"/api/v1/users/{self_admin['id']}",
        json={"role": int(Roles.VIEWER), "version": self_admin["version"]},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "self_admin_action_protected"
