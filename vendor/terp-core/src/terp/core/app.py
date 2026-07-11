"""Composition root: deny-by-default app assembly + policy guard + error envelope.

These pieces carry **no domain logic**, so they belong in the kernel (ADR 0001,
Decision 4). An app declares ``ModuleSpec``s; ``create_app`` mounts each router
behind a guard derived from its ``Policy`` and renders every ``AppError`` as the
uniform envelope.

Authentication is intentionally *not* here. ``get_principal`` is a seam that
defaults to unauthenticated and is overridden by the auth capability (or tests);
the kernel owns only the **authorization** check (role vs policy), consistent
with it owning ``Policy`` / ``Roles``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import get_args, get_origin

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel
from starlette.middleware import Middleware

from terp.core.audit import (
    AuditSink,
    bind_audit_actor,
    configure_audit,
    is_durable_audit_sink,
)
from terp.core.config import get_settings
from terp.core.control_plane import ControlPlane
from terp.core.db import get_session
from terp.core.errors import (
    AppError,
    AuthenticationError,
    PermissionDeniedError,
    build_error_envelope,
)
from terp.core.cache import CacheStore, configure_cache, is_shared_cache_store
from terp.core.events import EventDispatcher, configure_events
from terp.core.health import build_health_router
from terp.core.idempotency import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    is_shared_idempotency_store,
)
from terp.core.jobs import JobQueue, configure_jobs, is_durable_job_queue
from terp.core.logging import configure_logging, get_request_id
from terp.core.scheduling import configure_schedules
from terp.core._internal.discovery import iter_capability_specs
from terp.core._internal.engine import get_engine
from terp.core._internal.middleware import install_security_middleware
from terp.core._internal.session_guard import read_only_request
from terp.core.module_spec import ModuleSpec, Policy
from terp.core.passwords import configure_password_policy
from terp.core.throttling import (
    InMemoryThrottleStore,
    ThrottleStore,
    is_shared_throttle_store,
)
from terp.core.permissions import PermissionModel, Role, as_role

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Safe (RFC 9110) HTTP methods: the deny-by-default guard authorizes these against
# the policy's *read* requirement, so a handler bound to one must not mutate (a write
# would run at the read tier). create_app marks such a request read-only at runtime.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_logger = logging.getLogger("terp.core")

# The seam the access capability fills so the guard can enforce a permission as a
# real per-subject grant: (session, subject_id, permission_name) -> holds it?
PermissionEnforcer = Callable[[Session, uuid.UUID, str], bool]


class BootError(RuntimeError):
    """Raised when a module is misconfigured at composition time (fail closed)."""


@dataclass(frozen=True)
class Principal:
    """The authenticated caller the authorization guard checks.

    Identity + role only. ``role`` is a typed :class:`~terp.core.Role`; the legacy
    ``Roles`` enum is accepted and normalized, so a consumer can issue a principal
    bearing any role from its own permission model. *Authentication* (verifying
    credentials, issuing tokens) is the auth capability's job.
    """

    id: uuid.UUID
    role: Role

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", as_role(self.role))


def get_principal() -> Principal | None:
    """Auth seam: the current principal, or ``None`` when unauthenticated.

    Defaults to ``None``. The auth capability (or a test) overrides this FastAPI
    dependency to supply a real principal.
    """
    return None


# An attribute stamped on a principal provider that re-validates the token against the
# store every request (so a revoked / deactivated / re-issued token is rejected
# mid-session, ADR 0031). The marker mirrors the ``DurableAuditSink`` audit-sink marker
# (ADR 0007/0014): a capability stamps it, the kernel boot guard checks it, and neither
# imports the other.
_TOKEN_REVOCATION_ATTR = "__terp_enforces_token_revocation__"


def mark_token_revocation_provider(
    provider: Callable[..., Principal | None],
) -> Callable[..., Principal | None]:
    """Mark *provider* as enforcing token revocation, and return it.

    The auth capability stamps the provider that ``build_get_principal(token_validator=…)``
    returns. ``create_app(require_token_revocation=True)`` consults the marker and fails
    closed at boot when the configured provider lacks it — so an app that *declares* it
    needs prompt revocation can never silently ship the stateless, no-revocation provider.
    """
    setattr(provider, _TOKEN_REVOCATION_ATTR, True)
    return provider


def enforces_token_revocation(provider: Callable[..., Principal | None]) -> bool:
    """Return whether *provider* is a principal provider marked as revocation-enforcing."""
    return bool(getattr(provider, _TOKEN_REVOCATION_ATTR, False))


def build_guard(
    policy: Policy,
    principal_provider: Callable[..., Principal | None] = get_principal,
    permission_enforcer: PermissionEnforcer | None = None,
    permission_model: PermissionModel | None = None,
) -> Callable[..., None]:
    """Build a FastAPI dependency enforcing *policy* (deny-by-default).

    *principal_provider* is the seam an auth capability fills (default: the
    kernel's unauthenticated ``get_principal``).

    A **role** requirement is enforced by rank. A **permission** requirement
    (``Policy(write=Permission(...))``) is enforced as a real per-subject grant:
    the caller must clear the permission's ``min_role`` rank floor **and** hold the
    named permission, checked through *permission_enforcer* (the seam the access
    capability fills — ``terp.capabilities.access.enforce_permission``). The
    permission name is therefore never silently degraded to "any role of that
    rank"; without an enforcer a permission requirement denies fail-closed (and
    ``create_app`` refuses to boot, so the misconfiguration is caught early).
    """

    def guard(
        request: Request,
        principal: Principal | None = Depends(principal_provider),
        session: Session = Depends(get_session),
    ) -> None:
        if policy.is_public:
            return
        if principal is None:
            raise AuthenticationError()
        if permission_model is not None and not permission_model.has_role(principal.role):
            raise PermissionDeniedError()
        required = (
            policy.write_requirement
            if request.method in _MUTATING_METHODS
            else policy.read_requirement
        )
        if principal.role.rank < required.min_rank:
            raise PermissionDeniedError()
        if required.kind == "permission" and (
            permission_enforcer is None
            or not permission_enforcer(session, principal.id, required.name)
        ):
            raise PermissionDeniedError()

    return guard


def build_audit_actor_binder(
    principal_provider: Callable[..., Principal | None] = get_principal,
) -> Callable[..., AsyncIterator[None]]:
    """Build the dependency that binds the caller into the audit actor context.

    ``create_app`` mounts this on every router so an auto-emitted audit record
    knows *who* acted, resolved through the same principal seam the guard uses —
    without a module ever threading the actor through its service calls. The
    binding is request-scoped (set on entry, reset on exit) so it cannot leak
    across requests that share a worker thread. It is an **async** dependency so
    the set/reset pair runs in a single context (a threadpooled sync dependency
    would reset the context var from a different worker context and fail).
    """

    async def binder(
        principal: Principal | None = Depends(principal_provider),
    ) -> AsyncIterator[None]:
        actor_id = principal.id if principal is not None else None
        with bind_audit_actor(actor_id):
            yield

    return binder


def build_read_only_request_binder() -> Callable[..., AsyncIterator[None]]:
    """Build the dependency that marks a safe-method request read-only.

    ``create_app`` mounts this on every module router (beside the audit-actor binder)
    so a write through the ``BaseService`` chokepoint during a safe HTTP method
    (``GET`` / ``HEAD`` / ``OPTIONS``) fails closed
    (:class:`~terp.core._internal.session_guard.ReadOnlyRequestError`). The
    deny-by-default guard authorizes a safe method against the policy's *read*
    requirement, so without this a mutating safe-method handler would perform a write
    a read-tier caller cleared (a privilege-tier escape). It is the runtime half of
    the build-time ``safe_methods_are_read_only`` rule. Like the audit-actor binder it
    is **async** (so the flag is set once and propagates into the threadpooled sync
    route) and request-scoped (set on entry, reset on exit).
    """

    async def binder(request: Request) -> AsyncIterator[None]:
        with read_only_request(request.method.upper() in _SAFE_METHODS):
            yield

    return binder


def _resolve_request_id(request: Request) -> str:
    """The request's correlation id: middleware-stamped, context var, or a fresh one."""
    return (
        getattr(request.state, "request_id", None)
        or get_request_id()
        or str(uuid.uuid4())
    )


