"""The row-scope predicate registry — capabilities plug row visibility into reads.

Soft-delete is the kernel's own built-in row scope; a capability (e.g. tenancy)
adds its predicate here so :class:`~terp.core.BaseService` composes it into **every**
read query, without the kernel importing the capability. Predicates are applied
centrally and **cannot be dropped by a service**: a module narrows its reads through
:meth:`~terp.core.BaseService.business_filters` (which only *adds* conditions), never
by overriding ``base_query`` (the ``terp.arch`` ``base_query_not_overridden`` rule
forbids it). This is the structural fix for the "a ``super()``-less ``base_query``
override silently drops soft-delete / tenant scoping" footgun (ADR 0017).
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import or_
from sqlmodel import SQLModel
from sqlmodel.sql.expression import SelectOfScalar

from terp.core.base_models import OwnedMixin, SoftDeleteMixin

# A predicate narrows a read query for the models it owns (row visibility). It
# receives the model and the query and returns the query with its WHERE clause
# added — or the query unchanged for a model it does not apply to (it must guard on
# the relevant mixin and be idempotent, since it runs on every read of every model).
ScopePredicate = Callable[[type[SQLModel], SelectOfScalar], SelectOfScalar]

_scope_predicates: list[ScopePredicate] = []


def register_scope_predicate(predicate: ScopePredicate) -> None:
    """Register a row-visibility predicate applied to every ``BaseService`` read.

    The seam a capability uses to plug a row predicate (e.g. the tenant filter) into
    the kernel without the kernel importing it. Registration is idempotent.
    ``BaseService.base_query`` composes every registered predicate on top of the
    built-in soft-delete scope, so a service cannot drop it.
    """
    if predicate not in _scope_predicates:
        _scope_predicates.append(predicate)


def registered_scope_predicates() -> tuple[ScopePredicate, ...]:
    """Every registered row-scope predicate, in registration order."""
    return tuple(_scope_predicates)


def apply_row_scope(model: type[SQLModel], query: SelectOfScalar) -> SelectOfScalar:
    """Compose the framework's non-droppable row scope onto *query* for *model*.

    The single definition of "row scope": the built-in soft-delete predicate (when
    *model* is a :class:`~terp.core.SoftDeleteMixin`) plus every capability-registered
    row predicate (e.g. the tenant filter). :meth:`~terp.core.BaseService.base_query`
    composes it, **and** the request session re-applies it to any single-entity
    ``select(model)`` a custom read issues directly — so reading a scope-trait model
    outside ``base_query`` can no longer silently drop soft-delete / tenant scope
    (the runtime backstop for ADR 0017; the ``reads_use_base_query`` rule is the
    build-time early warning). It is **idempotent** — composing it twice yields the
    same filtered set — so the double application (``base_query`` + session) is safe,
    and it is a no-op for a model with no scope trait.
    """
    if issubclass(model, SoftDeleteMixin):
        query = query.where(model.deleted_at.is_(None))  # type: ignore[attr-defined]
    for predicate in _scope_predicates:
        query = predicate(model, query)
    return query


def _owner_read_scope_predicate(
    model: type[SQLModel], query: SelectOfScalar
) -> SelectOfScalar:
    """Filter an :class:`~terp.core.OwnedMixin` model's reads to the request actor.

    The read half of the ownership trait, which the trait itself deliberately is not:
    ``OwnedMixin`` gates *writes*, because a post-load boolean cannot paginate a list,
    and its docstring has always pointed here for visibility. Installing it was left as
    an exercise, and an exercise left undone reads exactly like a control that is
    present — which is how a surface comes to be described as owner-scoped while every
    caller who clears its role sees every row.

    An **unowned** row (``owner_id is None`` — created by a job, a migration, a seed,
    anything with no bound actor) stays visible to everyone, matching the write gate,
    which does not restrict a row with no owner to protect. An **actor-less read** (out
    of request, a worker, a CLI) is not narrowed either: there is no "self" to scope to,
    and narrowing to nothing would make background work silently see an empty database
    rather than fail. Both are widening defaults, which is why this is opt-in rather
    than automatic — see :func:`register_owner_read_scope`.
    """
    # Imported at call time, not at module scope: `terp.core.audit` reaches this
    # module through the session guard, so a top-level import here closes a cycle
    # that only shows up as a half-initialised module at first import.
    from terp.core.audit import audit_actor_ctx  # noqa: PLC0415 - cycle, see above

    if not issubclass(model, OwnedMixin):
        return query
    actor = audit_actor_ctx.get()
    if actor is None:
        return query
    return query.where(
        or_(model.owner_id.is_(None), model.owner_id == actor)  # type: ignore[attr-defined]
    )


def register_owner_read_scope() -> None:
    """Install the owner read filter for every :class:`~terp.core.OwnedMixin` model.

    One composition-root line, idempotent, and **opt-in on purpose**: it narrows what an
    already-authorized caller can see, so turning it on is a decision about a product
    rather than a default a framework can take. A deployment whose administrators are
    expected to see each other's rows would find its screens quietly emptied by an
    automatic version of this.

    Composed with the trait's built-in write gate it gives the property ``OwnedMixin``
    describes in full — only the owner sees **or** changes the row — and it is the whole
    of the "register a row-scope predicate keyed on ``owner_id``" that docstring asks
    for, so an app no longer has to write the predicate to get it right.
    """
    register_scope_predicate(_owner_read_scope_predicate)


def _reset_scope_predicates() -> None:
    """Clear all registered predicates (a test seam; capabilities re-register on import).

    **Private, and reachable only through** :mod:`terp.core._internal.registry_resets`
    (ADR 0137). Emptying this list is not a neutral act: it removes the tenant filter
    and every other registered row predicate for the whole process, in one call, with
    no exception and nothing in the log — reads simply start returning rows they used
    to hide. That is the shape of thing the ``no_internal_imports`` rule exists to keep
    out of module code, which is why the public spelling now lives behind it, exactly
    as ``allow_session_writes`` does for the write guard.
    """
    _scope_predicates.clear()


__all__ = [
    "ScopePredicate",
    "apply_row_scope",
    "register_owner_read_scope",
    "register_scope_predicate",
    "registered_scope_predicates",
]
