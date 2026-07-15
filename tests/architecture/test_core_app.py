"""Phase 1+ gate: the promoted ``terp.core`` composition surface (create_app / Page).

Pure-kernel unit checks (no app), complementing the reference-app end-to-end tests.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from starlette.middleware import Middleware

from terp.core import (
    ADMIN,
    BootError,
    ControlPlane,
    EDITOR,
    InMemoryThrottleStore,
    ModuleSpec,
    Page,
    PaginationParams,
    Permission,
    PermissionModel,
    Policy,
    SecurityConfig,
    VIEWER,
    create_app,
    get_principal,
    get_session,
    mark_shared_throttle_store,
    settings,
)


def test_create_app_boots_closed_without_policy() -> None:
    with pytest.raises(BootError):
        create_app([ModuleSpec(name="nopolicy")])


def test_create_app_builds_with_policy() -> None:
    app = create_app([ModuleSpec(name="ok", policy=Policy.default())])
    assert any(getattr(route, "path", "").startswith("/api/v1/ok") for route in app.routes) is False
    # No router was attached to the spec, so no /api/v1/ok routes exist; the app
    # still builds. (Routers are exercised end-to-end in the example app.)
    assert app.title == "Terp app"


def test_create_app_refuses_route_registration_after_composition() -> None:
    app = create_app([])

    def endpoint() -> dict:  # pragma: no cover - never called
        return {}

    for action in (
        lambda: app.add_api_route("/raw", endpoint),
        lambda: app.get("/raw")(endpoint),
        lambda: app.mount("/static", create_app([])),
        lambda: app.router.add_api_route("/raw", endpoint),
        lambda: app.on_event("startup")(endpoint),
        lambda: app.router.add_event_handler("startup", endpoint),
    ):
        with pytest.raises(BootError, match="after create_app"):
            action()


class _HeaderStampMiddleware:
    """A minimal pure-ASGI middleware stamping a response header (composition probe)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        async def stamped(message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message["headers"], (b"x-composed", b"yes")]
            await send(message)

        await self.app(scope, receive, stamped)


def test_create_app_refuses_middleware_registration_after_composition() -> None:
    # Runtime half of the no_adhoc_middleware rule: once composed, both middleware
    # registration spellings fail closed — create_app(middleware=[...]) is the seam.
    app = create_app([])

    async def http_middleware(request, call_next):  # pragma: no cover - never called
        return await call_next(request)

    for action in (
        lambda: app.add_middleware(_HeaderStampMiddleware),
        lambda: app.middleware("http")(http_middleware),
    ):
        with pytest.raises(BootError, match="after create_app"):
            action()


def test_create_app_middleware_parameter_remains_the_sanctioned_seam() -> None:
    # The one sanctioned wiring path keeps working: middleware passed at composition
    # is installed and runs (the freeze refuses only post-composition registration).
    app = create_app([], middleware=[Middleware(_HeaderStampMiddleware)])
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.headers["x-composed"] == "yes"


def test_dependency_overrides_stay_writable_in_the_local_environment() -> None:
    # Overrides are the sanctioned TEST-ONLY seam: a local (dev/test) composition
    # keeps the writable map, so a consumer's test suite can override get_session.
    app = create_app([])

    def _sentinel() -> None:  # pragma: no cover - never called
        return None

    app.dependency_overrides[get_session] = _sentinel
    assert app.dependency_overrides[get_session] is _sentinel


def test_dependency_overrides_freeze_outside_the_local_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Runtime half of the no_dependency_overrides rule: a deployed composition
    # (staging/production) hands back a refusing map — reads keep serving, every
    # mutating spelling fails closed, and the composition-bound override survives.
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")

    def _provider() -> None:
        return None

    app = create_app([], principal_provider=_provider)
    assert app.dependency_overrides[get_principal] is _provider  # bound pre-freeze
    assert TestClient(app).get("/health/live").status_code == 200  # reads still work

    overrides = app.dependency_overrides
    for action in (
        lambda: overrides.__setitem__(get_session, _provider),
        lambda: overrides.__delitem__(get_principal),
        lambda: overrides.update({get_session: _provider}),
        lambda: overrides.clear(),
        lambda: overrides.pop(get_principal),
        lambda: overrides.popitem(),
        lambda: overrides.setdefault(get_session, _provider),
        lambda: overrides.__ior__({get_session: _provider}),
    ):
        with pytest.raises(BootError, match="after create_app"):
            action()
    assert app.dependency_overrides[get_principal] is _provider  # nothing slipped through


def test_page_of_builds_envelope() -> None:
    page = Page[int].of([1, 2, 3], total=3, pagination=PaginationParams(skip=0, limit=10))
    assert page.model_dump() == {"items": [1, 2, 3], "total": 3, "skip": 0, "limit": 10}