def register_error_handlers(app: FastAPI) -> None:
    """Render errors as the uniform ``{code, detail, request_id}`` envelope.

    Typed :class:`AppError`s keep their status and ``code``; any *unexpected*
    exception is logged (with the request id) and rendered as a generic 500
    envelope, so a bug never leaks a stack trace nor escapes the uniform contract.
    """

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_envelope(exc, request_id=_resolve_request_id(request)),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        request_id = _resolve_request_id(request)
        _logger.error("unhandled exception [request_id=%s]", request_id, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "detail": "An unexpected error occurred.",
                "request_id": request_id,
            },
        )


_APP_ROUTE_MUTATORS = frozenset(
    {
        "mount",
        "include_router",
        "add_route",
        "add_api_route",
        "add_websocket_route",
        "add_api_websocket_route",
        "route",
        "api_route",
        "websocket",
        "websocket_route",
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "options",
        "head",
        "trace",
    }
)


def _refuse_route_mutation(name: str) -> Callable[..., None]:
    def refused(*_args: object, **_kwargs: object) -> None:
        raise BootError(
            f"route registration via {name}(...) after create_app() composition is refused; "
            "declare routes on a module APIRouter and expose it via ModuleSpec.router"
        )

    return refused


def _freeze_app_route_registration(app: FastAPI) -> None:
    """Runtime half of ``no_raw_app_routes``: no post-composition surface.

    ``create_app`` is the only code path allowed to mount routers because it injects
    the module policy guard at mount time. Once the app is composed, route mutation on
    the app or its underlying router is a guard bypass, so every registration spelling
    fails closed.
    """
    for target_name, target in (("app", app), ("app.router", app.router)):
        for method in _APP_ROUTE_MUTATORS:
            if hasattr(target, method):
                setattr(target, method, _refuse_route_mutation(f"{target_name}.{method}"))


