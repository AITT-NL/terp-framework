"""Route-level declarations a module makes about one handler, and the method vocabulary.

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
One vocabulary, phrased once as a single negation, is what makes the two halves
agree by construction rather than by coincidence.

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

#: The HTTP methods that carry write authority — the one definition of the split.
#:
#: A request whose method is in this set is authorized against the policy's *write*
#: requirement and may persist; **every other method** is authorized at the read tier
#: and is marked read-only, whether or not it is one of RFC 9110's safe methods. The
#: classification is deliberately a single negation rather than two sets, so no method
#: can fall between them.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

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


__all__ = ["MUTATING_METHODS", "READ_ONLY_ATTRIBUTE", "is_read_only", "read_only"]
