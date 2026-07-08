"""Generic CRUD service base — promoted after two divergent modules proved its shape.

``BaseService`` provides the uniform, OCC-bearing writes (``create`` / ``update``)
and pagination, while ``get`` / ``list`` / ``delete`` build on ``base_query`` — a
**non-overridable** scoped query that composes soft-delete, every capability-registered
row predicate (e.g. tenant scoping), and the service's ``business_filters`` hook, so
row scope cannot be dropped by a ``super()``-less override (ADR 0017).

Every write routes through the single ``_save`` / ``_remove`` chokepoint, which
**auto-emits an audit record** (design §5.8, ADR 0007) inside the same
transaction — so a module gets an audit trail with zero wiring, and a custom
mutation re-uses ``_save`` rather than touching the session directly. The
chokepoint **owns the commit** and is **re-entrant** (ADR 0038): the outermost
``_save`` / ``_remove`` commits once, and a nested write (an ``_after_write`` that
calls ``self._save``) joins that same transaction, so every write — however nested
— lands as one audited, atomic unit with no double-commit or half-committed graph.
The same
chokepoint **auto-honors model traits**: it excludes / soft-deletes a
:class:`~terp.core.SoftDeleteMixin` row (ADR 0010) and stamps the request actor on
a :class:`~terp.core.ActorStampedMixin` row (ADR 0012), both with zero module code.
It also exposes an ``_after_write`` hook (after the row + audit are staged, before
the commit) that a subclass overrides to fold an in-transaction side effect — e.g.
emitting a domain event (ADR 0008) — into the same atomic unit of work.

Evidence (ADR 0001, Decision 5): ``notes`` uses it wholesale (just ``model =
Note``); ``tasks`` adds only a ``list`` status filter (soft-delete and ``delete``
are auto-honored traits) — create/update are inherited unchanged.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Generic, TypeVar

from sqlalchemy import ColumnElement, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError as ORMStaleDataError
from sqlmodel import Session, SQLModel, select
from sqlmodel.sql.expression import SelectOfScalar

from terp.core.audit import AuditAction, audit_actor_ctx, emit_audit
from terp.core.base_models import (
    ActorStampedMixin,
    BaseTable,
    BaseUpdateSchema,
    OwnedMixin,
    SoftDeleteMixin,
)
from terp.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    StaleDataError,
)
from terp.core.object_authz import apply_object_authz
from terp.core.pagination import CursorPaginationParams, decode_cursor, encode_cursor
from terp.core.scoping import apply_row_scope
from terp.core._internal.session_guard import (
    enter_write_unit,
    forbid_session_writes,
)

ModelT = TypeVar("ModelT", bound=BaseTable)
CreateT = TypeVar("CreateT", bound=SQLModel)
UpdateT = TypeVar("UpdateT", bound=BaseUpdateSchema)

# Framework-managed columns a client input must never set: BaseService assigns all
# of these centrally (the primary key + audit timestamps + the OCC ``version`` +
# the scope/actor/owner columns). ``create`` / ``update`` strip them from the inbound
# payload so an over-wide schema (or a hand-built dict) can never over-post
# (mass-assign) them -- e.g. forge ``owner_id`` to seize a record. The terp.arch
# ``input_schemas_exclude_managed_columns`` rule is the build-time half of this
# control; the two sets must stay in lockstep.
_MANAGED_INPUT_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "version",
        "deleted_at",
        "tenant_id",
        "created_by_id",
        "modified_by_id",
        "owner_id",
        "token_version",
    }
)


def _utc_now() -> datetime:
    """UTC ``now`` provider for the soft-delete stamp (private so tests can patch it)."""
    return datetime.now(UTC)


class BaseService(Generic[ModelT, CreateT, UpdateT]):
    """Canonical CRUD for a :class:`~terp.core.BaseTable` model.

    Subclasses declare ``model`` and override only what diverges::

        class NoteService(BaseService[Note, NoteCreate, NoteUpdate]):
            model = Note
    """

    model: type[ModelT]

    def business_filters(self) -> Sequence[ColumnElement[bool]]:
        """Extra read conditions, composed **on top of** the non-droppable row scope.

        Override to **add** static business filters to every read (``get`` / ``list``)
        — e.g. "only rows in an active state". You return *conditions*, not a query, so
        you can never drop the framework's soft-delete / tenant scope from here (that
        is the point): there is **no** ``super()`` to remember and no way to widen a
        read. A per-call dynamic filter (a query parameter) belongs in a custom
        ``list`` that builds on ``base_query().where(...)``. Default: no extra
        conditions.
        """
        return ()

    def base_query(self) -> SelectOfScalar[ModelT]:
        """The scoped query every read builds on — **do not override this**.

        Composes, in order: ``select(model)``, the built-in soft-delete scope (when
        ``model`` is a :class:`~terp.core.SoftDeleteMixin`), every capability-registered
        row predicate (e.g. the tenant filter — ``register_scope_predicate``), and this
        service's :meth:`business_filters`. Row scope is applied **centrally and cannot
        be dropped by a service**: add conditions via :meth:`business_filters`, never by
        overriding this method. The ``terp.arch`` ``base_query_not_overridden`` rule
        forbids overriding it, precisely so a ``super()``-less override can never
        silently drop soft-delete or tenant scoping (and ``no_manual_scope_filtering``
        forbids hand-writing the managed columns). A custom read that issues a raw
        ``select(model)`` instead of building on this is re-scoped by the request
        session anyway (``apply_row_scope``), with the ``reads_use_base_query`` rule
        as the build-time early warning.
        """
        query = apply_row_scope(self.model, select(self.model))
        conditions = self.business_filters()
        if conditions:
            query = query.where(*conditions)
        return query

    def _paginate(
        self,
        session: Session,
        query: SelectOfScalar[ModelT],
        *,
        skip: int,
        limit: int,
    ) -> tuple[list[ModelT], int]:
        total = session.exec(select(func.count()).select_from(query.subquery())).one()
        rows = session.exec(
            query.order_by(self.model.created_at).offset(skip).limit(limit)
        ).all()
        return list(rows), total

    def get(self, session: Session, entity_id: uuid.UUID) -> ModelT:
        entity = session.exec(
            self.base_query().where(self.model.id == entity_id)
        ).first()
        if entity is None:
            raise NotFoundError()
        return entity

    def list(
        self, session: Session, *, skip: int, limit: int
    ) -> tuple[list[ModelT], int]:
        return self._paginate(session, self.base_query(), skip=skip, limit=limit)

    def list_by_cursor(
        self, session: Session, *, pagination: CursorPaginationParams
    ) -> tuple[list[ModelT], str | None, int | None]:
        """Keyset-paginated list: rows after the cursor, a next cursor, an optional total.

        The scale-friendly alternative to :meth:`list` (ADR 0064, review M5): rows are
        ordered by the stable ``(created_at, id)`` keyset and each page starts strictly
        *after* the opaque cursor's position — no ``OFFSET`` scan — and the exact
        ``COUNT(*)`` runs **only** when the request asked for it
        (``include_total=true``). Builds on the same non-droppable :meth:`base_query`
        row scope as every other read. Returns ``(rows, next_cursor, total)``;
        ``next_cursor`` is ``None`` on the last page, ``total`` is ``None`` unless
        requested. A tampered cursor raises the typed
        :class:`~terp.core.errors.ValidationFailedError` (400).
        """
        query = self.base_query()
        total: int | None = None
        if pagination.include_total:
            total = session.exec(
                select(func.count()).select_from(query.subquery())
            ).one()
        if pagination.cursor is not None:
            after_at, after_id = decode_cursor(pagination.cursor)
            query = query.where(
                (self.model.created_at > after_at)
                | ((self.model.created_at == after_at) & (self.model.id > after_id))
            )
        rows = list(
            session.exec(
                query.order_by(self.model.created_at, self.model.id).limit(
                    pagination.limit + 1
                )
            ).all()
        )
        next_cursor: str | None = None
        if len(rows) > pagination.limit:
            rows = rows[: pagination.limit]
            last = rows[-1]
            next_cursor = encode_cursor(last.created_at, last.id)
        return rows, next_cursor, total

    def _after_write(self, session: Session, entity: ModelT, action: AuditAction) -> None:
        """Hook for in-transaction side effects, after the write is staged, before commit.

        Runs inside ``_save`` / ``_remove`` once the row and its audit record are
        staged but **before** the commit, so anything it does — emitting a domain
        event, writing a derived row — rides the **same** transaction and is atomic
        with the write (if it raises, the write is rolled back). The default is a
        no-op; a subclass overrides it (e.g. to ``emit`` a catalog event) and must
        not commit on its own.
        """

    def _authorize_object_write(self, entity: ModelT, action: AuditAction) -> None:
        """Fail closed unless the request actor may perform *action* on this exact row.

        The runtime half of the object-level authorization control (ADR 0029): for a
        write to an **existing** row, the request actor (from ``audit_actor_ctx``)
        must clear :func:`~terp.core.object_authz.apply_object_authz` — the built-in
        owner check (an :class:`~terp.core.OwnedMixin` row may be changed only by its
        ``owner_id``) plus every capability-registered predicate (team / ACL). A
        denied write raises :class:`~terp.core.PermissionDeniedError` (403) before any
        persistence is staged. A model with no ownership trait and no matching
        predicate is allowed, so this is inert for every model that never opted in.
        """
        if not apply_object_authz(type(entity), entity, audit_actor_ctx.get(), action):
            raise PermissionDeniedError()

    def _save(self, session: Session, entity: ModelT, action: AuditAction) -> ModelT:
        """Persist *entity*, emitting its audit record inside the same transaction.

        The single write chokepoint: ``create`` / ``update`` and any bespoke
        service method that mutates a row route through here so the audit trail is
        automatic and atomic with the business write (a sink that raises aborts the
        commit). Subclasses doing a custom mutation (e.g. soft-delete) call this
        instead of touching the session directly — the ``terp.arch``
        ``mutations_emit_audit`` rule enforces that. The commit is owned here and is
        **re-entrant** (ADR 0038): only the outermost write commits, so a nested
        ``_save`` (from an ``_after_write``) joins the same transaction rather than
        committing a second time — one write, one atomic, audited unit.

        Actor-stamping is auto-honored here too (ADR 0012): when the row's model
        composes :class:`~terp.core.ActorStampedMixin`, the request actor (from
        ``audit_actor_ctx``) is written to ``created_by_id`` once on insert and to
        ``modified_by_id`` on every save (a soft-delete records *who* deleted) — a
        module hand-writes no stamping code (the ``no_manual_actor_stamping`` rule
        forbids it).

        Object-level ownership is auto-honored too (ADR 0029): an
        :class:`~terp.core.OwnedMixin` row's ``owner_id`` is stamped to the actor once
        on insert (the creator owns it), and every **update / delete of an existing
        row** is authorized per-row — a non-owner write fails closed
        (:class:`~terp.core.PermissionDeniedError`) here, centrally, so a module
        hand-writes no ownership check (the ``no_manual_ownership_checks`` rule forbids
        it). The check is keyed off the *entity* (``isinstance``), so a bespoke
        ``_save`` of a non-mapped stand-in is unaffected.
        """
        if isinstance(entity, ActorStampedMixin):
            actor = audit_actor_ctx.get()
            if action is AuditAction.CREATED:
                entity.created_by_id = actor
            entity.modified_by_id = actor
        if isinstance(entity, OwnedMixin) and action is AuditAction.CREATED:
            entity.owner_id = audit_actor_ctx.get()
        if action is not AuditAction.CREATED:
            self._authorize_object_write(entity, action)
        with enter_write_unit() as outermost:
            try:
                session.add(entity)
                emit_audit(
                    session,
                    action=action,
                    target_type=type(entity).__name__,
                    target_id=str(entity.id),
                )
                with forbid_session_writes():
                    self._after_write(session, entity, action)
                if not outermost:
                    # A nested write joins the outermost unit of work: flush now so
                    # constraint errors map to the same uniform 409 path, but defer
                    # the single commit to the outermost _save (ADR 0038).
                    session.flush()
                    return entity
                session.commit()
            except IntegrityError as exc:
                # A unique / referential constraint violation becomes a uniform
                # 409 envelope instead of a leaked 500, whether it surfaces during
                # nested flush or outer commit; the raw detail rides log_context.
                if outermost:
                    session.rollback()
                raise ConflictError(
                    "This write conflicts with a unique or referential constraint.",
                    log_context={"integrity_error": str(exc)},
                ) from exc
            except ORMStaleDataError as exc:
                # A concurrent UPDATE/DELETE changed the row since it was read, so the
                # version_id_col match found zero rows on flush / commit. Map it to the
                # same uniform 409 the sequential pre-check raises (terp StaleDataError),
                # instead of leaking a generic 500 — the OCC contract holds under *true*
                # concurrency, not only the known-stale case (ADR 0006; BaseTable docstring).
                if outermost:
                    session.rollback()
                raise StaleDataError() from exc
            except Exception:
                if outermost:
                    session.rollback()
                raise
            session.refresh(entity)
        return entity

    def _remove(self, session: Session, entity: ModelT) -> None:
        """Hard-delete *entity*, emitting its ``DELETED`` audit record in the same transaction."""
        self._authorize_object_write(entity, AuditAction.DELETED)
        with enter_write_unit() as outermost:
            try:
                emit_audit(
                    session,
                    action=AuditAction.DELETED,
                    target_type=type(entity).__name__,
                    target_id=str(entity.id),
                )
                with forbid_session_writes():
                    self._after_write(session, entity, AuditAction.DELETED)
                session.delete(entity)
                if not outermost:
                    # Nested delete joins the outermost unit; flush now so
                    # constraint errors map to the same uniform 409 path, but defer
                    # the single commit to the outermost _save/_remove (ADR 0038).
                    session.flush()
                    return
                session.commit()
            except IntegrityError as exc:
                # A referential constraint (e.g. a row still referenced by an FK)
                # becomes a uniform 409 envelope instead of a leaked 500, whether it
                # surfaces during nested flush or outer commit; the raw detail rides
                # log_context.
                if outermost:
                    session.rollback()
                raise ConflictError(
                    "This delete conflicts with a referential constraint.",
                    log_context={"integrity_error": str(exc)},
                ) from exc
            except ORMStaleDataError as exc:
                # A concurrent UPDATE/DELETE changed the row since it was read, so the
                # version_id_col match found zero rows on flush / commit. Map it to the
                # same uniform 409 the sequential pre-check raises (terp StaleDataError),
                # instead of leaking a generic 500 (ADR 0006; BaseTable docstring).
                if outermost:
                    session.rollback()
                raise StaleDataError() from exc
            except Exception:
                if outermost:
                    session.rollback()
                raise

    @staticmethod
    def _without_managed_columns(data: dict[str, object]) -> dict[str, object]:
        """Drop framework-managed columns from an inbound payload (anti over-posting).

        ``BaseService`` assigns id / timestamps / version / scope / actor columns
        centrally, so stripping them here means even an over-wide ``*Create`` /
        ``*Update`` schema (which the ``input_schemas_exclude_managed_columns`` arch
        rule also forbids at build time) cannot mass-assign them -- a client cannot
        forge the primary key, defeat optimistic concurrency, or cross a tenant
        boundary through the request body.
        """
        return {key: value for key, value in data.items() if key not in _MANAGED_INPUT_COLUMNS}

    def create(self, session: Session, data: CreateT) -> ModelT:
        entity = self.model(**self._without_managed_columns(data.model_dump()))
        return self._save(session, entity, AuditAction.CREATED)

    def update(self, session: Session, entity_id: uuid.UUID, data: UpdateT) -> ModelT:
        entity = self.get(session, entity_id)
        # Authorize the per-row write *before* the concurrency check, so a caller who
        # may not write this row is refused (403) whatever version they sent -- never a
        # misleading 409. The audited chokepoint (_save) re-checks centrally, covering
        # every write path (create's stamp, delete, a bespoke _save); this is the early,
        # ordered check so authorization precedes concurrency (ADR 0029).
        self._authorize_object_write(entity, AuditAction.UPDATED)
        # Optimistic concurrency: reject a stale write; never assign the client version.
        if entity.version != data.version:
            raise StaleDataError()
        patch = self._without_managed_columns(data.model_dump(exclude_unset=True))
        for key, value in patch.items():
            setattr(entity, key, value)
        return self._save(session, entity, AuditAction.UPDATED)

    def delete(self, session: Session, entity_id: uuid.UUID) -> None:
        """Delete by id — a **soft** delete when the model is soft-deletable, else a hard one.

        Soft-delete is auto-honored from the model trait: a
        :class:`~terp.core.SoftDeleteMixin` row is stamped ``deleted_at`` and saved
        (so it vanishes from future reads but survives for audit/undo), routed
        through the same audited ``_save`` chokepoint; any other model is hard-deleted
        through ``_remove``. Either way the mutation is audited and the module writes
        no soft-delete code of its own.
        """
        entity = self.get(session, entity_id)
        if issubclass(self.model, SoftDeleteMixin):
            entity.deleted_at = _utc_now()  # type: ignore[attr-defined]
            self._save(session, entity, AuditAction.DELETED)
        else:
            self._remove(session, entity)


__all__ = ["BaseService"]
