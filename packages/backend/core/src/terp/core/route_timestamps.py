"""Every timestamp a route reads is held to its UTC offset, checked when the app starts (ADR 0208).

A ``BaseSchema`` puts the refusal of timestamp text without an offset in front of every
timestamp it reads itself (ADR 0206). Two kinds of request value are read by nothing of the
kind. A route parameter is no field of a schema: FastAPI parses ``since: datetime`` itself, so
``2026-11-06T10:00:00`` arrives naive and is read in whatever zone the code assumes. And a class
that brings its own Pydantic validator, a plain model, a Pydantic dataclass or a table, reads
its own fields whatever schema surrounds it, as a request body or nested in one.

So ``create_app`` walks, once every router is mounted, the schema each parameter of each route
is read with: a path, query, header or cookie parameter, a body or form field, and those of
every dependency the route resolves. Every timestamp it reaches must stand behind the refusal
(``Instant``, or a ``BaseSchema``'s own field), behind ``LocalTimeIn``, whose zone names the
instant, or behind ``NaiveMeansUtc``, the escape the build-time rule counts; an aware-only
``datetime`` refuses a value without an offset itself. The walk knows those nodes by their own
functions, as the schema's walk does. Anything else is refused, every finding in one error that
names the route, the parameter and the class and field that hold the timestamp.

A response model is not read from a request, so it is left alone. A validator that replaces a
timestamp's type entirely (``PlainValidator``) leaves no timestamp for the walk to see; it is an
app's own early validator, which the build-time rule counts (ADR 0207).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Annotated, Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, APIWebSocketRoute, RouteContext, iter_route_contexts
from pydantic import TypeAdapter
from pydantic_core import CoreSchema
from starlette.routing import BaseRoute

from terp.core.timestamps import _is_escape, _is_judged, _is_local_time, _schemas_in

#: Keys of a schema node that no request is read through: a model's computed fields are only
#: written, and a validator's JSON schema input only shapes the published contract.
_NOT_READ = frozenset({"computed_fields", "json_schema_input_schema"})

#: Where a parameter is read from, as a reader of the refusal names it.
_PLACES = (
    ("path parameter", "path_params"),
    ("query parameter", "query_params"),
    ("header", "header_params"),
    ("cookie", "cookie_params"),
    ("body field", "body_params"),
)

_REMEDY = (
    "Type such a timestamp Instant, from terp.core, which refuses one without its UTC offset "
    "with a 422. Where its sender sends the wall time of a place, type it "
    "Annotated[datetime, LocalTimeIn('<zone>')], and where the sender is known to send UTC "
    "without saying so, NaiveMeansUtc, which the request_timestamps_carry_their_offset rule "
    "counts. A class that holds one can instead become a BaseSchema, or give way to a "
    "BaseSchema of the app's own where the class is not the app's to change; a BaseSchema "
    "holds every timestamp it reads to its offset"
)


def _route_name(route: RouteContext) -> str:
    if isinstance(route.original_route, APIWebSocketRoute):
        return f"WebSocket {route.path}"
    return f"{','.join(sorted(route.methods or ()))} {route.path}"


def _parameters(dependant: Dependant) -> Iterator[tuple[str, Any]]:
    """Each parameter FastAPI reads for *dependant* and every dependency it resolves.

    A dependency's parameters are its own: FastAPI builds a dependant for each place a
    dependency is declared, so the tree has no cycle, and one declared twice is read twice.
    """
    pending = [dependant]
    while pending:
        current = pending.pop()
        for place, attribute in _PLACES:
            for field in getattr(current, attribute):
                yield place, field
        pending.extend(current.dependencies)


def _schema_of(field: Any) -> CoreSchema:
    """The schema *field* is read with: its type and every piece of metadata on it."""
    info = field.field_info
    annotation = Annotated[(info.annotation, *info.metadata)] if info.metadata else info.annotation
    return TypeAdapter(annotation).core_schema


def _definitions_in(schema: CoreSchema) -> dict[str, Any]:
    """Every node of *schema* that a reference can name, by the name it is referred to by."""
    definitions: dict[str, Any] = {}
    pending: list[Any] = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, list | tuple):
            pending.extend(node)
        elif isinstance(node, dict):
            if isinstance(node.get("ref"), str):
                definitions.setdefault(node["ref"], node)
            pending.extend(value for _, value in _schemas_in(node))
    return definitions


def _unjudged(schema: CoreSchema) -> list[str]:
    """Where *schema* reads a timestamp nothing judges: ``Class.field``, or ``""`` for itself.

    Each definition is read once, so a class that refers to itself is read once. A node the
    refusal, ``LocalTimeIn`` or the escape built is left with the timestamp behind it, and so
    is an aware-only ``datetime``.
    """
    found: list[str] = []
    definitions = _definitions_in(schema)
    followed: set[str] = set()
    pending: list[tuple[Any, str]] = [(schema, "")]
    while pending:
        node, place = pending.pop()
        if isinstance(node, list | tuple):
            pending.extend((item, place) for item in node)
            continue
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        if not isinstance(kind, str):  # a mapping of names to schemas: a class's fields
            owner = place.partition(".")[0]
            pending.extend((value, f"{owner}.{name}" if owner else name) for name, value in node.items())
            continue
        if _is_judged(node) or _is_escape(node) or _is_local_time(node):
            continue
        if kind == "datetime":
            if node.get("tz_constraint") != "aware" and place not in found:
                found.append(place)
            continue
        if kind == "definition-ref":
            ref = node["schema_ref"]
            if ref not in followed:
                followed.add(ref)
                pending.append((definitions[ref], place))
            continue
        if kind == "definitions":  # read where they are referred to, not where they are listed
            pending.append((node["schema"], place))
            continue
        if kind in ("model", "dataclass", "typed-dict"):  # each names the class it reads, if any
            place = getattr(node.get("cls"), "__name__", place)
        if kind == "dataclass-field":
            place = f"{place.partition('.')[0]}.{node['name']}"
        pending.extend((value, place) for key, value in _schemas_in(node) if key not in _NOT_READ)
    return found


def _findings(routes: Sequence[BaseRoute]) -> Iterator[str]:
    """One line for each timestamp a route reads that nothing holds to its offset.

    Each route as it is served: its path with every prefix it is mounted under, and every
    dependency the routers that include it add, as FastAPI's own contract reads it.
    """
    for route in iter_route_contexts(routes):
        if not isinstance(route.original_route, APIRoute | APIWebSocketRoute):
            continue  # a plain Starlette route or mount: FastAPI reads no parameter for it
        for place, field in _parameters(route.dependant):
            for where in _unjudged(_schema_of(field)):
                held = f", in {where}" if where else ""
                yield f"{_route_name(route)} reads a timestamp in the {place} {field.alias!r}{held}"


def request_timestamps_refusal(routes: Sequence[BaseRoute]) -> str | None:
    """Why *routes* may not be served, or ``None``: each timestamp a route reads unjudged.

    ``create_app`` raises it as a ``BootError`` once every router is mounted, the runtime half
    of the ``request_timestamps_carry_their_offset`` rule for what a ``BaseSchema`` does not
    read itself (ADR 0208).
    """
    findings = list(dict.fromkeys(_findings(routes)))
    if not findings:
        return None
    return (
        "A request timestamp is read with nothing to hold its text to its UTC offset, so a "
        "time sent without one would be read in a zone the sender never named (ADR 0206): "
        f"{'; '.join(findings)}. {_REMEDY} (ADR 0208)"
    )


__all__ = ["request_timestamps_refusal"]
