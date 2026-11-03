"""Declared file references: ``FileRef`` + the fail-closed delegation check (ADR 0057).

A module that stores a pointer to a :class:`~terp.capabilities.files.File` (an invoice's
attachment, a report's export) must **declare** the reference — a bare
``file_id: uuid.UUID`` column carries no authorization semantics, and implicit "can see
the record ⇒ can see the file" propagation is exactly how object-level (BOLA) leaks
happen. The posture is **default-deny + explicit delegation**:

* :func:`FileRef` declares the column: it returns a normal indexed ``uuid`` field whose
  ``FieldInfo`` carries a machine-readable marker, making the reference greppable and
  verifiable at both build time (the ``no_raw_file_references`` rule flags a bare
  ``*file_id`` table column) and runtime (:func:`is_file_reference`).
* Delegated access is **serve-through**: the referencing module loads its *own* row
  through its *own* service (so that row's policy + row scope + per-row write gate
  already decided visibility), then serves the bytes with
  :meth:`~terp.capabilities.files.FileService.load_for` — which fail-closes on any
  column not declared with :func:`FileRef` (:class:`UndeclaredFileReferenceError`).
  Access to the file thus provably follows the referencing record's access, the raw
  ``/api/v1/files`` surface stays ADMIN-only, and delegation widens to exactly one
  already-authorized row — never by an implicit, registry-wide grant.
* Creating or changing that pointer requires the writer to see the target under
  its row scope and satisfy its object-write authorization. This is checked on
  every flush, within the assignment's transaction. Knowing a file UUID is not
  permission to delegate its contents. Existing references retain their delegation
  when someone edits an unrelated field or reads the authorized parent.

The kernel's predicate seams (scope / object-authz) compose with **AND** semantics — they
can only ever *narrow* access. That is deliberate, and it is why delegation is a
serve-through helper rather than a registered predicate: a predicate cannot (and must
never) silently *widen* who may reach a file.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, inspect as sa_inspect
from sqlmodel import Field, Session, SQLModel, select

from terp.core import AppError, AuditAction, PermissionDeniedError
from terp.core.audit import audit_actor_ctx
from terp.core.object_authz import apply_object_authz
from terp.core.scoping import apply_row_scope
from terp.capabilities.files.models import File

# The machine-readable marker a FileRef-declared column carries in its FieldInfo.
_FILE_REF_MARKER = "terp_file_ref"


class UndeclaredFileReferenceError(AppError):
    """500 — a serve-through read named a column not declared with ``FileRef``.

    Fail-closed: delegated file access flows only through a **declared** reference, so a
    typo'd column name or an undeclared bare ``uuid`` column refuses instead of serving
    bytes. This is a module wiring error (declare the column with :func:`FileRef`),
    never a caller mistake.
    """

    status_code = 500
    code = "file_reference_undeclared"
    default_message = "The record's file reference is not declared with FileRef."


def FileRef(*, index: bool = True) -> Any:  # noqa: N802 - a Field-style factory, named like the trait it declares
    """Declare a model column as a reference to a stored ``File``.

    Use it instead of a bare ``uuid`` field::

        class Invoice(BaseTable, table=True):
            attachment_file_id: uuid.UUID | None = FileRef()

    The column is a normal nullable, indexed ``uuid`` — no database FK is imposed (the
    ``File`` row may live in another package's migration history) — but its ``FieldInfo``
    carries the declaration marker :func:`is_file_reference` and
    :meth:`~terp.capabilities.files.FileService.load_for` verify, and the
    ``no_raw_file_references`` rule enforces at build time. New assignments are
    authorized against the target file during the same transaction; no database
    foreign key is required for that runtime check.
    """
    field = Field(default=None, index=index)
    field.json_schema_extra = {_FILE_REF_MARKER: True}
    return field


def is_file_reference(model: type[SQLModel], column: str) -> bool:
    """Whether *model*.*column* is declared as a file reference (via :func:`FileRef`)."""
    field = model.model_fields.get(column)
    if field is None:
        return False
    extra = field.json_schema_extra
    return isinstance(extra, dict) and bool(extra.get(_FILE_REF_MARKER))


def _authorize_file_bindings(session: Session, _flush_context: object) -> None:
    """A new delegation requires authority over its target in the same transaction.

    Inspect history after SQL is flushed but before commit, just like the kernel's
    reference-scope check. This also covers files inserted in the same unit. An
    unchanged delegation does not require its reader/editor to own the file anew.
    """
    for entity in (*session.new, *session.dirty):
        model = type(entity)
        state = sa_inspect(entity)
        for column in getattr(model, "model_fields", {}):
            if not is_file_reference(model, column):
                continue
            if entity not in session.new and not state.attrs[column].history.has_changes():
                continue
            file_id = getattr(entity, column)
            if file_id is None:
                continue
            # Selecting only the id checks scope without replacing an identity that
            # was inserted in this flush and has not entered the identity map yet.
            visible = session.scalars(apply_row_scope(
                File, select(File.id).where(File.id == file_id),
            )).first()
            target = next(
                (row for row in session.new if isinstance(row, File) and row.id == file_id),
                None,
            )
            if target is None and visible is not None:
                target = session.get(File, file_id)
            if visible is None or target is None or not apply_object_authz(
                File, target, audit_actor_ctx.get(), AuditAction.UPDATED,
            ):
                raise PermissionDeniedError(
                    log_context={"reason": "file_reference_not_authorized", "column": column},
                )


event.listen(Session, "after_flush", _authorize_file_bindings)


__all__ = ["FileRef", "UndeclaredFileReferenceError", "is_file_reference"]