def _validate_requires(specs: Sequence[ModuleSpec]) -> None:
    """Fail closed if any spec's declared ``requires`` are not present (design §4.3)."""
    available = {spec.name for spec in specs}
    for spec in specs:
        missing = sorted(req for req in spec.requires if req not in available)
        if missing:
            raise BootError(
                f"module {spec.name!r} requires {missing} which are not installed"
            )


def _validate_unique_spec_names(specs: Sequence[ModuleSpec]) -> None:
    """Fail closed when two specs would mount at the same ``/api/v1/<name>`` prefix."""
    seen: dict[str, str] = {}
    for spec in specs:
        previous = seen.get(spec.name)
        if previous is not None:
            raise BootError(
                f"module/capability name {spec.name!r} is declared more than once "
                f"({previous} and {spec!r}); names must be unique so a router cannot "
                "shadow another router"
            )
        seen[spec.name] = repr(spec)


def _request_size_override_map(
    specs: Sequence[ModuleSpec], explicit: Mapping[str, int] | None
) -> dict[str, int]:
    """The mount-prefix→byte-cap map for the request-size middleware (ADR 0067).

    Each **mounted** spec's declared ``max_request_bytes`` contributes its own
    ``/api/v1/<name>`` prefix (a router-less spec is skipped — an unrouted prefix
    must never accept a bigger body). *explicit* is the composition root's
    per-deployment retuning, keyed by **module name** so a typo cannot silently
    create an unrouted allowance: an unknown name or a non-positive cap raises
    :class:`BootError` (fail closed), and an explicit entry wins over the spec's
    declared default — the same root-overrides-package precedence as every other
    composition seam.
    """
    overrides: dict[str, int] = {}
    routed = {spec.name for spec in specs if spec.router is not None}
    for spec in specs:
        if spec.max_request_bytes is not None and spec.router is not None:
            overrides[f"/api/v1/{spec.name}"] = spec.max_request_bytes
    for name, cap in (explicit or {}).items():
        if name not in routed:
            raise BootError(
                f"request_size_overrides names {name!r}, which is not a mounted "
                "module/capability; overrides are keyed by module name"
            )
        if cap <= 0:
            raise BootError(
                f"request_size_overrides[{name!r}] must be a positive byte count, got {cap!r}"
            )
        overrides[f"/api/v1/{name}"] = cap
    return overrides


def _validate_permission_enforcement(
    specs: Sequence[ModuleSpec], permission_enforcer: PermissionEnforcer | None
) -> None:
    """Fail closed if a Policy needs per-subject permission enforcement but none is installed.

    A ``Policy`` whose read/write requirement is a ``Permission`` can only be
    honored when a ``permission_enforcer`` is wired (the access capability's
    ``enforce_permission``); otherwise the guard would have nothing to consult and
    a permission would silently collapse to its role rank. Boot refuses that
    misconfiguration so the gap is caught at composition time, not in production.
    """
    if permission_enforcer is not None:
        return
    permission_modules = sorted(
        spec.name
        for spec in specs
        if spec.policy is not None
        and not spec.policy.is_public
        and "permission"
        in (spec.policy.read_requirement.kind, spec.policy.write_requirement.kind)
    )
    if permission_modules:
        raise BootError(
            f"modules {permission_modules} declare a Policy with a Permission "
            "requirement but no permission_enforcer is installed; pass "
            "permission_enforcer=... (e.g. terp.capabilities.access.enforce_permission) "
            "so the per-subject grant is actually enforced (a permission is never "
            "degraded to a role tier), or declare a role requirement instead "
            "(e.g. Policy(write=EDITOR))"
        )