# --------------------------------------------------------------------------- #
# Per-module request-size allowances (ADR 0067)
# --------------------------------------------------------------------------- #
def _echo_spec(name: str, **spec_kwargs) -> ModuleSpec:
    """A public POST module that reports how many body bytes reached the handler."""
    router = APIRouter()

    @router.post("/")
    async def echo(request: Request) -> dict:
        return {"received": len(await request.body())}

    return ModuleSpec(
        name=name,
        router=router,
        policy=Policy.public_write(reason="size-limit probe"),
        **spec_kwargs,
    )


def test_spec_declared_max_request_bytes_lifts_only_its_own_prefix() -> None:
    app = create_app(
        [_echo_spec("files", max_request_bytes=100), _echo_spec("notes")],
        control_plane=ControlPlane(security=SecurityConfig(max_request_bytes=10)),
    )
    client = TestClient(app)
    body = b"x" * 50  # over the 10-byte global cap, under the files allowance
    assert client.post("/api/v1/files/", content=body).status_code == 200
    assert client.post("/api/v1/notes/", content=body).status_code == 413


def test_explicit_request_size_override_wins_over_the_declared_default() -> None:
    app = create_app(
        [_echo_spec("files", max_request_bytes=20)],
        control_plane=ControlPlane(security=SecurityConfig(max_request_bytes=10)),
        request_size_overrides={"files": 100},
    )
    response = TestClient(app).post("/api/v1/files/", content=b"x" * 50)
    assert response.status_code == 200  # 50 > declared 20, allowed by the explicit 100


def test_request_size_override_for_an_unknown_module_fails_the_boot() -> None:
    with pytest.raises(BootError, match="request_size_overrides names 'ghost'"):
        create_app(
            [ModuleSpec(name="ok", policy=Policy.default())],
            request_size_overrides={"ghost": 100},
        )


def test_request_size_override_must_be_positive() -> None:
    with pytest.raises(BootError, match="must be a positive byte count"):
        create_app([_echo_spec("files")], request_size_overrides={"files": 0})


def test_a_routerless_spec_contributes_no_request_size_allowance() -> None:
    """An unmounted prefix must never accept a bigger body (nothing routes there)."""
    from terp.core.app import _request_size_override_map

    spec = ModuleSpec(name="library", policy=Policy.default(), max_request_bytes=100)
    assert _request_size_override_map([spec], None) == {}
    # ...and being router-less also makes it invalid as an explicit override target.
    with pytest.raises(BootError, match="not a mounted"):
        _request_size_override_map([spec], {"library": 100})


def test_create_app_fails_closed_on_missing_requires() -> None:
    dependent = ModuleSpec(name="billing", policy=Policy.default(), requires=("users",))
    with pytest.raises(BootError):
        create_app([dependent])


def test_create_app_boots_when_requires_are_satisfied() -> None:
    provider = ModuleSpec(name="users", policy=Policy.default())
    dependent = ModuleSpec(name="billing", policy=Policy.default(), requires=("users",))
    app = create_app([provider, dependent])
    assert app.title == "Terp app"


def test_create_app_rejects_duplicate_spec_names() -> None:
    with pytest.raises(BootError, match="declared more than once"):
        create_app(
            [
                ModuleSpec(name="users", policy=Policy.default()),
                ModuleSpec(name="users", policy=Policy.default()),
            ]
        )


def test_create_app_validates_control_plane_policy_references() -> None:
    billing_read = Permission("billing.read", min_role=VIEWER)
    billing_write = Permission("billing.write", min_role=VIEWER)
    control_plane = ControlPlane(
        permissions=PermissionModel(permissions=[billing_read])
    )
    spec = ModuleSpec(
        name="billing",
        policy=Policy(read=billing_read, write=billing_write),
    )
    with pytest.raises(BootError, match="permission:billing.write"):
        create_app([spec], control_plane=control_plane)


def test_create_app_accepts_registered_permission_policy() -> None:
    billing_read = Permission("billing.read", min_role=VIEWER)
    control_plane = ControlPlane(permissions=PermissionModel(permissions=[billing_read]))
    spec = ModuleSpec(name="billing", policy=Policy(read=billing_read, write=VIEWER))
    # A permission requirement now needs an enforcer so it is honored as a real
    # grant rather than collapsing to a role rank (ADR 0016).
    app = create_app(
        [spec], control_plane=control_plane, permission_enforcer=lambda _s, _i, _n: True
    )
    assert app.title == "Terp app"


def test_entry_point_discovery_finds_installed_capabilities() -> None:
    from terp.core._internal.discovery import iter_capability_specs

    names = {spec.name for spec in iter_capability_specs()}
    # terp-cap-users self-registers its `users` ModuleSpec via an entry point.
    assert "users" in names


