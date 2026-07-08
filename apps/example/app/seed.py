"""Idempotent demo seed for the example app — ``terp seed`` runs :func:`seed`.

Provisions a first administrator (plus an editor) and a handful of representative rows
*through the real audited services*, so seeding itself exercises the guarantees it
demonstrates: every write lands an audit record, notes and tasks are actor-stamped, the
journal is owner-stamped, and the projects are tenant-scoped. It is idempotent — re-running
creates no duplicates — so a container may safely seed on every boot.

Dev / demo only: ``terp seed`` refuses to run when ``ENVIRONMENT=production`` (a real
deployment bootstraps its first admin with ``terp user create`` instead), so the demo
credentials below never reach a production store.
"""

from __future__ import annotations

from sqlmodel import Session, select

from terp.core import BaseTable, Roles, bind_audit_actor

from terp.capabilities.tenancy import tenant_context
from terp.capabilities.users import UserProvision, UsersService

from app.auth import tenant_id_for_email
from app.modules.journals.models import Journal
from app.modules.journals.schemas import JournalCreate
from app.modules.journals.service import JournalService
from app.modules.notes.models import Note
from app.modules.notes.schemas import NoteCreate
from app.modules.notes.service import NoteService
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate
from app.modules.projects.service import ProjectService
from app.modules.tasks.models import Task
from app.modules.tasks.schemas import TaskCreate
from app.modules.tasks.service import TaskService

# Dev-only demo credentials — meaningless outside a throwaway workbench database (`terp seed`
# refuses to run in production). The password satisfies the default PasswordPolicy.
_ADMIN_EMAIL = "admin@acme.test"
_EDITOR_EMAIL = "editor@acme.test"
_REVOCATION_EDITOR_EMAIL = "revocation-editor@acme.test"
_VIEWER_EMAIL = "viewer@acme.test"
_DEMO_PASSWORD = "correct horse battery staple"  # noqa: S105 - dev seed, not a real secret


def _has_any(session: Session, model: type[BaseTable]) -> bool:
    """True when *model* already has at least one row (for idempotent seeding)."""
    return session.exec(select(model).limit(1)).first() is not None


def seed(session: Session) -> str:
    """Populate a fresh database with a usable admin and a little demo content (idempotent)."""
    users = UsersService()
    admin = users.ensure_user(
        session, UserProvision(email=_ADMIN_EMAIL, password=_DEMO_PASSWORD, role=int(Roles.ADMIN))
    )
    users.ensure_user(
        session, UserProvision(email=_EDITOR_EMAIL, password=_DEMO_PASSWORD, role=int(Roles.EDITOR))
    )
    # A second editor lets revocation-sensitive e2e tests invalidate every token for one subject
    # without racing other parallel tests that sign in as the normal seeded editor.
    users.ensure_user(
        session,
        UserProvision(
            email=_REVOCATION_EDITOR_EMAIL,
            password=_DEMO_PASSWORD,
            role=int(Roles.EDITOR),
        ),
    )
    # A read-only user, so the frontend's write-gated controls (Authorized action="write") can be
    # seen to hide for a viewer while notes stay readable — UI RBAC honouring the backend roles.
    users.ensure_user(
        session, UserProvision(email=_VIEWER_EMAIL, password=_DEMO_PASSWORD, role=int(Roles.VIEWER))
    )

    # Actor- / owner-stamped content is created *as the admin*, so the seeded rows are owned
    # by (and editable as) the account you sign in with.
    with bind_audit_actor(admin.id):
        if not _has_any(session, Note):
            notes = NoteService()
            notes.create(session, NoteCreate(title="Welcome to Terp", body="Your first note."))
            notes.create(session, NoteCreate(title="Try editing me", body="Every write is audited."))
        if not _has_any(session, Task):
            tasks = TaskService()
            tasks.create(session, TaskCreate(title="Explore the audit log"))
            tasks.create(session, TaskCreate(title="Ship something", status="open"))
        if not _has_any(session, Journal):
            JournalService().create(
                session, JournalCreate(title="Day one", entry="This journal is owned by the admin.")
            )

    # Projects are tenant-scoped; create them under the admin's tenant (the same tenant a real
    # login for admin@acme.test binds), so they are visible after you sign in.
    with bind_audit_actor(admin.id), tenant_context(tenant_id_for_email(_ADMIN_EMAIL)):
        if not _has_any(session, Project):
            projects = ProjectService()
            projects.create(session, ProjectCreate(name="Acme launch"))
            projects.create(session, ProjectCreate(name="Internal tooling"))

    return f"seeded users ({_ADMIN_EMAIL}, {_EDITOR_EMAIL}, {_REVOCATION_EDITOR_EMAIL}, {_VIEWER_EMAIL}) + demo notes / tasks / journal / projects"