def _validate_token_revocation(
    principal_provider: Callable[..., Principal | None], require_token_revocation: bool
) -> None:
    """Fail closed when revocation is required but the principal provider does not enforce it.

    The boot half of the session-revocation control (ADR 0031): an app that sets
    ``require_token_revocation=True`` is promising that a deactivated / demoted /
    password-reset user's token stops working mid-session. That holds only when the wired
    ``principal_provider`` re-validates the token against the store every request (the
    auth capability's ``build_get_principal(token_validator=…)`` provider, marked via
    :func:`mark_token_revocation_provider`). If the provider is the stateless default,
    boot refuses — the promise is caught unmet at composition time, never in production.
    """
    if require_token_revocation and not enforces_token_revocation(principal_provider):
        raise BootError(
            "require_token_revocation=True but the configured principal_provider does not "
            "enforce token revocation; wire a validating provider (e.g. "
            "IdentityService(...).principal_provider(), or "
            "build_get_principal(token_validator=...)) so a deactivated, demoted, or "
            "password-reset user's token is rejected mid-session instead of staying valid "
            "for the access-token lifetime — or drop require_token_revocation to accept the "
            "short access-TTL staleness window"
        )


def _router_has_mutating_route(router: APIRouter) -> bool:
    """True when *router* (including nested included routers) declares a write method."""
    for route in _iter_api_routes(router.routes):
        if _MUTATING_METHODS & {method.upper() for method in (route.methods or ())}:
            return True
    return False


def _validate_policy_write_tiers(specs: Sequence[ModuleSpec]) -> None:
    """Fail closed when a write surface's Policy gates writes below its read tier.

    The universal runtime half of ``mutations_require_write_role`` (ADR 0006): the
    build-time rule catches the statically resolvable default-ladder cases, but it cannot
    know a *custom* role's rank from a source scan. For every module that exposes a
    mutating route under a non-public Policy, the write requirement must rank **at or
    above** the read requirement — otherwise a caller who can read can also write
    (privilege inversion). Equality is allowed (a flat or admin-only model); only
    ``write_rank < read_rank`` is refused, and it is refused for *any* role model.
    """
    for spec in specs:
        policy = spec.policy
        if policy is None or policy.is_public or spec.router is None:
            continue
        if not _router_has_mutating_route(spec.router):
            continue
        if policy.write_requirement.min_rank < policy.read_requirement.min_rank:
            raise BootError(
                f"module {spec.name!r} exposes a mutating route but its Policy gates writes "
                f"(rank {policy.write_requirement.min_rank}) below reads "
                f"(rank {policy.read_requirement.min_rank}); a reader could then write "
                "(privilege inversion). Raise the write tier to at least the read tier "
                "(e.g. Policy.default(): read=VIEWER, write=EDITOR)"
            )


def _validate_public_modules_read_only(specs: Sequence[ModuleSpec]) -> None:
    """Fail closed when a public router exposes writes without the stronger opt-out."""
    for spec in specs:
        policy = spec.policy
        if policy is None or not policy.is_public or spec.router is None:
            continue
        if _router_has_mutating_route(spec.router) and not policy.allows_public_writes:
            raise BootError(
                f"module {spec.name!r} is public but exposes a mutating route; "
                "unauthenticated writes require Policy.public_write(reason=...) so the "
                "runtime opt-out is explicit and greppable"
            )


def _validate_shared_throttle_store(
    throttle_store: ThrottleStore | None, require_shared_throttle_store: bool
) -> None:
    """Fail closed when a shared throttle store is required but a per-instance one is wired.

    The boot half of the multi-instance throttle control (ADR 0036): a horizontally scaled
    app sets ``require_shared_throttle_store=True`` to promise that the rate limit and the
    per-account login lockout are enforced **globally**, not per worker. That holds only
    when a shared backend is wired and marked via
    :func:`~terp.core.throttling.mark_shared_throttle_store`; the default
    :class:`InMemoryThrottleStore` is per-instance, so boot refuses it here — mirroring the
    durable-audit-sink and token-revocation boot guards. Default ``False`` keeps the
    per-instance behaviour unchanged unless a deployment opts in.
    """
    if require_shared_throttle_store and not is_shared_throttle_store(throttle_store):
        raise BootError(
            "require_shared_throttle_store=True but the configured throttle_store is not a "
            "shared, multi-instance backend; wire one marked via "
            "terp.core.mark_shared_throttle_store(...) (e.g. a Redis-backed ThrottleStore) "
            "so the rate limit and login lockout are enforced globally across workers — or "
            "drop require_shared_throttle_store to accept the per-instance default"
        )


