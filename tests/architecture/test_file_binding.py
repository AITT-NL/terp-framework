"""A declared file reference delegates access only after its assignment is authorized."""
from __future__ import annotations

import uuid

import pytest
from sqlmodel import Field, Session, select

from terp.core import (
    BaseSchema, BaseService, BaseTable, BaseUpdateSchema, OwnedMixin, PermissionDeniedError,
)
from terp.core.audit import bind_audit_actor
from terp.core._internal.session_guard import enter_write_unit
from terp.core.scoping import register_scope_predicate
from terp.capabilities.files import File, FileRef, FileService

from .test_files import _CONTENT, _store, session as session, storage_root as storage_root
from .test_scope_predicate_registry import isolated_registry as isolated_registry


class _AttachmentParent(BaseTable, OwnedMixin, table=True):
    __tablename__ = "binding_test_parent"
    attachment_file_id: uuid.UUID | None = FileRef()
    label: str = Field(max_length=50)


class _Create(BaseSchema):
    attachment_file_id: uuid.UUID | None = None
    label: str = Field(default="parent", max_length=50)


class _Update(BaseUpdateSchema):
    attachment_file_id: uuid.UUID | None = None
    label: str | None = Field(default=None, max_length=50)


class _Parents(BaseService[_AttachmentParent, _Create, _Update]):
    model = _AttachmentParent


def test_knowing_a_file_uuid_does_not_authorize_creating_a_delegation(
    session: Session, storage_root,
) -> None:
    owner, caller = uuid.uuid4(), uuid.uuid4()
    with bind_audit_actor(owner):
        file_id = _store(FileService(), session).id
    with bind_audit_actor(caller):
        with pytest.raises(PermissionDeniedError):
            _Parents().create(session, _Create(attachment_file_id=file_id))
        _Parents().create(session, _Create(label="authorized later write"))
    rows = session.exec(select(_AttachmentParent)).all()
    assert len(rows) == 1
    assert rows[0].attachment_file_id is None


def test_rejected_reassignment_cannot_commit_with_a_later_allowed_write(
    session: Session, storage_root,
) -> None:
    owner, caller = uuid.uuid4(), uuid.uuid4()
    with bind_audit_actor(owner):
        forbidden = _store(FileService(), session).id
    with bind_audit_actor(caller):
        allowed = _store(FileService(), session).id
        parent = _Parents().create(session, _Create(attachment_file_id=allowed))
        parent_id = parent.id
        with pytest.raises(PermissionDeniedError):
            _Parents().update(session, parent_id, _Update(
                version=parent.version, attachment_file_id=forbidden,
            ))
        current = _Parents().get(session, parent_id)
        _Parents().update(session, parent_id, _Update(version=current.version, label="changed"))
    session.expire_all()
    saved = _Parents().get(session, parent_id)
    assert saved.attachment_file_id == allowed
    assert saved.label == "changed"


def test_an_authorized_delegation_does_not_require_the_reader_to_own_the_file(
    session: Session, storage_root,
) -> None:
    with bind_audit_actor(uuid.uuid4()):
        file_id = _store(FileService(), session).id
        parent = _Parents().create(session, _Create(attachment_file_id=file_id))
    # The caller's parent authorization is the established serve-through contract.
    with bind_audit_actor(uuid.uuid4()):
        loaded, content = FileService().load_for(session, parent, "attachment_file_id")
    assert loaded.id == file_id
    assert content == _CONTENT


@pytest.mark.parametrize("target", ["missing", "out_of_scope"])
def test_a_new_binding_requires_a_visible_existing_target(
    session: Session, storage_root, target: str, isolated_registry,
) -> None:
    with bind_audit_actor(uuid.uuid4()):
        file_id = _store(FileService(), session).id if target == "out_of_scope" else uuid.uuid4()
        if target == "out_of_scope":
            register_scope_predicate(
                lambda model, query: query.where(False) if model is File else query,
            )
        with pytest.raises(PermissionDeniedError):
            _Parents().create(session, _Create(attachment_file_id=file_id))


def test_a_target_inserted_in_the_same_flush_can_be_bound(session: Session) -> None:
    actor = uuid.uuid4()
    file = File(
        owner_id=actor, filename="new.txt", content_type="text/plain", size=1,
        sha256="0" * 64, storage_key="synthetic-key", storage_profile="default",
    )
    parent = _AttachmentParent(label="new", owner_id=actor, attachment_file_id=file.id)
    # A trusted aggregate write can flush both rows together, before either enters
    # the identity map. This does not require reading a second copy of the file row.
    with bind_audit_actor(actor), enter_write_unit():
        session.add(file)
        session.add(parent)
        session.commit()
    assert session.get(_AttachmentParent, parent.id).attachment_file_id == file.id
