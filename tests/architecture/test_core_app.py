"""Phase 1+ gate: the promoted ``terp.core`` composition surface (create_app / Page).

Pure-kernel unit checks (no app), complementing the reference-app end-to-end tests.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from starlette.middleware import Middleware

from terp.core.app import build_guard
from terp.core import (
    ADMIN,
    AuditPolicy,
    BootError,
    ControlPlane,
    CorsPolicy,
    EDITOR,
    InMemoryThrottleStore,
    ModuleSpec,
    OperationCatalog,
    OperationCoverage,
    OperationDefinition,
    Page,
    PaginationParams,
    Permission,
    PermissionDeniedError,
    PermissionModel,
    Policy,
    Principal,
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


# --- the API root is a signpost, not a dead end ------------------------------


def test_the_api_root_says_what_it_is_instead_of_answering_not_found() -> None:
    """A Terp app is two addresses, and this is the one people open by mistake.

    No module can claim `/` (every module router is prefixed `/api/v1/<name>`)
    and route registration is frozen after composition, so nothing else ever
    will. FastAPI therefore answered the most reliably reachable address the
    platform has with a bare not-found document, which reads to somebody who
    opened the wrong port as an application that is broken.
    """
    client = TestClient(create_app([], title="Acme"))

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Acme" in response.text
    # The two things the reader came for: this is not the interface, and where
    # the machine-readable surface is.
    assert "user interface is served separately" in response.text
    assert "/docs" in response.text


def test_the_signpost_is_not_part_of_the_contract() -> None:
    """A landing page for a human is not API surface.

    In the document it would become a route in every generated client, for
    something no client calls -- and would move two committed OpenAPI artifacts
    on a change that adds no capability.
    """
    app = create_app([], title="Acme")

    assert "/" not in app.openapi()["paths"]


def test_the_signpost_never_points_at_docs_that_are_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production hides /docs unless the security config opts in.

    Linking it anyway would make this page a second dead end, which is the
    defect it exists to remove rather than to relocate.
    """
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    plane = ControlPlane(
        security=SecurityConfig(cors=CorsPolicy.disabled(reason="api only")),
        audit=AuditPolicy.disabled(reason="not required for this test"),
    )

    app = create_app([], title="Acme", control_plane=plane)
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert app.docs_url is None  # the premise: there is nothing to link to
    assert "/docs" not in response.text
    # Still a signpost: health is public in every environment.
    assert "/health/live" in response.text
    assert "Acme" in response.text


def test_a_title_that_contains_markup_is_escaped() -> None:
    """The title is app-supplied text landing in a document.

    It is not attacker-controlled in any deployment worth naming, but "the
    input is trusted" is the assumption that ages worst, and escaping costs
    nothing.
    """
    response = TestClient(create_app([], title="<script>x</script>")).get("/")

    assert "<script>x</script>" not in response.text
    assert "&lt;script&gt;" in response.text


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


def test_create_app_refuses_a_cycle_of_declared_dependencies() -> None:
    # A cycle means neither module can be read, tested or removed without the other,
    # so the app refuses to boot and the message names the two ways out. The cycle is
    # found through an unrelated module, because the shape a real app grows into is a
    # chain that loops back, not two modules pointing at each other.
    specs = [
        ModuleSpec(name="alerts", policy=Policy.default(), requires=("billing",)),
        ModuleSpec(name="billing", policy=Policy.default(), requires=("invoices",)),
        ModuleSpec(name="invoices", policy=Policy.default(), requires=("billing",)),
    ]
    with pytest.raises(BootError, match="cycle") as exc:
        create_app(specs)
    assert "billing -> invoices -> billing" in str(exc.value)
    assert "terp guide dependencies" in str(exc.value)


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


# --------------------------------------------------------------------------- #
# Declared route operations (ADR 0102)
# --------------------------------------------------------------------------- #
_FILES_DELETE = OperationDefinition(id="files.delete", label="Delete a file")


def _declaring_router(definition: OperationDefinition | None):
    """A one-route router that declares *definition*, or nothing when it is None."""
    from fastapi import APIRouter

    from terp.core import operation

    router = APIRouter()

    if definition is None:

        @router.get("/", response_model=str)
        def read() -> str:
            return "x"

    else:

        @router.get("/", response_model=str)
        @operation(definition)
        def read() -> str:
            return "x"

    return router


