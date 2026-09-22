"""The persisted access tables: permission grants, and per-module role assignments.

A :class:`Grant` is a single, immutable fact: *subject ``subject_id`` holds the
named ``permission``*. Permissions are open, app-defined tokens (e.g.
``"billing.write"``, ``"reports.export"``) — the capability hard-codes **no**
company module list. A composite unique constraint makes a grant idempotent: a
subject holds a given permission at most once.

The name is **dotted**, because that is the one shape a permission name can have:
:class:`terp.core.Permission` validates it (a colon form raises), so a grant of a
colon-separated name could never be the permission an app declares in its control
plane, and could therefore never be offered by ``terp grant`` or referenced from a
``Policy``. The column itself stays a plain string on purpose — a permission the app
has since stopped declaring is exactly the stale grant an operator most needs to
list and revoke, so the *shape* is a convention the declared vocabulary enforces
rather than a constraint this table imposes.

``subject_id`` is an FK-less UUID on purpose: this low-layer capability must not
import the higher-layer user table it references, so it stays a leaf the identity
and app modules can depend on (never the reverse).
"""

from __future__ import annotations

import uuid

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from terp.core import BaseTable


class Grant(BaseTable, table=True):
    __tablename__ = "access_grant"
    __table_args__ = (
        UniqueConstraint(
            "subject_id", "permission", name="uq_access_grant_subject_permission"
        ),
    )

    subject_id: uuid.UUID = Field(index=True)
    permission: str = Field(max_length=128, index=True)


class ModuleRole(BaseTable, table=True):
    """A single fact: *subject ``subject_id`` holds rank ``role_rank`` in module ``module``*.

    The row that makes "editor in one module, viewer everywhere else" expressible. Before it,
    a user carried exactly one rank and a group carried none, so the only way to grant write
    access in one module was to raise the rank everywhere — the ten-second workaround ADR 0089
    was written about, one level up (ADR 0121).

    ``subject_id`` is an FK-less UUID for exactly the reason :class:`Grant`'s is, and it buys
    the same thing: a group's id is a subject, so a per-module role for a whole group needs no
    new machinery at all — the existing subject-expansion seam already maps a user to the
    groups they belong to.

    **Additive only.** The effective rank in a module is ``max`` of the caller's global rank
    and every module role over the expanded subject set. There is no per-module *deny*, ever:
    a system where authority can be subtracted somewhere is one where no pane can honestly
    answer "why can this person do that?", and being able to answer that is the only defence
    an administrator has against an over-broad grant.

    ``role_rank`` is stored rather than the role's name because rank is what the guard
    compares, and a name would need resolving against a ladder that may have changed since.
    The writer validates the rank against the app's declared ladder, so a row can only ever
    name a rung the app declared *at the time* — and a rung the app later drops leaves a
    stale row, which is shown rather than hidden, on the same reasoning ``terp grant list``
    gives for a stale grant.
    """

    __tablename__ = "access_module_role"
    __table_args__ = (
        UniqueConstraint(
            "subject_id", "module", name="uq_access_module_role_subject_module"
        ),
    )

    subject_id: uuid.UUID = Field(index=True)
    module: str = Field(max_length=64, index=True)
    role_rank: int = Field(index=True)