def _validate_shared_cache_store(
    cache_store: CacheStore | None, require_shared_cache_store: bool
) -> None:
    """Fail closed when a shared cache is required but a per-instance one is wired.

    The boot half of the caching-seam control: a horizontally scaled app sets
    ``require_shared_cache_store=True`` to promise that cached reads are coherent
    **across workers** (one shared backend, one invalidation), not N divergent
    per-process caches. That holds only when a shared backend is wired and marked via
    :func:`~terp.core.cache.mark_shared_cache_store`; the default
    :class:`~terp.core.cache.InMemoryCacheStore` is per-instance, so boot refuses it
    here — mirroring the shared-throttle-store and durable-jobs boot guards. Default
    ``False`` keeps the per-instance default unchanged unless a deployment opts in.
    """
    if require_shared_cache_store and not is_shared_cache_store(cache_store):
        raise BootError(
            "require_shared_cache_store=True but the configured cache_store is not a "
            "shared, multi-instance backend; wire one marked via "
            "terp.core.mark_shared_cache_store(...) (e.g. a Redis-backed CacheStore) "
            "so cached reads stay coherent across workers — or drop "
            "require_shared_cache_store to accept the per-instance default"
        )


def _validate_shared_idempotency_store(
    idempotency_store: IdempotencyStore | None, require_shared_idempotency_store: bool
) -> None:
    """Fail closed when a shared idempotency store is required but a per-instance one is wired.

    The boot half of the idempotency-key control: a horizontally scaled app sets
    ``require_shared_idempotency_store=True`` to promise that a client's retried unsafe
    request is deduplicated **globally** — not per worker, where a retry landing on
    another instance would re-execute the mutation. That holds only when a shared
    backend is wired and marked via
    :func:`~terp.core.idempotency.mark_shared_idempotency_store`; the default
    :class:`~terp.core.idempotency.InMemoryIdempotencyStore` is per-instance, so boot
    refuses it here — mirroring the shared-throttle-store and shared-cache-store boot
    guards. Default ``False`` keeps the per-instance default unchanged unless a
    deployment opts in.
    """
    if require_shared_idempotency_store and not is_shared_idempotency_store(idempotency_store):
        raise BootError(
            "require_shared_idempotency_store=True but the configured idempotency_store "
            "is not a shared, multi-instance backend; wire one marked via "
            "terp.core.mark_shared_idempotency_store(...) (e.g. a Redis-backed "
            "IdempotencyStore) so a retried request is deduplicated globally across "
            "workers — or drop require_shared_idempotency_store to accept the "
            "per-instance default"
        )


def _validate_durable_jobs(
    job_queue: JobQueue | None, require_durable_jobs: bool
) -> None:
    """Fail closed when a durable job queue is required but a per-instance one is wired.

    The boot half of the durable-jobs control (ADR 0043): an app that promises its
    background work survives a restart sets ``require_durable_jobs=True``. That holds only
    when a durable backend is wired and marked via
    :func:`~terp.core.mark_durable_job_queue` (a future outbox / broker adapter); the
    default :class:`~terp.core.InProcessJobQueue` runs inline and loses queued work on
    restart, so boot refuses it here — mirroring the durable-audit-sink and
    shared-throttle-store boot guards. Default ``False`` keeps the in-process default
    unchanged unless a deployment opts in.
    """
    if require_durable_jobs and not is_durable_job_queue(job_queue):
        raise BootError(
            "require_durable_jobs=True but the configured job_queue is not a durable, "
            "restart-surviving backend; wire one marked via "
            "terp.core.mark_durable_job_queue(...) (e.g. an outbox- or broker-backed "
            "JobQueue) so enqueued work is not lost on restart — or drop "
            "require_durable_jobs to accept the in-process default"
        )


def _referenced_response_types(annotation: object) -> set[type]:
    """Every concrete class referenced by a ``response_model`` (generics unwrapped).

    ``Page[User]`` -> ``{Page, User}``; ``list[User]`` -> ``{list, User}`` -- so a
    table model nested inside a ``Page[...]`` / ``list[...]`` envelope (a typing
    generic *or* a pydantic generic model) is still inspected, not only a bare
    top-level annotation.
    """
    found: set[type] = set()
    if isinstance(annotation, type):
        found.add(annotation)
    origin = get_origin(annotation)
    if origin is not None:
        found |= _referenced_response_types(origin)
    for arg in _annotation_args(annotation):
        found |= _referenced_response_types(arg)
    return found


def _annotation_args(annotation: object) -> tuple[object, ...]:
    """Type arguments of *annotation* -- from a typing generic or a pydantic model."""
    args = get_args(annotation)
    if args:
        return args
    meta = getattr(annotation, "__pydantic_generic_metadata__", None)
    return tuple(meta.get("args", ())) if meta else ()


def _is_orm_table_model(tp: type) -> bool:
    """True for a persisted SQLModel (``table=True`` gives it a mapped ``__table__``)."""
    return issubclass(tp, SQLModel) and getattr(tp, "__table__", None) is not None


