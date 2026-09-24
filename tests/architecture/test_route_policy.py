"""A route declares its own security posture, and the gate and the pane both read it.

Gate for ADR 0148. A ``Policy`` was a property of a ``ModuleSpec``, so it was a property
of every route in that module at once: ``Policy.public_write`` made the whole router
unauthenticated — the routes that had to be, and any route an author added beside them
later, silently.

What is pinned here is the pair of properties that makes the override safe rather than
merely convenient: the guard applies the route's own policy, and the access projection
applies the *same* one. A projection that kept describing the module would show an
administrator a matrix the gate disagrees with, which is the failure this repository has
already had to repair once.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from terp.core import (
    BootError,
    ModuleSpec,
    Policy,
    Principal,
    Role,
    VIEWER,
    create_app,
    route_policy,
)
from terp.core.authz import endpoint_json
from terp.core.routing import declared_route_policy, effective_policy

_PUBLIC = Policy.public(reason="a test route that must answer without a token")
_PUBLIC_WRITE = Policy.public_write(reason="a test route that must accept a tokenless write")


def _anonymous() -> Principal | None:
    return None


def _viewer() -> Principal:
    return Principal(id=uuid.uuid4(), role=VIEWER)


# --------------------------------------------------------------------------- #
# The declaration itself
# --------------------------------------------------------------------------- #
def test_a_route_without_a_declaration_falls_back_to_its_module() -> None:
    """The default is unchanged, which is what makes this additive."""

    def handler() -> None: ...

    assert declared_route_policy(handler) is None
    assert effective_policy(_PUBLIC, handler) is _PUBLIC


def test_a_stray_attribute_of_the_same_name_is_not_a_policy() -> None:
    """`getattr` alone would accept anything; the resolver checks the type.

    Worth pinning because the failure is silent and one-directional: a truthy stray
    would be *used* as a policy, and `decide` reads `is_public` off it.
    """

    def handler() -> None: ...

    handler.__terp_route_policy__ = "public"  # type: ignore[attr-defined]
    assert declared_route_policy(handler) is None
    assert effective_policy(_PUBLIC, handler) is _PUBLIC


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
def _app(module_policy: Policy, *, guarded_declares: Policy | None) -> TestClient:
    router = APIRouter()

    @router.get("/open")
    @route_policy(_PUBLIC)
    def open_route() -> dict:
        return {"ok": True}

    @router.get("/guarded")
    def guarded_route() -> dict:
        return {"ok": True}

    if guarded_declares is not None:
        route_policy(guarded_declares)(guarded_route)

    app = create_app(
        [ModuleSpec(name="probe", router=router, policy=module_policy)],
        principal_provider=_anonymous,
    )
    return TestClient(app)


def test_a_protected_route_inside_a_public_module_is_refused() -> None:
    """The direction the finding is about: a public neighbourhood stops being enough.

    Before this, both routes below were unauthenticated because their *module* said so.
    """
    client = _app(_PUBLIC, guarded_declares=Policy.default())

    assert client.get("/api/v1/probe/open").status_code == 200
    assert client.get("/api/v1/probe/guarded").status_code == 401


def test_a_public_route_inside_a_protected_module_is_admitted() -> None:
    """The other direction, which is what makes a mixed router expressible at all.

    Without it the only way to open one route in a guarded module was to give the whole
    module a public policy and re-gate the rest by hand.
    """
    client = _app(Policy.default(), guarded_declares=None)

    assert client.get("/api/v1/probe/open").status_code == 200
    assert client.get("/api/v1/probe/guarded").status_code == 401


def test_an_authenticated_caller_still_clears_a_declared_route() -> None:
    """The override replaces the policy; it does not bypass the decision."""
    router = APIRouter()

    @router.get("/admin-only")
    @route_policy(Policy(read=Role("admin", rank=30), write=Role("admin", rank=30)))
    def admin_only() -> dict:
        return {"ok": True}

    app = create_app(
        [ModuleSpec(name="probe", router=router, policy=_PUBLIC)],
        principal_provider=_viewer,
    )
    # A viewer is authenticated and still below the floor the ROUTE declared.
    assert TestClient(app).get("/api/v1/probe/admin-only").status_code == 403


# --------------------------------------------------------------------------- #
# The projection replays the same answer
# --------------------------------------------------------------------------- #
def test_the_access_projection_reports_the_routes_own_policy() -> None:
    """The pane and the gate must not disagree, which is the whole reason for one resolver.

    Reading `spec.policy` here would have reported this route as ``public`` while the
    guard demanded a token — a matrix that is wrong in the direction that matters, since
    an administrator would read it as "anyone can reach this".
    """
    router = APIRouter()

    @router.get("/guarded")
    @route_policy(Policy.default())
    def guarded() -> dict:
        return {"ok": True}

    spec = ModuleSpec(name="probe", router=router, policy=_PUBLIC)
    ladder = [Role("viewer", rank=10)]
    projected = endpoint_json(spec, spec.router.routes[0], ladder)

    assert projected["requirement"] == "role:viewer"
    assert [row["allowed"] for row in projected["by_role"]] == [True]
    assert [row["reason"] for row in projected["by_role"]] == ["allowed"]


def test_the_projection_still_reports_public_where_the_route_says_so() -> None:
    router = APIRouter()

    @router.get("/open")
    @route_policy(_PUBLIC)
    def open_route() -> dict:
        return {"ok": True}

    spec = ModuleSpec(name="probe", router=router, policy=Policy.default())
    projected = endpoint_json(spec, spec.router.routes[0], [Role("viewer", rank=10)])

    assert projected["requirement"] == "public"
    assert [row["reason"] for row in projected["by_role"]] == ["public"]


# --------------------------------------------------------------------------- #
# Boot refuses silence
# --------------------------------------------------------------------------- #
def test_boot_refuses_an_undeclared_route_in_a_public_module() -> None:
    router = APIRouter()

    @router.get("/quietly-public")
    def quietly_public() -> dict:  # declares nothing
        return {"ok": True}

    spec = ModuleSpec(name="probe", router=router, policy=_PUBLIC)
    with pytest.raises(BootError, match="declares no policy of its own"):
        create_app([spec])


def test_boot_refuses_an_undeclared_websocket_in_a_public_module() -> None:
    """A socket has no method after the upgrade, so the guard treats it as a write.

    It is therefore the route that least deserves to be public by inheritance — and the
    one an HTTP-only walk would have missed, which the first version of this check did.
    """
    router = APIRouter()

    @router.websocket("/ws")
    async def socket(websocket) -> None:  # pragma: no cover - never connected
        ...

    spec = ModuleSpec(name="probe", router=router, policy=_PUBLIC_WRITE)
    with pytest.raises(BootError, match="declares no policy of its own"):
        create_app([spec])


def test_a_declared_route_satisfies_the_check_in_a_public_module() -> None:
    router = APIRouter()

    @router.get("/open")
    @route_policy(_PUBLIC)
    def open_route() -> dict:
        return {"ok": True}

    spec = ModuleSpec(name="probe", router=router, policy=_PUBLIC)
    assert create_app([spec]).title == "Terp app"


def test_a_protected_module_needs_no_ritual() -> None:
    """The check asks only of public modules; a safe default stays a safe default."""
    router = APIRouter()

    @router.get("/thing")
    def thing() -> dict:
        return {"ok": True}

    spec = ModuleSpec(name="probe", router=router, policy=Policy.default())
    assert create_app([spec]).title == "Terp app"


def test_a_route_that_opts_out_of_public_does_not_need_the_write_opt_out() -> None:
    """The mutating check reads the route's policy too.

    A route that declared itself protected inside a public module is not an
    unauthenticated write, and demanding ``Policy.public_write`` for a door that is shut
    would have been a refusal nobody could act on sensibly.
    """
    router = APIRouter()

    @router.post("/guarded", status_code=204)
    @route_policy(Policy.default())
    def guarded() -> None: ...

    spec = ModuleSpec(name="probe", router=router, policy=_PUBLIC)
    assert create_app([spec]).title == "Terp app"


def test_a_public_mutating_route_still_needs_the_stronger_opt_out() -> None:
    """The existing refusal survives the move from module to route."""
    router = APIRouter()

    @router.post("/open", status_code=204)
    @route_policy(_PUBLIC)  # public, but not public-WRITE
    def open_route() -> None: ...

    spec = ModuleSpec(name="probe", router=router, policy=_PUBLIC)
    with pytest.raises(BootError, match="Policy.public_write"):
        create_app([spec])
