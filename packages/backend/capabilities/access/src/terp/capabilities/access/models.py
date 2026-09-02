"""The persisted access-grant table (RBAC permission grants).

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
