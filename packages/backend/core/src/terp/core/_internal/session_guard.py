"""Runtime write-guarded ``Session`` — the structural half of the audited chokepoint.

:data:`terp.core.db.SessionDep` hands out a :class:`WriteGuardedSession` whose
persistence methods (``add`` / ``add_all`` / ``delete`` / ``merge`` / ``commit`` /
the ``bulk_*`` helpers / a DML ``execute`` / ``exec``) **fail closed** unless they
run inside :func:`allow_session_writes` — the dynamic scope that
:meth:`terp.core.BaseService._save` / ``_remove`` open around every write. So a
module that tries to persist a mutation *outside* the audited ``BaseService``
chokepoint — ``session.add(row); session.commit()`` under **any** variable name, or
a smuggled ``session.execute(update(...))`` — raises :class:`UnauditedWriteError`
at runtime instead of silently skipping the audit trail, actor-stamp, event hook,
and 409 mapping. The chokepoint owns the commit and the scope is **re-entrant** (ADR
0038): only the outermost write commits, so a nested write joins it as one audited,
atomic unit with no double commit.

This is the runtime, structural counterpart to the build-time ``terp.arch``
``mutations_emit_audit`` rule (the two-layer discipline, ADR 0006): the rule
flags direct session writes statically, and this guard catches every direct
request-``Session`` method shape dynamically — regardless of how the session
variable is named or which package the write lives in. The separate raw
engine/connection surface is guarded by the build-time ``no_raw_connection_access``
rule (and ``connection()`` itself is guarded here). This module lives under ``_internal`` so a module cannot import
:func:`allow_session_writes` to wave itself past the guard (the ``no_internal_imports``
rule forbids importing ``terp.core._internal`` from a module — the second layer
protecting the guard itself).

Reads stay unguarded for *writes* but are **row-scoped**. The ORM execution hook applies
criteria to each entity, including aliases and relationship loaders, and to every mapped
entity a read names, wherever it names it: an aggregate's, and one in a loader option, a
``VALUES`` row or a column property of a model it loads. Only a column refresh of an
already-loaded instance is exempt, so the write chokepoint can refresh a just-soft-deleted
row without granting the exemption to relationship reads. ``get`` also checks visibility
before its identity-map fast path. A read that reaches a row-scoped table only through its
Core ``Table`` names no mapped entity to take that criteria, and literal SQL cannot be read
at all, so the hook refuses either with :class:`UnscopedReadError` instead of running it
unscoped (ADR 0204 decision 6). A ``SELECT`` that carries an ``INSERT``, ``UPDATE`` or
``DELETE`` in a CTE is a write, not a read. ``flush`` is intentionally **not**
write-guarded so SQLAlchemy autoflush keeps working — nothing a guarded session flushes is
durable without the guarded ``commit`` (the request session is rolled back on close), and
``add`` / ``delete`` are already refused outside the scope, so no new or deleted row can be
staged outside it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Select, event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import ORMExecuteState, with_loader_criteria
from sqlalchemy.sql.util import ClauseAdapter
from sqlmodel import Session, SQLModel, select

from terp.core.scoping import (
    _core_only_reads,
    _entities_in,
    _mapping_sql,
    _writes,
    apply_row_scope,
)

# Dynamic-scope flag: True only while BaseService._save / _remove are persisting.
# A ContextVar (not a session attribute) so the scope follows the call stack — the
# audit sink's nested session.add and an _after_write side effect are inside it —
# and token-based reset keeps nested writes correct (a service whose _after_write
# calls another _save) and restores the previous state even if the body raises.
_write_allowed: ContextVar[bool] = ContextVar(
    "terp_session_write_allowed", default=False
)

# Request-method gate: True while serving a request authorized at the read tier —
# any method outside terp.core.routing.MUTATING_METHODS, which is every safe method
# and anything else a route may be registered under. A write attempted during such a
# request fails closed even inside the BaseService write scope, so such a handler
# cannot persist a change it was only authorized to *read* — the deny-by-default
# guard derives the role tier from the HTTP method, so a write during a GET runs at
# the read tier (a privilege-tier escape). The default is False, so a non-HTTP
# context (a test, the CLI, a migration) is unaffected.
_read_only_request: ContextVar[bool] = ContextVar(
    "terp_read_only_request", default=False
)

# Re-entrancy depth of the audited write chokepoint. Each BaseService._save /
# _remove opens one unit of work; the OUTERMOST (depth 0 -> 1) owns the single
# commit, and a nested write (an _after_write that calls self._save) joins the same
# transaction (stage + flush, no commit) — so every write, however nested, lands as
# one audited, atomic unit and there is no double-commit / half-committed footgun.
# Separate from the allow flag (which forbid_session_writes toggles) so the depth is
# never disturbed by re-arming the guard around a hook.
_write_depth: ContextVar[int] = ContextVar("terp_session_write_depth", default=0)


class UnauditedWriteError(RuntimeError):
    """A write was attempted on the request ``Session`` outside the audited chokepoint.

    Raised by :class:`WriteGuardedSession` when ``add`` / ``commit`` / a DML
    ``execute`` / etc. run outside :func:`allow_session_writes`. It is a
    *programming* error (a bypass of ``BaseService``), so it surfaces as a generic
    500 through the composition root's catch-all handler — never the uniform
    :class:`~terp.core.AppError` envelope, which would imply a handled,
    client-facing condition.
    """


class ReadOnlyRequestError(RuntimeError):
    """A write was attempted while serving a safe (read-only) HTTP method.

    The deny-by-default guard authorizes a request by HTTP method — a safe method
    (``GET`` / ``HEAD`` / ``OPTIONS``) is checked against the policy's *read*
    requirement — so a write during one is a privilege-tier escape: a caller cleared
    only the read tier yet mutated. Like :class:`UnauditedWriteError` it is a
    *programming* error (a mutating safe-method handler) and surfaces as a generic
    500. Move the write behind a ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` route so
    it is authorized at the write tier (and audited). This is the runtime half of the
    build-time ``safe_methods_are_read_only`` rule.
    """


class UnscopedReadError(RuntimeError):
    """A read reaches what the request session cannot scope (ADR 0204 decision 6).

    The request session scopes a read by attaching soft-delete and the registered row
    predicates to each **mapped entity** a SELECT names. ``Model.__table__.c.amount``,
    ``select_from(Model.__table__)``, a Core alias or sample of that table, a ``table("name")``
    in any case or schema, or a column property that reads it so, reaches the rows without
    one, so there is nothing to attach the scope to and the read would return soft-deleted or
    another tenant's rows. Literal SQL, wherever the statement holds it, and a FROM element
    the session does not know are refused with them: it can neither read nor scope them.
    Refused before it runs. Like :class:`UnauditedWriteError` it is a *programming* error and
    surfaces as a generic 500: read through the model, on the service's ``base_query()`` or a
    declared aggregate.
    """


#: Why a read was refused and what to do instead, after the list of what it reaches.
_UNSCOPED_READ_REMEDY = (
    "The session applies soft-delete, tenant and owner scope to every mapped entity a read "
    "names, wherever it names it, so it cannot reach a table read through Core, literal SQL, "
    "or a FROM element it does not know. Read it through the model: the service's "
    "base_query(), or a declared aggregate (terp guide aggregates), never Model.__table__ or "
    "literal SQL. A many-to-many whose link table is row-scoped maps the link as an "
    "association object instead of a secondary table."
)


@contextlib.contextmanager
def allow_session_writes() -> Iterator[None]:
    """Open the dynamic scope in which a :class:`WriteGuardedSession` accepts writes.

    :meth:`terp.core.BaseService._save` / ``_remove`` wrap their persistence in
    this scope; everything they call while persisting (the audit sink, an
    ``_after_write`` hook) inherits it. Token-based reset keeps nested writes
    correct and restores the previous state even if the body raises.
    """
    token = _write_allowed.set(True)
    try:
        yield
    finally:
        _write_allowed.reset(token)


@contextlib.contextmanager
def enter_write_unit() -> Iterator[bool]:
    """Open the audited write scope and join the current unit of work; yield outermost-ness.

    The re-entrant chokepoint scope :meth:`terp.core.BaseService._save` / ``_remove``
    wrap their persistence in (ADR 0038): it opens :func:`allow_session_writes` *and*
    bumps a depth counter, yielding ``True`` only for the **outermost** write. The
    outermost write owns the single ``commit``; a nested write (an ``_after_write``
    that calls ``self._save``) yields ``False`` and stages into the same transaction,
    so every write — however nested — lands as one audited, atomic unit and a partial
    commit is impossible. Token-based reset restores both the allow flag and the depth
    even if the body raises (the rollback then unwinds the whole unit), so nothing
    leaks across writes sharing a worker thread.
    """
    outermost = _write_depth.get() == 0
    depth_token = _write_depth.set(_write_depth.get() + 1)
    allow_token = _write_allowed.set(True)
    try:
        yield outermost
    finally:
        _write_allowed.reset(allow_token)
        _write_depth.reset(depth_token)


@contextlib.contextmanager
def forbid_session_writes() -> Iterator[None]:
    """Re-close the write scope for the duration of the block (re-arm the guard).

    The inverse of :func:`allow_session_writes`. ``BaseService`` wraps the subclass
    ``_after_write`` hook in this so that, although the hook runs *inside* the write,
    a **raw** ``session.add`` / ``commit`` there still fails closed — closing the F5
    seam where the open write scope silently re-admitted an unaudited write. The hook
    may still ``emit`` an event (which never touches the session) or call
    ``self._save`` / ``self._remove`` (which re-open the scope for their own audited
    write); only a bare session mutation is refused. Token-based reset restores the
    previous state even if the body raises.
    """
    token = _write_allowed.set(False)
    try:
        yield
    finally:
        _write_allowed.reset(token)


@contextlib.contextmanager
def read_only_request(read_only: bool) -> Iterator[None]:
    """Mark the current request read-only (or not) for the duration of the block.

    ``terp.core.create_app`` mounts a per-request dependency that opens this for a
    safe HTTP method (``GET`` / ``HEAD`` / ``OPTIONS``), so a write through the
    ``BaseService`` chokepoint then fails closed (:class:`ReadOnlyRequestError`) — the
    runtime half of the build-time ``safe_methods_are_read_only`` rule. It is set in
    an **async** dependency (like the audit-actor binder) so the flag propagates into
    the threadpooled sync route, and token-based reset restores the previous state
    even if the body raises, so it never leaks across requests sharing a worker thread.
    """
    token = _read_only_request.set(read_only)
    try:
        yield
    finally:
        _read_only_request.reset(token)


@contextlib.contextmanager
def fresh_write_scope() -> Iterator[None]:
    """Run a body as a brand-new, independent unit of work, clearing inherited write state.

    A background job's runner (``terp.core._internal.job_runtime.run_job``) opens this
    around the handler. The in-process job queue runs a handler **inline in the caller's
    context**, so without this the job would inherit the *enclosing request's* write state:
    a job enqueued from within an audited write would see ``_write_depth > 0`` and its own
    ``_save`` would treat itself as *nested*, deferring the single commit to an "outer" unit
    that lives on a **different** session and never commits it — a silently lost, unaudited
    write — and a job enqueued during a safe (read-only) request would be wrongly refused.
    Resetting the depth (to 0), the write-allow flag (to closed), and the read-only flag (to
    off) makes the job its **own** outermost unit at the envelope's authority, so its writes
    commit and are audited regardless of what scheduled it. Token-based reset restores the
    caller's state even if the body raises.
    """
    depth_token = _write_depth.set(0)
    allow_token = _write_allowed.set(False)
    read_only_token = _read_only_request.set(False)
    try:
        yield
    finally:
        _read_only_request.reset(read_only_token)
        _write_allowed.reset(allow_token)
        _write_depth.reset(depth_token)


def _require_write_scope(operation: str) -> None:
    """Raise unless a write is permitted here.

    Fail closed in two cases: while serving a safe (read-only) HTTP method — a write
    there is a privilege-tier escape, refused even inside the chokepoint
    (:class:`ReadOnlyRequestError`) — and outside the audited
    :func:`allow_session_writes` scope (:class:`UnauditedWriteError`).
    """
    if _read_only_request.get():
        raise ReadOnlyRequestError(
            f"{operation!r} attempted while serving a read-only request — a method "
            "outside POST/PUT/PATCH/DELETE, or a route declared terp.core.read_only; "
            "a request authorized at the read tier must not mutate — move the write "
            "behind a POST/PUT/PATCH/DELETE route so it is authorized at the write "
            "tier and audited"
        )
    if not _write_allowed.get():
        raise UnauditedWriteError(
            f"{operation!r} on the request Session outside the audited write "
            "chokepoint; persist through terp.core.BaseService (create / update / "
            "delete, or self._save / self._remove in a bespoke mutation) so every "
            "write is audited, actor-stamped, and event-hooked"
        )


def _is_read_statement(statement: Any) -> bool:
    """True for a ``SELECT`` that writes nothing (a read); every other statement is a write.

    Fail-closed: only a recognised :class:`sqlalchemy.Select` (including SQLModel's
    ``SelectOfScalar``, a subclass) is a read, and only when no part of it writes: a
    ``SELECT`` that carries an ``INSERT``, ``UPDATE`` or ``DELETE`` in a CTE runs it.
    Anything else handed to ``execute`` / ``exec`` — a Core ``insert`` / ``update`` /
    ``delete``, a raw ``text(...)`` — requires the write scope.
    """
    return isinstance(statement, Select) and not _writes(statement)


class WriteGuardedSession(Session):
    """A :class:`~sqlmodel.Session` that refuses to persist outside the audited chokepoint.

    Handed out by :data:`terp.core.db.SessionDep`. Every mutating method checks
    :func:`allow_session_writes` first and raises :class:`UnauditedWriteError` when
    called outside it; reads pass straight through. See the module docstring for
    the rationale and the deliberate non-guarding of ``flush``.
    """

    def add(self, instance: object, *args: Any, **kwargs: Any) -> None:
        _require_write_scope("add")
        super().add(instance, *args, **kwargs)

    def add_all(self, instances: Any) -> None:
        _require_write_scope("add_all")
        super().add_all(instances)

    def delete(self, instance: object, *args: Any, **kwargs: Any) -> None:
        _require_write_scope("delete")
        super().delete(instance, *args, **kwargs)

    def merge(self, instance: object, *args: Any, **kwargs: Any) -> Any:
        _require_write_scope("merge")
        return super().merge(instance, *args, **kwargs)

    def connection(self, *args: Any, **kwargs: Any) -> Any:
        # The bound Connection can issue DML directly, bypassing the method guards
        # above, so handing it out outside the write scope is itself a write-path
        # escape (the F3 follow-up to ADR 0015). The ORM's own execution uses the
        # private bind resolver, not this public accessor, so guarding it does not
        # affect reads. (A fresh connection from ``get_bind().connect()`` is a
        # separate transaction this cannot reach; the build-time
        # ``no_raw_connection_access`` rule is the layer that forbids *obtaining* the
        # engine/connection in a module.)
        _require_write_scope("connection")
        return super().connection(*args, **kwargs)

    def commit(self) -> None:
        _require_write_scope("commit")
        super().commit()

    def bulk_save_objects(self, *args: Any, **kwargs: Any) -> None:
        _require_write_scope("bulk_save_objects")
        super().bulk_save_objects(*args, **kwargs)

    def bulk_insert_mappings(self, *args: Any, **kwargs: Any) -> None:
        _require_write_scope("bulk_insert_mappings")
        super().bulk_insert_mappings(*args, **kwargs)

    def bulk_update_mappings(self, *args: Any, **kwargs: Any) -> None:
        _require_write_scope("bulk_update_mappings")
        super().bulk_update_mappings(*args, **kwargs)

    def exec(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_read_statement(statement):
            _require_write_scope("exec")
        return super().exec(statement, *args, **kwargs)

    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        # Entity visibility is enforced by the ORM hook below, including when the
        # ORM calls execute internally for a relationship load.
        if not _is_read_statement(statement):
            _require_write_scope("execute")
        return super().execute(statement, *args, **kwargs)

    def scalars(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_read_statement(statement):
            _require_write_scope("scalars")
        return super().scalars(statement, *args, **kwargs)

    def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_read_statement(statement):
            _require_write_scope("scalar")
        return super().scalar(statement, *args, **kwargs)

    def get(self, entity: Any, ident: Any, *args: Any, **kwargs: Any) -> Any:
        # A primary-key load bypasses ``base_query`` and the row predicates entirely,
        # so ``session.get(ScopedModel, id)`` would return a soft-deleted / cross-tenant
        # row by id — the one read shape the ``exec``-based backstop never saw, and the
        # one the build-time ``reads_use_base_query`` rule cannot reach via a
        # ``select(...)`` node (the F1 follow-up to ADR 0017). When row scope narrows
        # this model, gate the load on the scope:
        #   * with no ``get()`` options, re-issue it as one scoped primary-key query;
        #   * with options (``with_for_update`` / loader ``options`` /
        #     ``populate_existing`` / ...), confirm visibility with a primary-key-only
        #     probe — which loads no entity, so the identity map is untouched and a
        #     ``with_for_update`` still locks — then delegate to the parent ``get()`` so
        #     every option is honored exactly, never silently dropped.
        # An unscoped model keeps the parent's identity-map fast path unchanged.
        if isinstance(entity, type) and issubclass(entity, SQLModel):
            base = select(entity)
            scoped = apply_row_scope(entity, base)
            if scoped is not base:
                pk_column = sa_inspect(entity).primary_key[0]
                if args or kwargs:
                    visible = super().exec(
                        apply_row_scope(entity, select(pk_column)).where(
                            pk_column == ident
                        )
                    ).first()
                    if visible is None:
                        return None
                    return super().get(entity, ident, *args, **kwargs)
                return super().exec(scoped.where(pk_column == ident)).first()
        return super().get(entity, ident, *args, **kwargs)


@event.listens_for(WriteGuardedSession, "do_orm_execute")
def _scope_orm_read(state: ORMExecuteState) -> None:
    """Apply the current row scope to every entity a read names and every one related to it.

    Criteria are built at execution time and also propagate to relationship
    loaders. A later load is narrowed by the current scope as well as the original
    one, never widened when a context changes. Sessions belong to one authority
    context; another tenant uses a fresh session. Joined loaders receive their
    predicates in the JOIN, preserving outer-join parents. Column refreshes are
    the narrow exception needed after a soft-delete write.
    """
    if not state.is_select or state.is_column_load:
        return
    pending = list(state.all_mappers)
    aliases = {}
    # Include entities used only by a JOIN, predicate, nested SELECT, loader option or
    # VALUES row, and those a column property of a reached model names: they can disclose
    # scoped rows even when the result projects only an unscoped parent.
    sources = [state.statement]
    seen = set()
    while sources or pending:
        if sources:
            for inspected in _entities_in(sources.pop()):
                if inspected.is_aliased_class:
                    aliases[inspected] = None
                pending.append(inspected.mapper)
            continue
        mapper = pending.pop()
        if mapper in seen:
            continue
        seen.add(mapper)
        pending.extend(relation.mapper for relation in mapper.relationships)
        sources.extend(sql for sql, _place in _mapping_sql(mapper))
        model = mapper.class_
        if not issubclass(model, SQLModel):
            continue
        scoped = apply_row_scope(model, select(model))
        if scoped.whereclause is not None:
            state.statement = state.statement.options(
                with_loader_criteria(model, scoped.whereclause)
            )
    unscoped = _core_only_reads(state.statement, seen)
    if unscoped:
        raise UnscopedReadError(
            f"A read reaches what the request session cannot scope: {'; '.join(unscoped)}. "
            f"{_UNSCOPED_READ_REMEDY}"
        )
    # An explicit alias in an explicit JOIN needs criteria referring to that
    # selectable, rather than columns from the original table. Implicit aliases
    # used by joinedload are adapted by the ORM itself.
    for inspected in aliases:
        model = inspected.mapper.class_
        if not issubclass(model, SQLModel):
            continue
        scoped = apply_row_scope(model, select(model))
        if scoped.whereclause is not None:
            criteria = ClauseAdapter(inspected.selectable).traverse(scoped.whereclause)
            state.statement = state.statement.options(
                with_loader_criteria(inspected.entity, criteria)
            )


__all__ = [
    "ReadOnlyRequestError",
    "UnauditedWriteError",
    "UnscopedReadError",
    "WriteGuardedSession",
    "allow_session_writes",
    "enter_write_unit",
    "forbid_session_writes",
    "read_only_request",
]
