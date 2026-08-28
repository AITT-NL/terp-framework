"""Example-app operation catalog: what every route does — declared once (ADR 0102).

Mirrors the event and job catalogs: this app's own domain modules (notes, tasks,
journals, projects) declare their operations here, in one place, the same way
their authority lives in ``control_plane/permissions.py`` rather than scattered
per module. A capability's own operations are declared *inside* the capability
package (it cannot reach into this app's control plane) and re-exported from its
public ``__init__.py``; this file imports every capability actually mounted by
:mod:`app.main` and folds its operations into the one catalog below, so
``ControlPlane.operations`` is the single source of truth for every route this
app serves, hand-written or capability-supplied alike.
"""

from __future__ import annotations

from terp.core import OperationCatalog, OperationDefinition

from terp.capabilities.access import (
    ACCESS_CREATE_GRANT,
    ACCESS_DELETE_GRANT,
    ACCESS_LIST_GRANTS,
)
from terp.capabilities.audit import AUDIT_LIST_EVENTS
from terp.capabilities.auth import (
    AUTH_LOGIN,
    AUTH_LOGOUT,
    AUTH_ME,
    AUTH_REFRESH,
    AUTH_TOKEN,
)
from terp.capabilities.files import (
    FILES_DELETE,
    FILES_DOWNLOAD,
    FILES_GET,
    FILES_LIST,
    FILES_UPDATE,
    FILES_UPLOAD,
)
from terp.capabilities.groups import (
    GROUPS_ADD_MEMBER,
    GROUPS_CREATE,
    GROUPS_DELETE,
    GROUPS_GET,
    GROUPS_LIST,
    GROUPS_LIST_MEMBERS,
    GROUPS_REMOVE_MEMBER,
    GROUPS_UPDATE,
)
from terp.capabilities.oidc import OIDC_AUTHORIZE, OIDC_CALLBACK
from terp.capabilities.realtime import REALTIME_MINT_TICKET, REALTIME_SUBSCRIBE_SSE
from terp.capabilities.users import (
    USERS_DEACTIVATE,
    USERS_GET,
    USERS_LIST,
    USERS_PROVISION,
    USERS_REACTIVATE,
    USERS_RESET_PASSWORD,
    USERS_UPDATE,
)
from terp.capabilities.webhooks import (
    WEBHOOKS_CREATE_SUBSCRIPTION,
    WEBHOOKS_DELETE_SUBSCRIPTION,
    WEBHOOKS_GET_SUBSCRIPTION,
    WEBHOOKS_LIST_DELIVERIES,
    WEBHOOKS_LIST_SUBSCRIPTIONS,
    WEBHOOKS_UPDATE_SUBSCRIPTION,
)

# notes
NOTES_LIST = OperationDefinition(id="notes.list_notes", label="List every note")
NOTES_CREATE = OperationDefinition(id="notes.create_note", label="Write a new note")
NOTES_GET = OperationDefinition(id="notes.get_note", label="View a note")
NOTES_UPDATE = OperationDefinition(id="notes.update_note", label="Edit a note")
NOTES_DELETE = OperationDefinition(id="notes.delete_note", label="Delete a note")

# tasks
TASKS_LIST = OperationDefinition(id="tasks.list_tasks", label="List every task")
TASKS_CREATE = OperationDefinition(id="tasks.create_task", label="Add a new task")
TASKS_GET = OperationDefinition(id="tasks.get_task", label="View a task")
TASKS_UPDATE = OperationDefinition(id="tasks.update_task", label="Edit a task")
TASKS_DELETE = OperationDefinition(id="tasks.delete_task", label="Delete a task")

# journals
JOURNALS_LIST = OperationDefinition(
    id="journals.list_journals", label="List every journal entry you can see"
)
JOURNALS_CREATE = OperationDefinition(
    id="journals.create_journal", label="Write a new journal entry"
)
JOURNALS_GET = OperationDefinition(id="journals.get_journal", label="View a journal entry")
JOURNALS_UPDATE = OperationDefinition(
    id="journals.update_journal", label="Edit a journal entry"
)
JOURNALS_DELETE = OperationDefinition(
    id="journals.delete_journal", label="Delete a journal entry"
)

