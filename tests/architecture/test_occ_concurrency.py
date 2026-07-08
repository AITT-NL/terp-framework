"""Regression gate (adversarial audit, 2026-06-30): a *concurrent* optimistic-concurrency
clash returns the uniform 409 the ``BaseTable`` docstring promises — not a leaked 500.

``BaseService.update()`` pre-checks the echoed ``version`` in Python, which catches the
**sequential** known-stale case (a fresh ``get`` already sees the newer row). Under **true**
concurrency two transactions both load the row *before* either commits, both pass that
pre-check, and the loser's commit trips SQLAlchemy's ``version_id_col`` guard
(``sqlalchemy.orm.exc.StaleDataError``) on flush / commit. The audited ``BaseService`` write
chokepoint now maps that to terp's :class:`~terp.core.errors.StaleDataError` (409
``stale_data``) instead of letting it escape as a generic 500 — for both the update
(``_save``) and the hard-delete (``_remove``) path. This is the build-time half of the fix;
the runtime half is the mapping in ``base_service``.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pytest
from sqlmodel import Field, Session, SQLModel, create_engine

from terp.core import BaseSchema, BaseService, BaseTable, BaseUpdateSchema
from terp.core.audit import AuditAction
from terp.core.errors import StaleDataError


class _OccDoc(BaseTable, table=True):
    __tablename__ = "_occ_doc"
    label: str = Field(max_length=50)


class _OccDocCreate(BaseSchema):
    label: str = Field(max_length=50)


class _OccDocUpdate(BaseUpdateSchema):
    label: str | None = Field(default=None, max_length=50)


class _OccDocService(BaseService[_OccDoc, _OccDocCreate, _OccDocUpdate]):
    model = _OccDoc


@pytest.fixture
def seeded(tmp_path: pathlib.Path) -> Iterator[tuple[object, object]]:
    """A file-backed SQLite engine (independent connections) seeded with one row (v1)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'occ.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as seed:
        doc_id = _OccDocService().create(seed, _OccDocCreate(label="seed")).id
    try:
        yield engine, doc_id
    finally:
        engine.dispose()


def test_concurrent_update_maps_to_409_not_500(seeded: tuple[object, object]) -> None:
    engine, doc_id = seeded
    svc = _OccDocService()
    session_a = Session(engine)  # type: ignore[arg-type]
    session_b = Session(engine)  # type: ignore[arg-type]
    try:
        # Both transactions load the row at version 1 *before* either commits.
        row_a = svc.get(session_a, doc_id)  # type: ignore[arg-type]
        row_b = svc.get(session_b, doc_id)  # type: ignore[arg-type]
        assert row_a.version == row_b.version == 1
        # A writes first and wins -> the row is now version 2.
        row_a.label = "from-A"
        svc._save(session_a, row_a, AuditAction.UPDATED)
        # B commits its stale (version-1) row: version_id_col matches zero rows. This used
        # to leak the unmapped sqlalchemy.orm.exc.StaleDataError (-> generic 500); it is now
        # the uniform 409 the sequential pre-check already produced.
        row_b.label = "from-B"
        with pytest.raises(StaleDataError) as exc:
            svc._save(session_b, row_b, AuditAction.UPDATED)
        assert exc.value.status_code == 409
        assert exc.value.code == "stale_data"
    finally:
        session_a.close()
        session_b.close()


def test_concurrent_hard_delete_maps_to_409_not_500(seeded: tuple[object, object]) -> None:
    engine, doc_id = seeded
    svc = _OccDocService()
    session_a = Session(engine)  # type: ignore[arg-type]
    session_b = Session(engine)  # type: ignore[arg-type]
    try:
        row_a = svc.get(session_a, doc_id)  # type: ignore[arg-type]
        row_b = svc.get(session_b, doc_id)  # type: ignore[arg-type]
        # A updates first -> version 2.
        row_a.label = "from-A"
        svc._save(session_a, row_a, AuditAction.UPDATED)
        # B hard-deletes its stale (version-1) row -> DELETE ... WHERE version = 1 matches
        # zero rows -> SQLAlchemy StaleDataError on the _remove path, now mapped to 409.
        with pytest.raises(StaleDataError) as exc:
            svc._remove(session_b, row_b)
        assert exc.value.status_code == 409
        assert exc.value.code == "stale_data"
    finally:
        session_a.close()
        session_b.close()
