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

The kernel's predicate seams (scope / object-authz) compose with **AND** semantics — they
can only ever *narrow* access. That is deliberate, and it is why delegation is a
serve-through helper rather than a registered predicate: a predicate cannot (and must
never) silently *widen* who may reach a file.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Field, SQLModel

from terp.core import AppError

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
    ``no_raw_file_references`` rule enforces at build time.
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


__all__ = ["FileRef", "UndeclaredFileReferenceError", "is_file_reference"]
