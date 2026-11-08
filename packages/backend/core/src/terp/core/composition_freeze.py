"""The composition freeze: once ``create_app`` has composed an app, nothing registers on it (ADR 0208).

``create_app`` is the one code path that mounts routers, because it puts the module policy
guard in front of every route at mount time and runs its startup checks over every route it
read. Whatever is registered on the composed app afterwards would be served or run outside
both. So the freeze refuses every registration surface the app and the routers it mounted
keep, fail closed: a route, a lifecycle hook, middleware, an exception handler, and outside
``local`` a dependency override.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import TYPE_CHECKING

from terp.core.config import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = [
    "freeze_app_middleware_registration",
    "freeze_app_route_registration",
    "freeze_dependency_overrides",
    "freeze_exception_handlers",
]


def _boot_error(message: str) -> Exception:
    """The composition root's :class:`~terp.core.app.BootError`, which imports this module."""
    from terp.core.app import BootError

    return BootError(message)


_APP_ROUTE_MUTATORS = frozenset(
    {
        "mount",
        "host",
        "frontend",
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
        # Lifecycle hooks are executable registration on the composed app — the
        # same guard-bypass surface as a raw route (nothing gates what they run).
        "on_event",
        "add_event_handler",
    }
)


def _refuse_route_mutation(name: str) -> Callable[..., None]:
    def refused(*_args: object, **_kwargs: object) -> None:
        raise _boot_error(
            f"registration via {name}(...) after create_app() composition is refused; "
            "declare routes on a module APIRouter (ModuleSpec.router) and lifecycle "
            "work through the sanctioned seams"
        )

    return refused


def _refuse_late_route(method: str) -> Callable[..., None]:
    def refused(*_args: object, **_kwargs: object) -> None:
        raise _boot_error(
            f"registration via router.{method}(...) on a router create_app() mounted is refused "
            "once the app is composed: FastAPI would serve the route without the checks "
            "create_app() ran on every route it read; declare every route on the router "
            "before create_app() runs"
        )

    return refused


# Middleware registration spellings on the composed app. Post-composition middleware
# wraps the central security stack from outside every declared control, so both the
# imperative call and the decorator fail closed once the app is composed.
_APP_MIDDLEWARE_MUTATORS = ("add_middleware", "middleware")


def _refuse_middleware_registration(name: str) -> Callable[..., None]:
    def refused(*_args: object, **_kwargs: object) -> None:
        raise _boot_error(
            f"middleware registration via {name}(...) after create_app() composition is "
            "refused; pass middleware=[Middleware(...)] to create_app() — the one "
            "sanctioned composition seam (the no_adhoc_middleware rule)"
        )

    return refused


def freeze_app_middleware_registration(app: FastAPI) -> None:
    """Runtime half of ``no_adhoc_middleware``: no post-composition middleware.

    Cross-cutting HTTP security is declared once (``SecurityConfig`` + the
    ``create_app`` *middleware* parameter) and installed at composition, inside the
    central security stack. Middleware registered on the composed app afterwards —
    ``add_middleware(...)`` or the ``@app.middleware("http")`` decorator — would wrap
    that stack from outside every declared control, so both spellings fail closed.
    """
    for method in _APP_MIDDLEWARE_MUTATORS:
        setattr(app, method, _refuse_middleware_registration(f"app.{method}"))


class _FrozenDependencyOverrides(dict):
    """The composed app's ``dependency_overrides``: readable forever, never writable.

    Runtime half of ``no_dependency_overrides``: composition binds the principal /
    session seams once (``create_app(principal_provider=...)`` registers the app's
    own override *before* the freeze), and any later write would silently disable
    authentication or swap the database session outside every guard — so every
    mutating spelling fails closed while reads (FastAPI's per-request override
    lookup) keep working.
    """

    def _refused(self, *_args: object, **_kwargs: object) -> None:
        raise _boot_error(
            "rebinding dependency_overrides after create_app() composition is refused; "
            "bind the seam at composition instead (e.g. "
            "create_app(principal_provider=...)) — overrides are a test-only seam, "
            "writable only in the local environment (the no_dependency_overrides rule)"
        )

    __setitem__ = _refused
    __delitem__ = _refused
    __ior__ = _refused
    clear = _refused
    pop = _refused
    popitem = _refused
    setdefault = _refused
    update = _refused


def freeze_dependency_overrides(app: FastAPI) -> None:
    """Swap the composed app's override map for the refusing, read-only mapping."""
    app.dependency_overrides = _FrozenDependencyOverrides(app.dependency_overrides)