def test_an_operation_absent_from_the_catalog_fails_the_boot() -> None:
    # The no-drift half, and it is unconditional: coverage is left at its OFF default
    # here, so this refusal is not the strict-coverage check in disguise.
    spec = ModuleSpec(
        name="files", router=_declaring_router(_FILES_DELETE), policy=Policy.default()
    )
    with pytest.raises(BootError, match="not the entry registered"):
        create_app([spec], control_plane=ControlPlane())


def test_a_same_id_operation_with_different_wording_is_refused() -> None:
    # Matched by VALUE: a look-alike sharing the id would let a route present one
    # wording while the catalog documents another, which is exactly the drift the
    # catalog exists to prevent. The ids are identical on purpose — only the label
    # differs, so an id-only comparison would accept this and the test would pass
    # with the bug present.
    shadow = OperationDefinition(id="files.delete", label="Remove a file for good")
    spec = ModuleSpec(
        name="files", router=_declaring_router(shadow), policy=Policy.default()
    )
    plane = ControlPlane(operations=OperationCatalog(operations=(_FILES_DELETE,)))
    with pytest.raises(BootError, match="not the entry registered"):
        create_app([spec], control_plane=plane)


def test_a_declared_operation_in_the_catalog_boots() -> None:
    spec = ModuleSpec(
        name="files", router=_declaring_router(_FILES_DELETE), policy=Policy.default()
    )
    plane = ControlPlane(operations=OperationCatalog(operations=(_FILES_DELETE,)))
    assert create_app([spec], control_plane=plane).title == "Terp app"


def test_an_undeclared_route_boots_with_coverage_off_and_is_refused_under_strict() -> None:
    # The feature is optional, the guarantee is not. Both halves in one test because
    # each is only meaningful against the other: if OFF refused, the control would be
    # a breaking change for every existing app; if STRICT accepted, there would be no
    # state in which "every route is explained" is true.
    spec = ModuleSpec(
        name="files", router=_declaring_router(None), policy=Policy.default()
    )
    assert create_app([spec], control_plane=ControlPlane()).title == "Terp app"

    strict = ControlPlane(
        operations=OperationCatalog(coverage=OperationCoverage.STRICT)
    )
    with pytest.raises(BootError, match="coverage is STRICT"):
        create_app([spec], control_plane=strict)


def test_strict_coverage_reaches_a_route_on_an_included_sub_router() -> None:
    """A guarantee that stopped at the top level is one an app sidesteps by nesting.

    The assertion is on the reported *path*, not merely that the boot failed. Measured
    reason: ``include_router`` keeps the child as an ``_IncludedRouter`` whose own
    ``path`` is ``None``, so a validator that iterated ``router.routes`` directly would
    still refuse the boot — counting that wrapper as an undeclared route — and a test
    asserting only "it raised" would pass with the traversal broken. Naming
    ``/nested-leaf`` is what distinguishes walking the tree from tripping over its root.
    """
    from fastapi import APIRouter

    child = APIRouter()

    @child.get("/nested-leaf", response_model=str)
    def leaf() -> str:
        return "x"

    parent = APIRouter()
    parent.include_router(child)
    spec = ModuleSpec(name="files", router=parent, policy=Policy.default())
    strict = ControlPlane(
        operations=OperationCatalog(coverage=OperationCoverage.STRICT)
    )
    with pytest.raises(BootError, match="nested-leaf"):
        create_app([spec], control_plane=strict)


def test_declaring_an_operation_does_not_change_authorization() -> None:
    """The promise read_only makes: saying what a route does narrows nothing.

    Observed by comparing the access graph for two routers that differ ONLY in whether
    the route declares an operation — same policy, same method, same path. Every
    authorization-bearing field must be identical. The first version of this test
    asserted build_guard's read/write tier split instead, which is true whether or not
    operations exist anywhere, so it would have passed had operation() rewritten the
    policy outright.
    """
    from terp.cli.access import build_access_graph

    plane = ControlPlane(operations=OperationCatalog(operations=(_FILES_DELETE,)))

    def graph_for(definition: OperationDefinition | None) -> dict:
        spec = ModuleSpec(
            name="files", router=_declaring_router(definition), policy=Policy.default()
        )
        return build_access_graph(plane, [spec])["modules"][0]

    declared = graph_for(_FILES_DELETE)
    plain = graph_for(None)

    assert declared["policy"] == plain["policy"]
    for field in ("requirement", "extra_permissions", "methods", "path"):
        assert [e[field] for e in declared["endpoints"]] == [
            e[field] for e in plain["endpoints"]
        ], f"declaring an operation changed {field!r}"

    # ...and the declaration really is present, so the comparison is between a
    # declaring route and a plain one rather than between two plain ones.
    assert declared["endpoints"][0]["operation"] == {
        "id": "files.delete",
        "label": "Delete a file",
    }
    assert plain["endpoints"][0]["operation"] is None