def test_create_app_wraps_discovery_errors_as_boot_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import terp.core.app as app_module

    def _boom() -> list[ModuleSpec]:
        raise RuntimeError("entry point broke")

    monkeypatch.setattr(app_module, "iter_capability_specs", _boom)
    with pytest.raises(BootError, match="capability discovery failed"):
        create_app([], discover_capabilities=True)


def test_create_app_rejects_capability_names_without_discovery() -> None:
    with pytest.raises(BootError, match="capability_names requires"):
        create_app([], capability_names=["users"])


def test_create_app_filters_discovered_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    import terp.core.app as app_module

    seen: list[tuple[str, ...] | None] = []

    def _fake(names=None) -> list[ModuleSpec]:
        seen.append(tuple(names) if names is not None else None)
        return []

    monkeypatch.setattr(app_module, "iter_capability_specs", _fake)
    create_app([], discover_capabilities=True, capability_names=["users"])
    assert seen == [("users",)]


def test_create_app_fails_closed_on_permission_policy_without_enforcer() -> None:
    publish = Permission("widgets.publish", min_role=EDITOR)
    plane = ControlPlane(permissions=PermissionModel(permissions=[publish]))
    spec = ModuleSpec(name="widgets", policy=Policy(read=VIEWER, write=publish))
    with pytest.raises(BootError, match="permission_enforcer"):
        create_app([spec], control_plane=plane)


def test_create_app_boots_permission_policy_with_enforcer() -> None:
    publish = Permission("widgets.publish", min_role=EDITOR)
    plane = ControlPlane(permissions=PermissionModel(permissions=[publish]))
    spec = ModuleSpec(name="widgets", policy=Policy(read=VIEWER, write=publish))
    app = create_app(
        [spec], control_plane=plane, permission_enforcer=lambda _s, _i, _n: False
    )
    assert app.title == "Terp app"


def _mutating_router():
    from fastapi import APIRouter

    router = APIRouter()

    @router.post("/", status_code=204)
    def create() -> None: ...

    return router


def test_create_app_fails_closed_on_an_inverted_write_tier() -> None:
    # Writes require EDITOR (rank 20) but reads require ADMIN (rank 30): a reader could
    # write — a privilege inversion the boot guard refuses for ANY role model (the runtime
    # half of mutations_require_write_role, which cannot see a custom role's rank).
    spec = ModuleSpec(
        name="widgets", router=_mutating_router(), policy=Policy(read=ADMIN, write=EDITOR)
    )
    with pytest.raises(BootError, match="privilege inversion"):
        create_app([spec])


def test_create_app_allows_equal_write_and_read_tiers() -> None:
    # Equality is allowed (an admin-only / flat model): read=write=ADMIN boots fine.
    spec = ModuleSpec(
        name="widgets", router=_mutating_router(), policy=Policy(read=ADMIN, write=ADMIN)
    )
    assert create_app([spec]).title == "Terp app"


def test_create_app_skips_the_write_tier_check_for_a_read_only_router() -> None:
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/", response_model=dict)
    def show() -> dict: ...

    # No mutating route, so a low write tier under a high read tier is not a write-surface
    # inversion — the check does not apply and the app boots.
    spec = ModuleSpec(name="reports", router=router, policy=Policy(read=ADMIN, write=VIEWER))
    assert create_app([spec]).title == "Terp app"


def test_create_app_fails_closed_on_public_mutating_router() -> None:
    spec = ModuleSpec(
        name="widgets",
        router=_mutating_router(),
        policy=Policy.public(reason="read-only public docs"),
    )
    with pytest.raises(BootError, match="Policy.public_write"):
        create_app([spec])


def test_create_app_allows_explicit_public_write_opt_out() -> None:
    spec = ModuleSpec(
        name="login",
        router=_mutating_router(),
        policy=Policy.public_write(reason="login endpoint"),
    )
    assert create_app([spec]).title == "Terp app"


def test_create_app_requires_a_shared_throttle_store_when_asked() -> None:
    # The per-instance default is refused when the app promises a global limit.
    with pytest.raises(BootError, match="shared, multi-instance"):
        create_app(
            [ModuleSpec(name="ok", policy=Policy.default())],
            require_shared_throttle_store=True,
        )


def test_create_app_accepts_a_marked_shared_throttle_store() -> None:
    store = mark_shared_throttle_store(InMemoryThrottleStore())
    app = create_app(
        [ModuleSpec(name="ok", policy=Policy.default())],
        throttle_store=store,
        require_shared_throttle_store=True,
    )
    assert app.title == "Terp app"
