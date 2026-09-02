"""Example-app permission model: the role ladder + the named permissions — declared once.

The ladder is the packaged one (``viewer < editor < admin``); what this app adds is a
single **named permission**, and the reason it exists at all is worth stating, because
until now this repository declared none and the fine-grained half of the authorization
model had no consumer anywhere in it.

``notes`` is an ordinary CRUD module: ``Policy.default()`` lets a VIEWER read and an
EDITOR write. That tier answers "may this person change notes?" — and for deletion it
answers the wrong question. Destroying a note is not the same decision as editing one,
and an app that cannot separate them has to choose between letting every editor delete
or letting nobody. So deletion is gated on :data:`NOTES_DELETE_PERMISSION` *in addition*
to the module's write tier: an editor may write, and may delete only if someone has said
so (``terp grant add <who> notes.delete``).

The ``min_role`` floor is EDITOR to match the module's write tier. A route-level
``require_permission`` checks only the grant, so the floor is not consulted on this
route — it is what makes ``terp grant`` warn when the permission is granted to a subject
who could not write a note anyway, which is a grant that would sit in the table and
never fire.
"""

from __future__ import annotations

from terp.core import EDITOR, LabelCoverage, Permission, PermissionModel

#: Deleting a note — the destructive half of ``notes``, separated from "may write".
NOTES_DELETE_PERMISSION = Permission(
    "notes.delete",
    min_role=EDITOR,
    label="Delete a note someone else wrote",
)

permission_model = PermissionModel(
    permissions=(NOTES_DELETE_PERMISSION,),
    # STRICT from the start, which this app can afford because it declares one permission
    # and that permission is labelled. The framework default is OFF for the reason ADR 0102
    # gives about its own coverage flip — turning it on before declarations carry labels
    # refuses the boot of every app that has any — but the app that has to demonstrate the
    # control is the wrong place to leave it off.
    label_coverage=LabelCoverage.STRICT,
)

__all__ = ["NOTES_DELETE_PERMISSION", "permission_model"]
