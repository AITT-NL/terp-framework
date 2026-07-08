"""The example seed (``app.seed:seed``) — idempotent bootstrap of a usable admin + demo rows.

Proves seeding runs through the real audited services: a first administrator is provisioned,
the notes it creates are actor-stamped to that admin (so they are editable as the login
account), and the projects land in the admin's tenant (the one a real login binds). Re-running
creates no duplicates.
"""

from __future__ import annotations

from fastapi import FastAPI
from sqlmodel import Session, select

from terp.core import Roles

from terp.capabilities.identity import User

from app.auth import tenant_id_for_email
from app.modules.notes.models import Note
from app.modules.projects.models import Project
from app.seed import seed


def test_seed_bootstraps_a_usable_admin(app_db: FastAPI, db_session: Session) -> None:
    # app_db builds the app, which configures the event catalog + audit sink the seed relies on.
    summary = seed(db_session)

    assert "admin@acme.test" in summary
    admin = db_session.exec(select(User).where(User.email == "admin@acme.test")).first()
    assert admin is not None
    assert admin.role == int(Roles.ADMIN)


def test_seed_provisions_the_editor_and_viewer(app_db: FastAPI, db_session: Session) -> None:
    # The seed provisions the full role ladder so the frontend's write-gated controls can be seen
    # to appear for a writer (editor) and hide for a read-only user (viewer).
    summary = seed(db_session)

    assert "editor@acme.test" in summary
    assert "revocation-editor@acme.test" in summary
    assert "viewer@acme.test" in summary
    editor = db_session.exec(select(User).where(User.email == "editor@acme.test")).first()
    assert editor is not None
    assert editor.role == int(Roles.EDITOR)
    revocation_editor = db_session.exec(
        select(User).where(User.email == "revocation-editor@acme.test")
    ).first()
    assert revocation_editor is not None
    assert revocation_editor.role == int(Roles.EDITOR)
    viewer = db_session.exec(select(User).where(User.email == "viewer@acme.test")).first()
    assert viewer is not None
    assert viewer.role == int(Roles.VIEWER)


def test_seed_actor_stamps_content_to_the_admin(app_db: FastAPI, db_session: Session) -> None:
    seed(db_session)

    admin = db_session.exec(select(User).where(User.email == "admin@acme.test")).first()
    assert admin is not None
    notes = db_session.exec(select(Note)).all()
    assert notes  # a fresh database was seeded with a few notes
    assert all(note.created_by_id == admin.id for note in notes)


def test_seed_places_projects_in_the_admins_tenant(app_db: FastAPI, db_session: Session) -> None:
    seed(db_session)

    tenant = tenant_id_for_email("admin@acme.test")
    projects = db_session.exec(select(Project)).all()
    assert projects
    assert all(project.tenant_id == tenant for project in projects)


def test_seed_is_idempotent(app_db: FastAPI, db_session: Session) -> None:
    seed(db_session)
    first = len(db_session.exec(select(Note)).all())

    seed(db_session)  # a second run must not duplicate the demo rows
    assert len(db_session.exec(select(Note)).all()) == first