class _Frozen(list):  # type: ignore[type-arg]
    """A list the composed app reads and nothing may change: its routes, hooks or middleware.

    Every registration method, of any name or called on its class, changes a list through the
    list's own methods, so the list refuses it. ``list``'s methods called on it directly, or
    another list in its place, reach past that, as ``object.__setattr__`` reaches past
    ``LocalTimeIn``'s (ADR 0208). A copy is a plain list again.
    """

    def __init__(self, items: list[object], refusal: str) -> None:
        super().__init__(items)
        self._refusal = refusal

    def _refused(self, *_args: object, **_kwargs: object) -> None:
        raise _boot_error(
            f"{self._refusal} added after create_app() composed the app is refused: "
            f"{_FROZEN_REMEDY}"
        )

    def __reduce_ex__(self, _protocol: object) -> tuple[type[list], tuple[list[object]]]:  # type: ignore[override]
        return list, (list(self),)

    append = extend = insert = remove = pop = clear = sort = reverse = _refused
    __setitem__ = __delitem__ = __iadd__ = __imul__ = _refused


_FROZEN_REMEDY = (
    "it would run outside the policy guard and the checks create_app() made of what it read. "
    "Declare routes on a module APIRouter, lifecycle work through the sanctioned seams and "
    "middleware with create_app(middleware=[...]), before create_app() runs"
)


class _FrozenHandlers(dict):  # type: ignore[type-arg]
    """The composed app's ``exception_handlers``: read when it builds its stack, never written.

    Every registration (``add_exception_handler``, the ``exception_handler`` decorator, either
    called on its class with the app passed in) writes this map, so the map refuses it.
    """

    def _refused(self, *_args: object, **_kwargs: object) -> None:
        raise _boot_error(
            "an exception handler added after create_app() composed the app is refused: it "
            "would answer in place of the uniform error envelope, which keeps an AppError's "
            "status and code and never repeats an unexpected exception's text. Raise a typed "
            "AppError subclass instead; the envelope renders it with its own status and code"
        )

    __setitem__ = __delitem__ = __ior__ = clear = pop = popitem = setdefault = update = _refused


def freeze_exception_handlers(app: FastAPI) -> None:
    """Swap the composed app's handler map for the refusing one, which its stack still reads."""
    app.exception_handlers = _FrozenHandlers(app.exception_handlers)


def _freeze_lists(app: FastAPI, routers: Sequence[object]) -> None:
    """Freeze every list the composed *app* and its mounted *routers* read requests through."""
    for router in routers:
        router.routes = _Frozen(router.routes, "a route")  # type: ignore[attr-defined]
        groups = getattr(router, "_low_priority_routes", [])  # FastAPI's frontend routes
        for group in groups:
            group.routes = _Frozen(group.routes, "a frontend route")
        router._low_priority_routes = _Frozen(groups, "a frontend route")  # type: ignore[attr-defined]
    app.router.on_startup = _Frozen(app.router.on_startup, "a startup handler")
    app.router.on_shutdown = _Frozen(app.router.on_shutdown, "a shutdown handler")
    app.user_middleware = _Frozen(app.user_middleware, "middleware")


def _mounted_routers(routes: Sequence[object]) -> Iterator[object]:
    """Every router *routes* include, at any depth: a module's, and one it includes itself."""
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield nested
            yield from _mounted_routers(nested.routes)


def freeze_app_route_registration(app: FastAPI) -> None:
    """The composition freeze: no post-composition registration surface, fail closed.

    Runtime half of ``no_raw_app_routes`` (and, through the two extensions below, of
    ``no_adhoc_middleware`` and ``no_dependency_overrides``). ``create_app`` is the
    only code path allowed to mount routers because it injects the module policy
    guard at mount time. Once the app is composed, route mutation on the app or its
    underlying router is a guard bypass, so every registration method fails closed.
    So is one on a router the app mounted: FastAPI serves an included router live, so a
    route added to it afterwards would be served without one of the checks ``create_app``
    ran on every route it read (ADR 0208). Middleware registration is refused on the same
    footing, and so is an exception handler, which would answer for every route in place of
    the error envelope. The lists the app reads requests through (every router's routes,
    FastAPI's frontend routes, the lifecycle hooks, the middleware) and the handler map refuse
    a change through their own methods, so a registration method nobody listed fails closed
    too. The override map is frozen only outside ``local``: overrides are the sanctioned *test*
    seam (a local suite overrides ``get_session`` against a scratch engine), while a deployed
    app must never rebind its auth / session seams post-composition.
    """
    for target_name, target in (("app", app), ("app.router", app.router)):
        for method in _APP_ROUTE_MUTATORS:
            if hasattr(target, method):
                setattr(target, method, _refuse_route_mutation(f"{target_name}.{method}"))
    mounted = list(_mounted_routers(app.router.routes))
    for router in mounted:
        for method in _APP_ROUTE_MUTATORS:
            if hasattr(router, method):
                setattr(router, method, _refuse_late_route(method))
    _freeze_lists(app, (app.router, *mounted))
    freeze_app_middleware_registration(app)
    freeze_exception_handlers(app)
    if get_settings().ENVIRONMENT != "local":
        freeze_dependency_overrides(app)
