"""Route-level declarations a module makes about one handler, and the method vocabulary.

Three declarations live here: :func:`read_only` (this handler persists nothing),
:func:`operation` (this is what the route does, ADR 0102), and the introspection
marker :func:`mark_required_permission` the access capability stamps. Each is a
stamped attribute read through a predicate, so a rule or a view can see the
declaration without the writer and the reader sharing anything but this module.

Terp derives a request's write authority from the **HTTP method**: a mutating
method is authorized at the write tier and may persist, and every other method is
authorized at the read tier and marked read-only at runtime. That mapping is right
for almost every route, and it is what ``safe_methods_are_read_only`` and the
session guard enforce between them.

:data:`MUTATING_METHODS` is the single definition of that split, and every part of
the platform that classifies a request reads it from here — the composition root's
guard and read-only binder, the idempotency middleware, and the access-graph
projection in ``terp.cli``. It used to be spelled out separately in each of those,
two of them carrying a comment conceding they mirrored the others, and the copies
had drifted: the guard treated *any* non-mutating method as a read while the binder
marked only ``GET`` / ``HEAD`` / ``OPTIONS`` read-only, so a route served under a
method in neither set (``TRACE``, or a verb registered through
``add_api_route``) was authorized at the read tier and still allowed to write.
One vocabulary, read through one :func:`request_method`, and phrased once as a
single negation: that is what makes the two halves agree by construction rather
than by coincidence. Sharing only the vocabulary was not enough — they still
disagreed about the method's *case* until the read was shared too.

That mapping has one blind spot, and :func:`read_only` is for exactly that: a handler that
uses an unsafe verb **because of where its input lives**, not because it writes.
Validating a candidate document, previewing an import, judging a draft, costing a
plan — each takes a body too large or too structured for a query string, so it is
a ``POST``, and each computes an answer and persists nothing.

Today such a route is pure only by the *absence* of a write, which is a guarantee
made of missing code: it holds until someone adds a line, and no rule and no
review step notices when they do. That is the same argument
``BaseService.append_only`` answers for a table, and this is the same answer for a
route — state the intent, and let both halves of the platform enforce it:

* **Build time** — the ``declared_read_only_routes_do_not_write`` rule refuses a
  decorated handler that calls a mutating ``BaseService`` method.
* **Run time** — ``create_app``'s read-only binder marks the request read-only, so
  a write through the chokepoint fails closed with ``ReadOnlyRequestError``
  exactly as it would in a ``GET``.

What it does **not** change is authorization. A decorated ``POST`` is still
authorized at the write tier, because the caller is still asking the platform to
do something with a document they supplied; declaring purity narrows what the
handler may do, never what the caller must hold. A route that should be readable
by a read-tier caller is a ``GET``, and this decorator is not a way to spell one::

    @router.post("/{sync_id}/validation", response_model=ValidationRead)
    @read_only
    def validate_candidate(...) -> ValidationRead:
        # judges an unsaved document; writes nothing
        return service.validate(session, sync_id, candidate)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from terp.core.operations import OperationDefinition

#: The HTTP methods that carry write authority — the one definition of the split.
#:
#: A request whose method is in this set is authorized against the policy's *write*
#: requirement and may persist; **every other method** is authorized at the read tier
#: and is marked read-only, whether or not it is one of RFC 9110's safe methods. The
#: classification is deliberately a single negation rather than two sets, so no method
#: can fall between them.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def request_method(connection: object) -> str:
    """The upper-cased HTTP method *connection* is being served under.

    The single reader of a request's method for an authority decision, so the
    guard and the read-only binder cannot disagree about what the method *is*.
    They previously each inlined this expression and only one of them upper-cased
    the result, which reopened the very gap :data:`MUTATING_METHODS` exists to
    close: a lower-case ``post`` matched no entry in the mutating set for the
    guard (so it was authorized at the read tier) while the binder's own
    upper-casing found ``POST`` there (so the request was not marked read-only),
    and a handler served that way could write at the read tier.

    HTTP methods are case-sensitive on the wire and a client may send whatever it
    likes, so normalising is a **control**, not tidiness. A WebSocket has no
    method after the upgrade and is treated as a write, matching the guard's
    deny-by-default stance for a transport whose per-message authority a
    capability must police itself.
    """

    scope = getattr(connection, "scope", {})
    method = getattr(connection, "method", None) or scope.get(
        "method", "POST" if scope.get("type") == "websocket" else "GET"
    )
    return str(method).upper()


#: The attribute :func:`read_only` stamps on an endpoint. Read through
#: :func:`is_read_only` rather than directly — the name is an implementation
#: detail of this module, and the build-time rule matches on the *decorator*.
READ_ONLY_ATTRIBUTE = "__terp_read_only__"

_Endpoint = TypeVar("_Endpoint", bound=Callable[..., Any])


def read_only(endpoint: _Endpoint) -> _Endpoint:
    """Declare that *endpoint* computes an answer and never persists one.

    Apply it **below** the route decorator, so the marked function is the one
    FastAPI registers as the endpoint::

        @router.post("/{sync_id}/validation")
        @read_only
        def validate_candidate(...): ...

    Decorating a handler that does write is refused at build time by
    ``declared_read_only_routes_do_not_write``, and — if one is reached anyway —
    at run time by the session guard. Both are deliberate: the rule catches the
    edit that breaks the promise, and the guard catches the write the rule cannot
    see statically (through a helper, a subscriber, a capability).
    """

    setattr(endpoint, READ_ONLY_ATTRIBUTE, True)
    return endpoint


def is_read_only(endpoint: object | None) -> bool:
    """Whether *endpoint* was declared :func:`read_only`. ``None`` is not."""

    return bool(getattr(endpoint, READ_ONLY_ATTRIBUTE, False))


#: The attribute :func:`mark_required_permission` stamps on a route dependency.
#: Read through :func:`required_permission`; the name is this module's detail.
REQUIRED_PERMISSION_ATTRIBUTE = "__terp_required_permission__"


def mark_required_permission(dependency: _Endpoint, permission_name: str) -> _Endpoint:
    """Mark *dependency* as gating a route on *permission_name*.

    An **introspection marker, never a control**: the dependency the access
    capability builds does the enforcing, and this only makes the requirement
    legible to ``terp inspect access`` so a route-level grant appears in the
    access graph. Stamping it through this function rather than assigning the
    attribute inline keeps the name in one place — the capability that writes it
    and the CLI that reads it live in different packages, and the name used to be
    declared in the reader.
    """

    setattr(dependency, REQUIRED_PERMISSION_ATTRIBUTE, permission_name)
    return dependency


def required_permission(dependency: object | None) -> str | None:
    """The permission *dependency* gates on, or ``None`` if it gates on none."""

    name = getattr(dependency, REQUIRED_PERMISSION_ATTRIBUTE, None)
    return name if isinstance(name, str) else None


#: The attribute :func:`operation` stamps on an endpoint. Read through
#: :func:`declared_operation`; the name is this module's detail.
OPERATION_ATTRIBUTE = "__terp_operation__"


def operation(definition: OperationDefinition) -> Callable[[_Endpoint], _Endpoint]:
    """Declare what *definition* the decorated route performs (ADR 0102).

    Apply it **below** the route decorator, so the marked function is the one FastAPI
    registers as the endpoint — the same placement :func:`read_only` requires::

        @router.delete("/{file_id}", status_code=204)
        @operation(OPS.FILES_DELETE)
        def delete_file(file_id: uuid.UUID, session: SessionDep) -> None: ...

    The definition must be the entry registered in the control plane's
    :class:`~terp.core.operations.OperationCatalog`; boot refuses one that is not, so a
    route can neither invent an operation nor reference an undeclared one. Under
    :attr:`~terp.core.operations.OperationCoverage.STRICT` boot also refuses a mounted
    route that declares none.

    What it does **not** change is authorization — the promise :func:`read_only` makes,
    for the same reason. A route's requirement comes from its module's ``Policy`` and
    any route-level permission dependency; saying what a route *does* narrows nothing
    about who may call it, and this is not a way to widen or restrict access.
    """

    def decorate(endpoint: _Endpoint) -> _Endpoint:
        setattr(endpoint, OPERATION_ATTRIBUTE, definition)
        return endpoint

    return decorate


def declared_operation(endpoint: object | None) -> OperationDefinition | None:
    """The operation *endpoint* declares, or ``None`` if it declares none."""

    found = getattr(endpoint, OPERATION_ATTRIBUTE, None)
    return found if isinstance(found, OperationDefinition) else None


__all__ = [
    "MUTATING_METHODS",
    "OPERATION_ATTRIBUTE",
    "READ_ONLY_ATTRIBUTE",
    "REQUIRED_PERMISSION_ATTRIBUTE",
    "declared_operation",
    "is_read_only",
    "mark_required_permission",
    "operation",
    "read_only",
    "request_method",
    "required_permission",
]
