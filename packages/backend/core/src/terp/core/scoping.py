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

from sqlmodel import SQLModel
from sqlmodel.sql.expression import SelectOfScalar

from terp.core.base_models import SoftDeleteMixin

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


def reset_scope_predicates() -> None:
    """Clear all registered predicates (a test seam; capabilities re-register on import)."""
    _scope_predicates.clear()


__all__ = [
    "ScopePredicate",
    "apply_row_scope",
    "register_scope_predicate",
    "registered_scope_predicates",
    "reset_scope_predicates",
]