def test_warn_coverage_reports_what_strict_would_refuse(caplog) -> None:
    """WARN has to say something, or it is OFF wearing a different name.

    It is the staging step on the way to STRICT becoming the default, and afterwards the
    documented escape for an app that cannot annotate yet — both of which require it to
    actually name the routes STRICT would refuse. As first written nothing branched on
    WARN at all, so it behaved identically to OFF while its docstring described
    reporting; the assertion below is on the route appearing in the log, not merely on a
    successful boot, because a successful boot is what OFF gives too.
    """
    import logging

    spec = ModuleSpec(
        name="files", router=_declaring_router(None), policy=Policy.default()
    )
    warn = ControlPlane(operations=OperationCatalog(coverage=OperationCoverage.WARN))
    with caplog.at_level(logging.WARNING, logger="terp.core"):
        assert create_app([spec], control_plane=warn).title == "Terp app"
    assert "files:GET /" in caplog.text
    assert "WARN" in caplog.text

    # OFF is silent about the same app: the two settings are distinguishable.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="terp.core"):
        create_app([spec], control_plane=ControlPlane())
    assert caplog.text == ""


def test_strict_coverage_is_satisfied_by_a_fully_annotated_app() -> None:
    """The behaviour strict-as-default rests on, and the only one not previously tested.

    Both earlier STRICT tests asserted a refusal. A validator that refused every app —
    the trivially over-strict failure — would have passed both of them, and would have
    made STRICT unusable as a default the moment it was flipped.
    """
    spec = ModuleSpec(
        name="files", router=_declaring_router(_FILES_DELETE), policy=Policy.default()
    )
    strict = ControlPlane(
        operations=OperationCatalog(
            operations=(_FILES_DELETE,), coverage=OperationCoverage.STRICT
        )
    )
    assert create_app([spec], control_plane=strict).title == "Terp app"


def test_a_websocket_route_is_held_to_both_halves_of_the_control() -> None:
    """A WebSocket route is mounted, callable surface and must be explained like any other.

    It used to escape both halves, because the walk yielded only ``APIRoute``: an
    undeclared WebSocket passed STRICT, and an operation absent from the catalog was
    accepted there while the *identical* declaration was refused on a ``GET`` — so the
    guarantee described as unconditional was conditional on the route class. This is not
    hypothetical surface: `terp.capabilities.realtime` ships one on its module router.
    """
    from fastapi import APIRouter, WebSocket

    from terp.core import operation

    plain = APIRouter()

    @plain.websocket("/ws")
    async def socket(websocket: WebSocket) -> None: ...

    spec = ModuleSpec(name="rt", router=plain, policy=Policy.default())
    strict = ControlPlane(
        operations=OperationCatalog(coverage=OperationCoverage.STRICT)
    )
    with pytest.raises(BootError, match="rt:WS /ws"):
        create_app([spec], control_plane=strict)

    # The no-drift half applies to it too, with coverage left OFF so this refusal
    # cannot be the coverage check in disguise.
    ghost = OperationDefinition(id="ghost.op", label="Not in the catalog")
    drifting = APIRouter()

    @drifting.websocket("/ws")
    @operation(ghost)
    async def drift(websocket: WebSocket) -> None: ...

    spec2 = ModuleSpec(name="rt", router=drifting, policy=Policy.default())
    with pytest.raises(BootError, match="not the entry registered"):
        create_app([spec2], control_plane=ControlPlane())


def test_operation_refuses_an_argument_that_is_not_a_definition() -> None:
    """A mistyped argument must fail where it is written, not go silently undeclared.

    Stamping whatever was passed meant `declared_operation` discarded it for failing its
    type check, so the route declared nothing at all — invisible under permissive
    coverage, and under STRICT a boot refusal naming the route rather than the mistake.
    """
    from terp.core import operation

    with pytest.raises(TypeError, match="OperationDefinition"):
        operation("files.delete")
    with pytest.raises(TypeError, match="OperationDefinition"):
        operation(None)


