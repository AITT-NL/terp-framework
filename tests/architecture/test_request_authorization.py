"""Overlapping requests cannot share module elevation or cached grant decisions."""

from __future__ import annotations

import asyncio
import threading
import uuid

import httpx
from fastapi import APIRouter, Depends
from sqlmodel import Session, SQLModel, create_engine
from starlette.requests import HTTPConnection

from terp.capabilities.access import AccessService, ModuleRoleService, require_permission, resolve_module_rank
from terp.core import (
    EDITOR, VIEWER, ControlPlane, ModuleAccess, ModuleSpec, Permission,
    PermissionModel, Policy, Principal, create_app, get_session, request_authorization,
)


def test_overlapping_module_requests_keep_context_and_live_grants_separate(tmp_path) -> None:
    permission = Permission("records.export", EDITOR)
    principal = Principal(uuid.uuid4(), VIEWER)
    engine = create_engine(f"sqlite:///{tmp_path / 'request-authz.db'}")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            AccessService().grant(session, principal.id, permission.name)
            ModuleRoleService().assign(session, principal.id, "assigned", EDITOR.rank)
            # A stored assignment has no authority in an unassignable module.
            ModuleRoleService().assign(session, principal.id, "ordinary", EDITOR.rank)

        rendezvous = threading.Barrier(2, timeout=5)
        contexts = {}

        def after_guard(connection: HTTPConnection) -> None:
            context = request_authorization(connection)
            assert context is not None
            contexts[connection.url.path] = context
            # Both guards have now run before either permission dependency can
            # read its context. A process-global last-context cache would fail.
            rendezvous.wait()

        shared_permission_dependency = require_permission(permission.name)

        def router() -> APIRouter:
            result = APIRouter()

            @result.get(
                "/export", response_model=str,
                dependencies=[Depends(after_guard), Depends(shared_permission_dependency)],
            )
            def export() -> str:
                return "authorized export"

            return result

        app = create_app(
            [
                ModuleSpec(
                    name="assigned", router=router(), policy=Policy.default(),
                    permissions=(permission,),
                    access=ModuleAccess(label="Assigned records", assignable=True),
                ),
                ModuleSpec(name="ordinary", router=router(), policy=Policy.default()),
            ],
            discover_capabilities=False,
            principal_provider=lambda: principal,
            control_plane=ControlPlane(permissions=PermissionModel(permissions=(permission,))),
            module_rank_resolver=resolve_module_rank,
        )

        def sessions():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[get_session] = sessions

        async def requests() -> tuple[int, int]:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver",
            ) as client:
                responses = await asyncio.wait_for(
                    asyncio.gather(
                        client.get("/api/v1/assigned/export"),
                        client.get("/api/v1/ordinary/export"),
                    ), timeout=10,
                )
                return tuple(response.status_code for response in responses)

        assert asyncio.run(requests()) == (200, 403)
        assigned = contexts["/api/v1/assigned/export"]
        ordinary = contexts["/api/v1/ordinary/export"]
        assert assigned is not ordinary
        assert assigned.module_rank is not None
        assert ordinary.module_rank is None

        with Session(engine) as session:
            assert AccessService().revoke(session, principal.id, permission.name)
        assert asyncio.run(requests()) == (403, 403)
        assert contexts["/api/v1/assigned/export"] is not assigned
        assert contexts["/api/v1/ordinary/export"] is not ordinary
    finally:
        engine.dispose()
