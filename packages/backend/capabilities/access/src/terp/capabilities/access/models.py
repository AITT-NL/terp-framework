"""The persisted access-grant table (RBAC permission grants).

A :class:`Grant` is a single, immutable fact: *subject ``subject_id`` holds the
named ``permission``*. Permissions are open, app-defined string tokens (e.g.
``"billing:write"``, ``"reports:export"``) — the capability hard-codes **no**
company module list. A composite unique constraint makes a grant idempotent: a
subject holds a given permission at most once.

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