def test_a_declared_operation_populates_openapi_summary_and_operation_id() -> None:
    """ADR 0102 phase 4: the declaration feeds a second reader, the exported document.

    Asserted against the real generated schema (app.openapi()), not the route object,
    because that is what a generated client or terp openapi actually sees, and because
    FastAPI reads both fields live at schema-generation time rather than from a value
    cached at route construction -- asserting on the route object would pass even if
    that laziness broke.
    """
    spec = ModuleSpec(
        name="files", router=_declaring_router(_FILES_DELETE), policy=Policy.default()
    )
    plane = ControlPlane(operations=OperationCatalog(operations=(_FILES_DELETE,)))
    app = create_app([spec], control_plane=plane)
    get_op = app.openapi()["paths"]["/api/v1/files/"]["get"]
    assert get_op["summary"] == "Delete a file"
    assert get_op["operationId"] == "files.delete"

    # A route that declares nothing is untouched: FastAPI's own generated fallback,
    # not something this control invented for it.
    plain_spec = ModuleSpec(
        name="files", router=_declaring_router(None), policy=Policy.default()
    )
    plain_app = create_app([plain_spec], control_plane=ControlPlane())
    plain_get_op = plain_app.openapi()["paths"]["/api/v1/files/"]["get"]
    assert plain_get_op["summary"] != "Delete a file"
    assert plain_get_op["operationId"] != "files.delete"


def test_applying_a_declared_operation_twice_over_the_same_router_is_not_a_conflict() -> None:
    """create_app is routinely called more than once over the same router objects.

    A module's router is built once at import time (module-level `router =
    APIRouter()`); `create_app` mounting it twice in one process (the example app's
    full profile and base profile both boot from the same capability routers, and
    so does any test suite that builds the same app more than once) must not treat
    the summary THIS control itself set on the first call as a hand-written
    conflict on the second. A regression here is a boot failure on the *second*
    `create_app` call only — the first alone would not have caught it.
    """
    spec = ModuleSpec(
        name="files", router=_declaring_router(_FILES_DELETE), policy=Policy.default()
    )
    plane = ControlPlane(operations=OperationCatalog(operations=(_FILES_DELETE,)))
    create_app([spec], control_plane=plane)  # first call: applies the label
    app = create_app([spec], control_plane=plane)  # second call: must not re-raise
    assert app.openapi()["paths"]["/api/v1/files/"]["get"]["summary"] == "Delete a file"


def test_a_hand_written_summary_beside_a_declared_operation_is_refused() -> None:
    """Two answers to the same promise (ADR 0102 S4), refused at boot.

    Mirrors the refusal declared_read_only_routes_do_not_write names for @read_only
    plus a write in the same handler: the mere presence of the second answer is the
    defect, independent of whether the two summaries happen to agree.
    """
    from terp.core import operation

    router = APIRouter()

    @router.get("/", response_model=str, summary="Remove the file for good")
    @operation(_FILES_DELETE)
    def delete() -> str:
        return "x"

    spec = ModuleSpec(name="files", router=router, policy=Policy.default())
    plane = ControlPlane(operations=OperationCatalog(operations=(_FILES_DELETE,)))
    with pytest.raises(BootError, match="two answers to the same promise"):
        create_app([spec], control_plane=plane)


# --------------------------------------------------------------------------- #
# what an operation declaration refuses (ADR 0102)
# --------------------------------------------------------------------------- #
def test_an_operation_id_must_be_a_dotted_token() -> None:
    """The id is the i18n message id and the catalog key, so a loose string would
    make the catalog's own lookups ambiguous."""
    from terp.core import OperationDefinition

    with pytest.raises(ValueError, match="id"):
        OperationDefinition(id="not a dotted token", label="Do a thing")


def test_an_operation_needs_a_label_a_person_can_read() -> None:
    """The whole point is that a non-technical reader can see what a route does;
    a blank label is the one value that cannot do that."""
    from terp.core import OperationDefinition

    with pytest.raises(ValueError, match="label"):
        OperationDefinition(id="thing.do", label="   ")


def test_a_catalog_refuses_the_same_id_twice() -> None:
    """Two declarations under one id means the catalog is no longer the single
    source of truth for what that id says."""
    from terp.core import OperationCatalog, OperationDefinition

    first = OperationDefinition(id="thing.do", label="Do the thing")
    second = OperationDefinition(id="thing.do", label="Do it differently")
    with pytest.raises(ValueError, match="duplicate operation"):
        OperationCatalog(operations=(first, second))


def test_a_sibilant_noun_pluralises_with_es() -> None:
    """`box` -> `boxes`, not `boxs`. The CRUD factory names a module's routes from
    its noun, so this shows up in every generated summary and operation id."""
    from terp.core.crud import _plural

    assert _plural("box") == "boxes"
    assert _plural("batch") == "batches"
    assert _plural("note") == "notes"
    assert _plural("company") == "companies"
