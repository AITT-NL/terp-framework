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

Reads stay unguarded for *writes* but are **row-scoped**: a ``SELECT`` through the
user-facing read methods (``exec`` / ``scalars`` / ``scalar``) and a primary-key
``get`` re-apply the framework's non-droppable row scope (soft-delete / tenant) to a
single-entity ``select(model)`` / ``get(model, id)``, so a bespoke read cannot leak a
soft-deleted or cross-tenant row by skipping ``base_query`` (the runtime backstop for
ADR 0017; the build-time ``reads_use_base_query`` rule is the early warning). ``execute``
is **not** re-scoped — it is the ORM's own internal load path (``refresh`` / lazy loads),
and scoping those would, e.g., make a just-soft-deleted row unrefreshable — so a raw
user ``execute(select(scoped_model))`` is covered by the build rule alone. ``flush`` is
intentionally **not** write-guarded so SQLAlchemy autoflush keeps working — nothing a
guarded session flushes is durable without the guarded ``commit`` (the request session is
rolled back on close), and ``add`` / ``delete`` are already refused outside the scope, so
no new or deleted row can be staged outside it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Select
from sqlalchemy import inspect as sa_inspect
from sqlmodel import Session, SQLModel, select

from terp.core.scoping import apply_row_scope

# Dynamic-scope flag: True only while BaseService._save / _remove are persisting.
# A ContextVar (not a session attribute) so the scope follows the call stack — the
# audit sink's nested session.add and an _after_write side effect are inside it —
# and token-based reset keeps nested writes correct (a service whose _after_write
# calls another _save) and restores the previous state even if the body raises.
_write_allowed: ContextVar[bool] = ContextVar(
    "terp_session_write_allowed", default=False
)

# Request-method gate: True while serving a safe (read-only) HTTP method
# (GET/HEAD/OPTIONS). A write attempted during such a request fails closed even
# inside the BaseService write scope, so a mutating safe-method handler cannot
# persist a change it was only authorized to *read* — the deny-by-default guard
# derives the role tier from the HTTP method, so a write during a GET runs at the
# read tier (a privilege-tier escape). The default is False, so a non-HTTP context
# (a test, the CLI, a migration) is unaffected.
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
            f"{operation!r} attempted while serving a safe, read-only HTTP method "
            "(GET/HEAD/OPTIONS); a request authorized at the read tier must not "
            "mutate — move the write behind a POST/PUT/PATCH/DELETE route so it is "
            "authorized at the write tier and audited"
        )
    if not _write_allowed.get():
        raise UnauditedWriteError(
            f"{operation!r} on the request Session outside the audited write "
            "chokepoint; persist through terp.core.BaseService (create / update / "
            "delete, or self._save / self._remove in a bespoke mutation) so every "
            "write is audited, actor-stamped, and event-hooked"
        )


def _is_read_statement(statement: Any) -> bool:
    """True for a ``SELECT`` (a read); every other statement is treated as a write.

    Fail-closed: only a recognised :class:`sqlalchemy.Select` (including SQLModel's
    ``SelectOfScalar``, a subclass) is a read. Anything else handed to ``execute`` /
    ``exec`` — a Core ``insert`` / ``update`` / ``delete``, a raw ``text(...)`` —
    requires the write scope.
    """
    return isinstance(statement, Select)


def _scoped_read(statement: Select) -> Select:
    """Re-apply the framework row scope to a single-entity ``select(model)``.

    A read issued **outside** ``BaseService.base_query`` — a bespoke service method
    that does ``session.exec(select(self.model)...)`` directly — would otherwise drop
    soft-delete / tenant scope (the F1 follow-up to ADR 0017): the build-time
    ``reads_use_base_query`` rule flags the common shape, and this is the runtime
    backstop that closes it for the user-facing read methods (``exec`` / ``scalars`` /
    ``scalar``; the primary-key ``get`` has its own scoped path). When the statement
    selects exactly one mapped entity, the registered scope predicates are composed in
    (:func:`~terp.core.scoping.apply_row_scope`) — **idempotently**, so a query already
    built from ``base_query`` is unchanged in effect, and it is a no-op for a model
    with no scope trait. A multi-entity select, a column/aggregate select (e.g. the
    pagination ``count``), or a non-model statement is left untouched. Only the request
    session re-scopes, so a bare ``Session`` (a test, a deliberate privileged read) is
    unaffected.
    """
    descriptions = statement.column_descriptions
    if len(descriptions) == 1:
        entity = descriptions[0].get("entity")
        if isinstance(entity, type) and issubclass(entity, SQLModel):
            return apply_row_scope(entity, statement)
    return statement


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
        if _is_read_statement(statement):
            statement = _scoped_read(statement)
        else:
            _require_write_scope("exec")
        return super().exec(statement, *args, **kwargs)

    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        # NB: only ``exec`` (the SQLModel user-facing read) re-applies row scope.
        # ``execute`` is what the ORM itself calls internally (``refresh``, lazy
        # loads, identity reloads), and scoping those would, e.g., make a just
        # soft-deleted row unrefreshable — so here we only enforce the write guard.
        # A user-issued ``execute(select(scoped_model))`` is still caught by the
        # build-time ``reads_use_base_query`` rule.
        if not _is_read_statement(statement):
            _require_write_scope("execute")
        return super().execute(statement, *args, **kwargs)

    def scalars(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        # A user-facing scalar read: re-scope a single-entity ``select(model)`` like
        # ``exec`` (so a bespoke ``session.scalars(select(ScopedModel))`` cannot drop
        # soft-delete / tenant scope), or require the write scope for a DML statement
        # (a RETURNING insert/update/delete), like ``execute``.
        if _is_read_statement(statement):
            statement = _scoped_read(statement)
        else:
            _require_write_scope("scalars")
        return super().scalars(statement, *args, **kwargs)

    def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        # The single-value sibling of ``scalars`` — same row-scope / write-guard split.
        if _is_read_statement(statement):
            statement = _scoped_read(statement)
        else:
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


__all__ = [
    "ReadOnlyRequestError",
    "UnauditedWriteError",
    "WriteGuardedSession",
    "allow_session_writes",
    "enter_write_unit",
    "forbid_session_writes",
    "read_only_request",
]