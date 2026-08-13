"""Two guarantees for code that *reports* instead of aborting.

A validator, an import pre-flight, a dry run: each answers "what is wrong with
this?" and owes the caller every reason at once, not the first one. Terp used to
make both halves of that awkward.

**Resolving a reference without raising.** ``BaseService.get`` raises, so
"does this id resolve for this caller?" was spelled as exception control flow,
re-implemented in every service that composes a sibling. ``find`` returns the
row or ``None`` through the *same* ``base_query``, so absence is data without
becoming a hole in the row scope.

**Reporting more than one reason.** The error envelope carried a single
``code`` and one English ``detail``, so a check that found three problems
flattened three stable codes and three document paths into prose and a UI could
only substring-match them. ``ErrorDetail`` carries them beside the message.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlmodel import Field, Session, SQLModel, create_engine, select

from terp.core import BaseSchema, BaseService, BaseTable, BaseUpdateSchema
from terp.core.errors import (
    AppError,
    ErrorDetail,
    NotFoundError,
    ValidationFailedError,
    build_error_envelope,
)


class _Note(BaseTable, table=True):
    __tablename__ = "reporting_ergonomics_note"

    label: str = Field(max_length=50)
    archived: bool = Field(default=False)


class _NoteCreate(BaseSchema):
    label: str
    archived: bool = False


class _NoteUpdate(BaseUpdateSchema):
    label: str | None = None


class _NoteService(BaseService[_Note, _NoteCreate, _NoteUpdate]):
    model = _Note


class _VisibleNoteService(_NoteService):
    """A service whose rows are scoped — the case ``find`` must not widen."""

    def base_query(self):  # type: ignore[no-untyped-def]
        return select(_Note).where(_Note.archived == False)  # noqa: E712


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as active:
        yield active
    engine.dispose()


def test_find_returns_the_row(session: Session) -> None:
    service = _NoteService()
    row = service.create(session, _NoteCreate(label="ledger"))
    assert service.find(session, row.id) is not None


def test_find_returns_none_instead_of_raising(session: Session) -> None:
    """The whole point: absence is a value, so a caller can keep collecting."""
    assert _NoteService().find(session, uuid.uuid4()) is None


def test_get_still_raises_for_the_same_absence(session: Session) -> None:
    with pytest.raises(NotFoundError):
        _NoteService().get(session, uuid.uuid4())


def test_find_honours_the_row_scope(session: Session) -> None:
    """``find`` must be ``get`` minus the exception — never minus the scope."""
    hidden = _NoteService().create(session, _NoteCreate(label="old", archived=True))
    scoped = _VisibleNoteService()
    assert scoped.find(session, hidden.id) is None
    with pytest.raises(NotFoundError):
        scoped.get(session, hidden.id)


def test_envelope_is_unchanged_without_details() -> None:
    """Additive: an ordinary error still renders exactly the three documented keys."""
    envelope = build_error_envelope(AppError("nope"), request_id="req-1")
    assert set(envelope) == {"code", "detail", "request_id"}


def test_envelope_carries_structured_details() -> None:
    error = ValidationFailedError(
        "This draft cannot be published.",
        details=[
            ErrorDetail(
                code="destination_fields_exist",
                loc="entity_mappings[0].columns[0].destination",
                msg="is 'kode', which is not a column of fast.finance.ledgers.",
            ),
            ErrorDetail(code="depends_on_acyclic", loc="entity_mappings[1]"),
        ],
    )
    envelope = build_error_envelope(error, request_id="req-2")

    assert envelope["code"] == "validation_failed"
    assert [detail["code"] for detail in envelope["details"]] == [
        "destination_fields_exist",
        "depends_on_acyclic",
    ]
    assert envelope["details"][0]["loc"] == "entity_mappings[0].columns[0].destination"
    # A reason may be about the document as a whole rather than one field.
    assert envelope["details"][1]["msg"] == ""


def test_details_default_to_empty() -> None:
    assert AppError("nope").details == ()
