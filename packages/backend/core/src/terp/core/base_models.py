"""Reusable SQLModel table mixins and Pydantic schema bases for Terp modules.

Every persisted model and DTO in a Terp module composes from these primitives
instead of redeclaring ``id`` / ``created_at`` / ``updated_at`` / ``version`` by
hand. This keeps schemas DRY, surfaces otherwise-invisible columns to coding
agents, and makes cross-cutting schema changes a one-line edit.

Public exports (re-exported from :mod:`terp.core`):

* :class:`UUIDPrimaryKeyMixin`, :class:`TimestampMixin`, :class:`SoftDeleteMixin`,
  :class:`ActorStampedMixin`, :class:`OwnedMixin`
* :class:`BaseTable` — UUID PK + timestamps + optimistic-concurrency ``version``
* :class:`BaseSchema` — DTO base (``from_attributes``)
* :class:`BaseUpdateSchema` — update DTO that requires the OCC ``version``

A deterministic Alembic naming convention is attached to the shared
``SQLModel.metadata`` at import time so constraint names are generated
identically across environments.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ConfigDict
from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import declared_attr
from sqlmodel import Field, SQLModel

_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _ensure_naming_convention() -> None:
    """Idempotently install the naming convention on the shared metadata."""
    metadata: MetaData = SQLModel.metadata
    if metadata.naming_convention != _NAMING_CONVENTION:
        metadata.naming_convention = _NAMING_CONVENTION


_ensure_naming_convention()


def _utc_now() -> datetime:
    """UTC ``now`` provider — kept private so tests can monkeypatch it."""
    return datetime.now(UTC)


class UUIDPrimaryKeyMixin(SQLModel):
    """Adds a UUID v4 primary key column called ``id``."""

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        nullable=False,
    )


class TimestampMixin(SQLModel):
    """Adds UTC ``created_at`` / ``updated_at`` columns.

    ``updated_at`` is refreshed automatically by SQLAlchemy on every UPDATE.
    """

    created_at: datetime | None = Field(  # type: ignore[call-overload]
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    updated_at: datetime | None = Field(  # type: ignore[call-overload]
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": _utc_now},
        nullable=False,
    )


class SoftDeleteMixin(SQLModel):
    """Adds a nullable ``deleted_at`` column for opt-in soft-delete semantics.

    Core installs **no** global filter: a naive query still returns deleted
    rows. The caller filters ``deleted_at IS NULL`` explicitly. (A soft-delete /
    tenancy capability may later add a session-level filter; the core stays
    free of that policy.)
    """

    deleted_at: datetime | None = Field(  # type: ignore[call-overload]
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class ActorStampedMixin(SQLModel):
    """Adds FK-less ``created_by_id`` / ``modified_by_id`` actor-stamp columns.

    An opt-in *provenance* trait (ADR 0012): a table that composes this records
    *who* created and last modified each row. :class:`~terp.core.BaseService`
    fills both **automatically** from the request-scoped actor (the same
    ``audit_actor_ctx`` the audit seam binds) — ``created_by_id`` once on insert,
    ``modified_by_id`` on every write (including a soft-delete) — so a module
    hand-writes **no** stamping code (the ``terp.arch`` ``no_manual_actor_stamping``
    rule forbids it; just like soft-delete is auto-honored, ADR 0010).

    The ids are deliberately **FK-less** UUIDs — like the audit record's
    ``actor_id`` and the access grant's ``subject_id`` — because the low core
    layer must not import a user table, and a principal may not even be a user (a
    service account, an external subject). They are **nullable**: a write outside
    a request (a worker, a migration, an unauthenticated path) leaves them
    ``None`` (best-effort). Requiring an actor is a future control-plane *how*
    knob (ADR 0011), not a column default — the trait owns only the *which*.
    """

    created_by_id: uuid.UUID | None = Field(default=None, nullable=True, index=True)
    modified_by_id: uuid.UUID | None = Field(default=None, nullable=True, index=True)


class OwnedMixin(SQLModel):
    """Adds an FK-less ``owner_id`` column that gates per-row writes (object-level authz).

    An opt-in *authorization* trait (ADR 0029): a table that composes this declares
    that each of its rows has an **owner**, and the framework answers the per-row
    write question the endpoint guard cannot — "may *this* principal edit *this*
    record?". :class:`~terp.core.BaseService` stamps ``owner_id`` to the request actor
    once **on create** (the creator owns what they create) and then **authorizes every
    update / delete of an existing row**: a non-owner write fails closed with
    :class:`~terp.core.PermissionDeniedError` (403), centrally, so a module writes
    **no** ownership-check code (the ``terp.arch`` ``no_manual_ownership_checks`` rule
    forbids it). Richer policies (team membership, a shared-with ACL) plug into the
    same gate through :func:`~terp.core.register_object_authz_predicate` without the
    kernel importing them.

    Relationship to :class:`ActorStampedMixin`. The owner *defaults* to the creator:
    it is stamped from the same request-scoped actor (``audit_actor_ctx``) that fills
    ``created_by_id``, but is a **distinct** column from that immutable provenance
    record. Compose both traits when you want *who created it* (audit provenance)
    **and** *who may change it* (authorization) tracked independently; compose only
    :class:`OwnedMixin` when you need just the write gate. Note ``owner_id`` is a
    framework-managed column (stripped from request bodies, like the scope / actor
    columns) and the built-in gate authorizes only the row's *current* owner — so
    reassigning ownership (a hand-off, an admin re-owner) is **not** a built-in: it
    needs an explicit, audited reassignment seam the app provides, and an admin
    override of a still-owned or orphaned row is an elevated capability (a registered
    predicate can only *narrow* the owner check, never widen it), not a default.

    Read **visibility** is a separate, complementary concern: this trait gates *writes*
    only (a boolean on the loaded row cannot scale to a paginated list). To also hide
    other owners' rows from reads, register a row-scope predicate
    (:func:`~terp.core.register_scope_predicate`, ADR 0017) keyed on ``owner_id`` — the
    two seams compose into "only the owner sees **or** changes the row".

    The id is deliberately **FK-less** (like ``created_by_id`` / the audit record's
    ``actor_id``) — the low core layer must not import a user table and a principal may
    not be a user — and **nullable**: a write outside a request (a worker, a migration)
    leaves it ``None`` (best-effort), and an unowned row is not write-restricted (there
    is no owner to protect). Requiring an owner is a future control-plane *how* knob
    (ADR 0011), not a column default.
    """

    owner_id: uuid.UUID | None = Field(default=None, nullable=True, index=True)


class BaseTable(UUIDPrimaryKeyMixin, TimestampMixin, SQLModel):
    """Standard base for every persisted table.

    Subclasses declare ``table=True`` themselves and must **not** redeclare
    ``id``, ``created_at``, ``updated_at`` or ``version``::

        class Invoice(BaseTable, table=True):
            number: str = Field(max_length=50, index=True, unique=True)

    Optimistic concurrency control
    ------------------------------
    ``version`` is registered as SQLAlchemy's ``version_id_col``. Every ORM
    UPDATE appends ``AND version = <loaded>`` and increments the column; a
    losing concurrent write matches zero rows and raises
    :class:`sqlalchemy.orm.exc.StaleDataError`. The audited ``BaseService`` write
    chokepoint maps that to a uniform HTTP 409 (``terp.core.errors.StaleDataError``),
    so a *concurrent* clash returns the same 409 as the sequential staleness check.
    """

    version: int = Field(
        default=1,
        nullable=False,
        description=(
            "Optimistic concurrency token. Increments on every UPDATE; clients "
            "echo the value from the last read response in their update payload."
        ),
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805
        # Resolves against each concrete subclass' own ``__table__``.
        return {"version_id_col": cls.__table__.c.version}  # type: ignore[attr-defined]


class BaseSchema(SQLModel):
    """Base for non-table DTOs (request bodies and response models)."""

    model_config = ConfigDict(  # type: ignore[assignment]
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class BaseUpdateSchema(BaseSchema):
    """Base for every ``*Update`` DTO that targets a :class:`BaseTable` row.

    Requires the client to echo the OCC ``version`` from the most recent read.
    The value drives the staleness check and is **never** assigned to the ORM
    row (doing so breaks ``version_id_col`` tracking).

    Unknown fields are rejected (``extra="forbid"``): partial updates apply
    only the fields the client *set* (``exclude_unset``), so a mistyped field
    name would otherwise validate cleanly and silently no-op. Rejecting it
    with a 422 turns that silent data-loss bug into an immediate client error.
    """

    model_config = ConfigDict(  # type: ignore[assignment]
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
    )

    version: int = Field(
        description=(
            "Version from the most recent read response, used for optimistic "
            "concurrency control. A stale value is rejected with HTTP 409."
        ),
    )


__all__ = [
    "ActorStampedMixin",
    "BaseSchema",
    "BaseTable",
    "BaseUpdateSchema",
    "OwnedMixin",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
