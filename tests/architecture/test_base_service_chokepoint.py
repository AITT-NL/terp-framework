"""BaseService chokepoint: a constraint violation on hard delete maps to 409 (M1).

``_save`` already turns a unique/referential ``IntegrityError`` into a uniform
``ConflictError`` (409); ``_remove`` (hard delete) now does the same, so deleting a
row still referenced by a foreign key no longer leaks a raw 500. A spy session
drives the failure path deterministically.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from terp.core.base_service import BaseService
from terp.core.errors import ConflictError


class _CommitFailsSession:
    """A stand-in session whose ``commit`` raises a referential ``IntegrityError``."""

    def __init__(self) -> None:
        self.rolled_back = False
        self.deleted: object | None = None

    def delete(self, entity: object) -> None:
        self.deleted = entity

    def commit(self) -> None:
        raise IntegrityError("DELETE", {}, Exception("row still referenced"))

    def rollback(self) -> None:
        self.rolled_back = True


class _Service(BaseService):  # type: ignore[type-arg]
    """Concrete BaseService; ``_remove`` does not touch ``model``."""


def test_hard_delete_constraint_violation_maps_to_conflict() -> None:
    session = _CommitFailsSession()
    entity = SimpleNamespace(id=uuid.uuid4())
    with pytest.raises(ConflictError):
        _Service()._remove(session, entity)  # type: ignore[arg-type]
    assert session.rolled_back is True
    assert session.deleted is entity
