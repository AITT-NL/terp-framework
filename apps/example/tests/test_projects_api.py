"""End-to-end: the example ``projects`` module is isolated per tenant over HTTP.

Proves the *shipped* composition (``main.build()``) wires ``TenantMiddleware``
through the ``create_app(middleware=...)`` seam (ADR 0021): a request's tenant is
bound from its token's ``tenant`` claim, and the tenant-scoped ``projects`` resource
then isolates rows per tenant — with no ad-hoc middleware anywhere in app code. This
closes the review gap that the example app had no tenant-scoped model.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from terp.capabilities.auth import decode_access_token
from terp.core import Roles


def test_projects_are_isolated_by_token_tenant(token_client) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    client_a = token_client(tenant=tenant_a)
    client_b = token_client(tenant=tenant_b)

    assert client_a.post("/api/v1/projects/", json={"name": "alpha"}).status_code == 201
    assert client_b.post("/api/v1/projects/", json={"name": "beta-1"}).status_code == 201
    assert client_b.post("/api/v1/projects/", json={"name": "beta-2"}).status_code == 201

    a_names = [p["name"] for p in client_a.get("/api/v1/projects/").json()["items"]]
    b_names = [p["name"] for p in client_b.get("/api/v1/projects/").json()["items"]]
    assert a_names == ["alpha"]
    assert sorted(b_names) == ["beta-1", "beta-2"]


def test_create_stamps_the_token_tenant(token_client) -> None:
    tenant = uuid.uuid4()
    created = token_client(tenant=tenant).post(
        "/api/v1/projects/", json={"name": "x"}
    ).json()
    assert created["tenant_id"] == str(tenant)


def test_an_authenticated_caller_without_a_tenant_fails_closed(token_client) -> None:
    # The caller is a valid EDITOR (authz passes) but the token carries no tenant
    # claim, so the scoped resource fails closed: reads are empty, writes raise.
    client = token_client(tenant=None)

    listing = client.get("/api/v1/projects/").json()
    assert listing["total"] == 0 and listing["items"] == []

    rejected = client.post("/api/v1/projects/", json={"name": "orphan"})
    assert rejected.status_code == 500
    assert rejected.json()["code"] == "tenant_context_missing"


def test_real_login_yields_a_usable_tenant_token(app_db: FastAPI, make_user) -> None:
    # The *shipped* /auth/login signs a tenant claim (example: by email domain), so a
    # user who logs in normally can immediately use the tenant-scoped projects resource.
    make_user("alice@acme.test", "correct horse battery", Roles.EDITOR)
    client = TestClient(app_db)
    login = client.post(
        "/api/v1/auth/login", json={"email": "alice@acme.test", "password": "correct horse battery"}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    assert decode_access_token(token).tenant is not None  # the login bound a tenant

    client.headers["Authorization"] = f"Bearer {token}"
    assert client.post("/api/v1/projects/", json={"name": "via real login"}).status_code == 201
    assert [p["name"] for p in client.get("/api/v1/projects/").json()["items"]] == [
        "via real login"
    ]


def test_projects_isolated_across_login_tenants(app_db: FastAPI, make_user) -> None:
    make_user("a@acme.test", "correct horse battery", Roles.EDITOR)
    make_user("b@globex.test", "correct horse battery", Roles.EDITOR)

    def _login(email: str) -> TestClient:
        client = TestClient(app_db)
        token = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "correct horse battery"}
        ).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    acme, globex = _login("a@acme.test"), _login("b@globex.test")
    assert acme.post("/api/v1/projects/", json={"name": "acme-only"}).status_code == 201

    # Same login machinery, different email domain -> different tenant -> isolated.
    assert [p["name"] for p in acme.get("/api/v1/projects/").json()["items"]] == ["acme-only"]
    assert globex.get("/api/v1/projects/").json()["items"] == []