def _iter_api_routes(routes: Sequence[object]) -> Iterator[APIRoute]:
    """Every ``APIRoute`` reachable from *routes*, descending into included sub-routers.

    ``APIRouter.include_router`` keeps the sub-router as a nested ``_IncludedRouter``
    (its routes live on ``.original_router``), not flattened into ``.routes`` -- so a
    plain ``for route in router.routes`` would miss a route declared on a nested
    router. Walking the tree keeps the response-model guard total.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested = getattr(route, "original_router", None) or route
        sub = getattr(nested, "routes", None)
        if sub:
            yield from _iter_api_routes(sub)


def _validate_router_response_models(router: APIRouter) -> None:
    """Fail closed if a route on *router* serializes a ``table=True`` ORM model.

    A ``response_model`` that is (or wraps) a persisted model leaks every column --
    a password hash, an internal flag -- straight through the boundary. The
    build-time ``terp.arch`` ``response_model_not_table_model`` rule catches this
    within a scanned tree; this runtime control is the universal guarantee, also
    covering a table model reached across packages where a static scan cannot
    follow the symbol (and routes declared on a nested, included router). Return a
    ``*Read`` DTO (:class:`terp.core.BaseSchema`).
    """
    for route in _iter_api_routes(router.routes):
        if route.response_model is None:
            continue
        for tp in _referenced_response_types(route.response_model):
            if _is_orm_table_model(tp):
                raise BootError(
                    f"route {route.path!r} exposes the table model {tp.__name__!r} as its "
                    "response_model; a persisted model serializes every column (e.g. a "
                    "password hash) -- return a *Read DTO (terp.core.BaseSchema) instead"
                )


def create_app(
    specs: Sequence[ModuleSpec],
    *,
    title: str = "Terp app",
    principal_provider: Callable[..., Principal | None] = get_principal,
    discover_capabilities: bool = False,
    capability_names: Sequence[str] | None = None,
    control_plane: ControlPlane | None = None,
    audit_sink: AuditSink | None = None,
    event_dispatcher: EventDispatcher | None = None,
    permission_enforcer: PermissionEnforcer | None = None,
    middleware: Sequence[Middleware] | None = None,
    migration_check: Callable[[Engine], None] | None = None,
    require_token_revocation: bool = False,
    throttle_store: ThrottleStore | None = None,
    require_shared_throttle_store: bool = False,
    job_queue: JobQueue | None = None,
    require_durable_jobs: bool = False,
    cache_store: CacheStore | None = None,
    require_shared_cache_store: bool = False,
    idempotency_store: IdempotencyStore | None = None,
    require_shared_idempotency_store: bool = False,
    request_size_overrides: Mapping[str, int] | None = None,
) -> FastAPI:
    """Compose a FastAPI app from module specs (deny-by-default, guarded).

    A spec with no ``Policy`` raises :class:`BootError` (fail closed). Each
    module router is mounted at ``/api/v1/<name>`` behind its policy guard.
    *principal_provider* is the seam an auth capability fills (e.g.
    ``terp.capabilities.auth.get_principal``); it defaults to the kernel's
    unauthenticated seam. When *discover_capabilities* is true, installed
    capabilities that declare a ``terp.capabilities`` entry point are also
    mounted (self-registration), with no composition-root edit. Pass
    *capability_names* to make discovery profile-shaped and load only those entry
    point names; this lets a deployment install optional capability packages
    without accidentally exposing every installed routed surface.

    Every spec's declared ``requires`` are checked against the installed set and
    a missing dependency raises :class:`BootError` before any router is mounted.

    A non-default *principal_provider* is also registered as a dependency
    override for ``get_principal``, so route-level dependencies that read the
    caller through the public seam (e.g. ``access.require_permission``) receive
    the configured principal — not only the policy guard does.

    *audit_sink* installs the durable audit sink (e.g.
    ``terp.capabilities.audit.persist_audit``). When omitted, audit records are
    emitted to the structured log only; either way every mutation through
    ``BaseService`` is audited per the control plane's ``AuditPolicy``. In
    production this log-only fallback is refused: boot fails unless a durable
    *audit_sink* is installed or audit is explicitly turned off
    (``AuditPolicy.disabled(reason=...)``), so a real deployment never silently
    loses its trail.

    *event_dispatcher* installs the event-bus dispatcher (e.g.
    ``terp.capabilities.eventbus.dispatch_in_process``). When omitted, the event
    catalog is still validated and ``emit`` still rejects unknown events, but an
    emitted event is delivered nowhere — the optional event bus is inactive.

    *permission_enforcer* installs the per-subject permission check the guard
    consults for a ``Policy`` that requires a ``Permission`` (e.g.
    ``terp.capabilities.access.enforce_permission``). When a module declares a
    permission requirement and no enforcer is installed, boot fails closed
    (:class:`BootError`) — a permission is never silently degraded to a role tier.

    *middleware* installs additional ASGI middleware through the one sanctioned
    composition seam (e.g. ``Middleware(TenantMiddleware, resolve_tenant=...)`` from
    the tenancy capability). It is mounted just inside the central security stack,
    so a request still passes request-id, security headers, CORS, rate-limit, and
    the body-size limit first; this is how a capability's middleware is wired
    without a module ever calling ``add_middleware`` (the ``no_adhoc_middleware``
    rule keeps the composition root the only path).

    *migration_check* is the fail-closed migration boot guard seam: a callable given
    the process engine that raises if the database schema is behind the code (e.g.
    ``terp.migrations.assert_migrations_current``). When supplied it runs at boot so
    the app refuses to serve against an un-migrated schema — the runtime half of the
    migration two-layer control. It is opt-in (the kernel never imports the migration
    subsystem); a consumer typically wires it only outside local development.

    *require_token_revocation* makes the session-revocation guarantee a boot
    requirement (ADR 0031): when ``True``, boot fails closed unless *principal_provider*
    is a revocation-enforcing provider (one that re-validates the token against the
    store every request, e.g. ``IdentityService(...).principal_provider()`` /
    ``build_get_principal(token_validator=...)``). It defaults ``False`` only for
    backward compatibility — the bundled stack sets it ``True`` so a deactivated,
    demoted, or password-reset user's token stops working mid-session rather than
    lingering for the access-token lifetime.

    *throttle_store* is the pluggable backend for the request rate limiter (ADR 0036):
    a single-process app uses the default :class:`InMemoryThrottleStore`, so the limit
    is per-instance (unchanged); a multi-instance deployment passes one shared store so
    every worker enforces the same global cap. A store error fails closed (the caller is
    rate-limited). The per-account login throttle takes the same store at its own seam.

    *require_shared_throttle_store* makes that shared-store promise a boot requirement:
    when ``True``, boot fails closed unless *throttle_store* is a backend marked shared via
    ``mark_shared_throttle_store`` — so a multi-instance app cannot silently ship the
    per-instance default and dilute the rate limit / login lockout by the worker count. It
    defaults ``False`` (the per-instance default is unchanged), mirroring
    *require_token_revocation*.

    *job_queue* is the backend background jobs are enqueued to (ADR 0043): the default
    :class:`~terp.core.InProcessJobQueue` runs each handler inline in its own audited unit
    (zero infra; dev / test / single-process behave as before), while a durable / broker
    adapter runs it off-request. Either way ``terp.core.enqueue`` validates against the
    control plane's :class:`~terp.core.JobCatalog`, and every declared ``ModuleSpec.jobs``
    is boot-validated against it (an undeclared job fails the boot, like a policy / event
    reference). The control plane's ``job_system_actor_id`` is the stand-in actor a job
    runs as when no user originated it, so a job's writes are never silently unstamped.

    *require_durable_jobs* makes durability a boot requirement: when ``True``, boot fails
    closed unless *job_queue* is a backend marked durable via ``mark_durable_job_queue`` —
    so production cannot silently ship the in-process default that loses queued work on
    restart. It defaults ``False`` (the in-process default is unchanged), mirroring
    *require_shared_throttle_store*.

    *cache_store* is the pluggable hot-read cache backend: a single-process app keeps
    the default per-process :class:`~terp.core.cache.InMemoryCacheStore` (zero infra; a
    cache is never a correctness dependency — a miss only costs a read), while a
    multi-instance deployment passes one shared backend (e.g. Redis) so cached reads and
    invalidations stay coherent across workers. Modules reach the configured store only
    through :func:`terp.core.get_cache`, never a concrete engine.

    *require_shared_cache_store* makes that shared-cache promise a boot requirement:
    when ``True``, boot fails closed unless *cache_store* is a backend marked shared via
    ``mark_shared_cache_store`` — so a multi-instance app cannot silently ship N
    divergent per-process caches. It defaults ``False`` (the per-instance default is
    unchanged), mirroring *require_shared_throttle_store*.

    *idempotency_store* is the pluggable backend for the ``Idempotency-Key`` retry
    dedup: an unsafe request carrying the header executes once and its response is
    stored and replayed to a retry of the same key (a request without the header is
    untouched). A single-process app keeps the default per-process
    :class:`~terp.core.idempotency.InMemoryIdempotencyStore`; a multi-instance
    deployment passes one shared backend so a retry landing on another worker still
    replays instead of re-executing. A store error on the claim fails closed (typed
    503) — the mutation is never silently double-executable.

    *require_shared_idempotency_store* makes that shared-dedup promise a boot
    requirement: when ``True``, boot fails closed unless *idempotency_store* is a
    backend marked shared via ``mark_shared_idempotency_store`` — so a multi-instance
    app cannot silently dedupe per worker. It defaults ``False`` (the per-instance
    default is unchanged), mirroring *require_shared_throttle_store*.

    *request_size_overrides* retunes a mounted module's request-body ceiling per
    deployment (ADR 0067), keyed by **module name** (``{"files": 100 * 1024 * 1024}``).
    Each mounted spec's declared ``ModuleSpec.max_request_bytes`` already applies to its
    own ``/api/v1/<name>`` prefix; an explicit entry here wins over that declared
    default. An unknown name or a non-positive cap fails the boot (fail closed); every
    prefix without an override keeps the global ``SecurityConfig.max_request_bytes``.
    """
    if capability_names is not None and not discover_capabilities:
        raise BootError("capability_names requires discover_capabilities=True")
    collected = list(specs)
    if discover_capabilities:
        try:
            collected.extend(iter_capability_specs(capability_names))
        except Exception as exc:
            raise BootError(f"capability discovery failed: {exc}") from exc

    _validate_unique_spec_names(collected)
    _validate_requires(collected)
    resolved_plane = control_plane or ControlPlane.default()
    plane_errors = resolved_plane.validation_errors(collected)
    if plane_errors:
        raise BootError("; ".join(plane_errors))
    _validate_permission_enforcement(collected, permission_enforcer)
    _validate_token_revocation(principal_provider, require_token_revocation)
    _validate_policy_write_tiers(collected)
    _validate_public_modules_read_only(collected)
    _validate_shared_throttle_store(throttle_store, require_shared_throttle_store)
    _validate_durable_jobs(job_queue, require_durable_jobs)
    _validate_shared_cache_store(cache_store, require_shared_cache_store)
    _validate_shared_idempotency_store(idempotency_store, require_shared_idempotency_store)

    settings = get_settings()
    if settings.is_production:
        security_problems = resolved_plane.security.production_problems()
        if security_problems:
            raise BootError(
                "insecure production security config: " + "; ".join(security_problems)
            )
        password_problems = resolved_plane.passwords.production_problems()
        if password_problems:
            raise BootError(
                "insecure production password policy: " + "; ".join(password_problems)
            )
        if resolved_plane.audit.enabled and not is_durable_audit_sink(audit_sink):
            raise BootError(
                "audit is enabled but no marked durable audit sink is installed; "
                "production must persist its audit trail — pass audit_sink=... from "
                "the durable audit capability (e.g. terp.capabilities.audit.persist_audit) "
                "or turn audit off explicitly with AuditPolicy.disabled(reason=...)"
            )

    if migration_check is not None:
        migration_check(get_engine())

    configure_logging()
    configure_audit(resolved_plane.audit, sink=audit_sink)
    configure_events(resolved_plane.events, dispatcher=event_dispatcher)
    configure_jobs(
        resolved_plane.jobs,
        queue=job_queue,
        system_actor_id=resolved_plane.job_system_actor_id,
    )
    configure_schedules(resolved_plane.schedules)
    configure_password_policy(resolved_plane.passwords)
    configure_cache(cache_store)
    app = FastAPI(
        title=title,
        middleware=list(middleware) if middleware else None,
    )
    register_error_handlers(app)
    install_security_middleware(
        app,
        resolved_plane.security,
        is_local=settings.ENVIRONMENT == "local",
        throttle_store=throttle_store if throttle_store is not None else InMemoryThrottleStore(),
        idempotency_store=(
            idempotency_store if idempotency_store is not None else InMemoryIdempotencyStore()
        ),
        request_size_overrides=_request_size_override_map(collected, request_size_overrides),
    )
    if principal_provider is not get_principal:
        app.dependency_overrides[get_principal] = principal_provider

    audit_actor_binder = Depends(build_audit_actor_binder(principal_provider))
    read_only_binder = Depends(build_read_only_request_binder())
    for spec in collected:
        if spec.policy is None:
            raise BootError(f"module {spec.name!r} declares no Policy (deny-by-default)")
        if spec.router is not None:
            _validate_router_response_models(spec.router)
            app.include_router(
                spec.router,
                prefix=f"/api/v1/{spec.name}",
                dependencies=[
                    Depends(
                        build_guard(
                            spec.policy,
                            principal_provider,
                            permission_enforcer,
                            resolved_plane.permissions,
                        )
                    ),
                    audit_actor_binder,
                    read_only_binder,
                ],
            )
    app.include_router(build_health_router(), prefix="/health")
    _freeze_app_route_registration(app)
    return app


__all__ = [
    "BootError",
    "ControlPlane",
    "PermissionEnforcer",
    "Principal",
    "build_audit_actor_binder",
    "build_guard",
    "build_read_only_request_binder",
    "create_app",
    "enforces_token_revocation",
    "get_principal",
    "mark_token_revocation_provider",
    "register_error_handlers",
]