# projects (build_crud_router — the factory's own route names, ADR 0102 §7)
PROJECTS_LIST = OperationDefinition(id="projects.list_projects", label="List every project")
PROJECTS_CREATE = OperationDefinition(id="projects.create_project", label="Start a new project")
PROJECTS_GET = OperationDefinition(id="projects.get_project", label="View a project")
PROJECTS_UPDATE = OperationDefinition(id="projects.update_project", label="Edit a project")
PROJECTS_DELETE = OperationDefinition(id="projects.delete_project", label="Delete a project")

operation_catalog = OperationCatalog(
    operations=(
        NOTES_LIST,
        NOTES_CREATE,
        NOTES_GET,
        NOTES_UPDATE,
        NOTES_DELETE,
        TASKS_LIST,
        TASKS_CREATE,
        TASKS_GET,
        TASKS_UPDATE,
        TASKS_DELETE,
        JOURNALS_LIST,
        JOURNALS_CREATE,
        JOURNALS_GET,
        JOURNALS_UPDATE,
        JOURNALS_DELETE,
        PROJECTS_LIST,
        PROJECTS_CREATE,
        PROJECTS_GET,
        PROJECTS_UPDATE,
        PROJECTS_DELETE,
        ACCESS_LIST_GRANTS,
        ACCESS_CREATE_GRANT,
        ACCESS_DELETE_GRANT,
        AUDIT_LIST_EVENTS,
        AUTH_LOGIN,
        AUTH_TOKEN,
        AUTH_REFRESH,
        AUTH_LOGOUT,
        AUTH_ME,
        FILES_UPLOAD,
        FILES_LIST,
        FILES_GET,
        FILES_DOWNLOAD,
        FILES_UPDATE,
        FILES_DELETE,
        GROUPS_LIST,
        GROUPS_CREATE,
        GROUPS_GET,
        GROUPS_UPDATE,
        GROUPS_DELETE,
        GROUPS_LIST_MEMBERS,
        GROUPS_ADD_MEMBER,
        GROUPS_REMOVE_MEMBER,
        OIDC_AUTHORIZE,
        OIDC_CALLBACK,
        REALTIME_MINT_TICKET,
        REALTIME_SUBSCRIBE_SSE,
        USERS_LIST,
        USERS_PROVISION,
        USERS_GET,
        USERS_UPDATE,
        USERS_DEACTIVATE,
        USERS_REACTIVATE,
        USERS_RESET_PASSWORD,
        WEBHOOKS_LIST_SUBSCRIPTIONS,
        WEBHOOKS_CREATE_SUBSCRIPTION,
        WEBHOOKS_GET_SUBSCRIPTION,
        WEBHOOKS_UPDATE_SUBSCRIPTION,
        WEBHOOKS_DELETE_SUBSCRIPTION,
        WEBHOOKS_LIST_DELIVERIES,
    )
)

__all__ = [
    "JOURNALS_CREATE",
    "JOURNALS_DELETE",
    "JOURNALS_GET",
    "JOURNALS_LIST",
    "JOURNALS_UPDATE",
    "NOTES_CREATE",
    "NOTES_DELETE",
    "NOTES_GET",
    "NOTES_LIST",
    "NOTES_UPDATE",
    "PROJECTS_CREATE",
    "PROJECTS_DELETE",
    "PROJECTS_GET",
    "PROJECTS_LIST",
    "PROJECTS_UPDATE",
    "TASKS_CREATE",
    "TASKS_DELETE",
    "TASKS_GET",
    "TASKS_LIST",
    "TASKS_UPDATE",
    "operation_catalog",
]

# `leases` and `sync` are deliberately absent. Their operations used to be folded
# in on the reasoning that a superset costs nothing under OFF coverage — true of
# the CATALOG, and false of the IMPORT that fills it. Neither capability is
# installed in the production image, so the import raised ModuleNotFoundError
# before the app could serve a single request, and the container never became
# healthy. It ran fine in the workspace, where every package is installed.
#
# So this file lists what this app MOUNTS, and nothing else. Wiring one of them in
# means adding it here too, which is the moment you would be looking anyway.
