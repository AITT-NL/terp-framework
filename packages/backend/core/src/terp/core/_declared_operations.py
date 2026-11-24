"""Where a route's declared operation lands in the contract, and the one refusal it makes.

Moved out of ``terp.core.app`` (ADR 0102 §4, ADR 0222): ``create_app`` asks
:func:`_validate_hand_written_summaries` with its other declaration checks, and calls
:func:`_apply_declared_operations` only once every check passed, so a refused composition
leaves the route objects it was handed as it found them.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from fastapi.routing import APIRoute

from terp.core._boot_refusals import BootError
from terp.core.module_spec import ModuleSpec
from terp.core.operations import OperationDefinition
from terp.core.routing import declared_operation, iter_declaring_routes


def _iter_api_routes(routes: Sequence[object]) -> Iterator[APIRoute]:
    """Every HTTP ``APIRoute`` reachable from *routes*, descending into included sub-routers.

    ``APIRouter.include_router`` keeps the sub-router as a nested ``_IncludedRouter``
    (its routes live on ``.original_router``), not flattened into ``.routes`` -- so a
    plain ``for route in router.routes`` would miss a route declared on a nested
    router. It is :func:`~terp.core.routing.iter_declaring_routes` narrowed to HTTP, so the
    two cannot come to disagree about what counts as nested.
    """
    for route in iter_declaring_routes(routes):
        if isinstance(route, APIRoute):
            yield route


def _apply_declared_operations(specs: Sequence[ModuleSpec]) -> None:
    """Populate a declaring route's OpenAPI ``summary`` / ``operation_id`` (ADR 0102 §4),
    and refuse a hand-written ``summary=`` beside a declared operation.

    Must run after :func:`validate_declared_operations`, so every operation reaching
    here is already confirmed to be the catalog's own entry -- this function only
    applies it, it does not re-check membership. Only ``APIRoute`` carries
    ``summary`` / ``operation_id`` in OpenAPI; a declared operation on a WebSocket
    route is validated the same way but has nothing here to populate.

    A hand-written ``summary=`` on a route that also declares an operation is two
    answers to the same promise -- the same failure
    ``declared_read_only_routes_do_not_write`` names for ``@read_only`` and a write in
    the same handler. Refused at boot rather than left to whichever one FastAPI's
    OpenAPI generator happens to prefer.

    Both fields are read **live** by FastAPI's OpenAPI generator
    (``fastapi.openapi.utils.generate_operation_summary`` /
    ``get_openapi_operation_metadata`` read ``route.summary`` / ``route.operation_id``
    at schema-generation time, not a value cached at route construction), and
    ``include_router`` keeps a mounted router's original ``APIRoute`` objects rather
    than cloning them -- so mutating them here, before ``create_app`` ever mounts the
    spec's router, reaches the exported document unchanged.

    Idempotent by necessity, not merely by convenience: a module's router is a
    process-wide singleton built once at import time (``router = APIRouter()`` at
    module scope), and ``create_app`` is routinely called more than once over the
    same router objects in one process -- the example app alone does this for its
    full profile and its base profile, and so does any test suite that boots the
    same capability's app more than once. The second call sees the summary THIS
    function itself set on the first one; comparing to ``declared.label`` (always
    the same value, since ``declared_operation`` reads a stamp fixed at decoration
    time) tells that apart from an author's hand-written ``summary=``, which is
    fixed at route construction and can never equal the label by this route's own
    doing on a first call.
    """
    _validate_hand_written_summaries(specs)
    for spec in specs:
        for route, declared in _declaring_api_routes(spec):
            route.summary = declared.label
            route.operation_id = declared.id


def _declaring_api_routes(spec: ModuleSpec) -> Iterator[tuple[APIRoute, OperationDefinition]]:
    """Each API route of *spec* that declares an operation, with the operation."""
    for route in _iter_api_routes(spec.router.routes) if spec.router is not None else ():
        declared = declared_operation(route.endpoint)
        if declared is not None:
            yield route, declared


def _validate_hand_written_summaries(specs: Sequence[ModuleSpec]) -> None:
    """Refuse a hand-written ``summary=`` beside a declared operation (see :func:`_apply_declared_operations`).

    A check of its own, so ``create_app`` asks it with the other declaration checks and
    stamps the routes only once every check passed: a refused composition leaves the
    module's process-wide route objects as it found them (ADR 0222).
    """
    for spec in specs:
        for route, declared in _declaring_api_routes(spec):
            if route.summary and route.summary != declared.label:
                raise BootError(
                    f"module {spec.name!r} route {route.path!r} declares operation "
                    f"{declared.id!r} and also sets summary={route.summary!r} by hand; "
                    "that is two answers to the same promise -- drop the hand-written "
                    "summary= and let the declared operation's label supply it, or "
                    "drop the operation() declaration if this route genuinely needs a "
                    "different summary"
                )
