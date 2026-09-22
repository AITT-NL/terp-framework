"""``terp module-role`` — assign, list and revoke a subject's rung inside one module.

The first writer for per-module authority, and an operator command before a UI on purpose
(ADR 0089's pattern): the seam that has to exist for a fresh deployment, where nobody has an
admin session yet, is the one that runs next to the database rather than through it. The pane
comes later and writes the same rows.

Every refusal here comes from the capability's own ``validate_assignment``, so the command and
any HTTP surface refuse identically. That was the defect the grants endpoint had for its whole
life — the CLI refused a typo and the endpoint stored it — and repeating it in a second table
would be a poor use of having just fixed it.
"""

from __future__ import annotations

import contextlib
import pathlib

from fastapi import FastAPI

from terp.cli._subjects import load_app_for_cli, resolve_subject
from terp.core.db import get_session


def _declarations(app: FastAPI) -> tuple[object, tuple[object, ...]]:
    """The composed app's control plane and mounted specs — what a refusal is measured against.

    Read off ``app.state`` rather than re-imported, for the reason ``terp grant`` gives about
    its own catalog: the command must only ever offer what *this* app really enforces.
    """
    plane = getattr(getattr(app, "state", None), "terp_control_plane", None)
    specs = getattr(getattr(app, "state", None), "terp_module_specs", None)
    if plane is None or specs is None:
        raise SystemExit(
            "the app exposes no control plane (create_app records it on app.state) — "
            "pass a terp app factory, e.g. --app app.main:build"
        )
    return plane, tuple(specs)


def _resolve_rank(plane: object, role: str) -> int:
    """Resolve a role *name* to its rank, or fail listing the app's ladder.

    Operators think in names, not ranks — the whole reason ADR 0089 stopped making people
    supply a UUID. And the error is the feature: "unknown role" alone sends the reader back to
    the source, which is the moment they reach for a broader tier instead.
    """
    ladder = {r.name: r.rank for r in plane.permissions.roles}  # type: ignore[attr-defined]
    if role in ladder:
        return ladder[role]
    known = "\n".join(
        f"  {name}  (rank {rank})" for name, rank in sorted(ladder.items(), key=lambda i: i[1])
    )
    raise SystemExit(
        f"unknown role {role!r}. This app declares:\n{known}\n\n"
        "A module role at a rank the app does not declare could not be compared against any "
        "policy, so it is refused rather than stored."
    )


def module_role_add_command(
    subject: str,
    module: str,
    role: str,
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
) -> str:
    """Assign *role* to *subject* inside *module* — validated, audited, idempotent."""
    from terp.capabilities.access import ModuleRoleService, validate_assignment
    from terp.core import AppError

    app = load_app_for_cli(app_ref, app_root)
    plane, specs = _declarations(app)
    rank = _resolve_rank(plane, role)
    try:
        validate_assignment(plane, specs, module, rank)
    except AppError as exc:
        # The capability raises the app-level error an HTTP caller would get; at a terminal
        # that is a refusal with a message, not a traceback.
        raise SystemExit(str(exc)) from exc

    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        subject_id, label = resolve_subject(session, subject)
        try:
            ModuleRoleService().assign(session, subject_id, module, rank)
        except AppError as exc:
            raise SystemExit(
                f"could not assign {role!r} in {module!r} to {label}: {exc}"
            ) from exc
    return (
        f"assigned role {role!r} in module {module!r} to {label} ({subject_id})\n"
        f"  This raises their authority inside {module!r} only. It cannot lower it: the "
        "effective rank is the highest of their global role and every module role they hold."
    )


def module_role_revoke_command(
    subject: str,
    module: str,
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
) -> str:
    """Remove *subject*'s rung in *module*.

    Validates nothing about the module, for the reason ``terp grant revoke`` does not validate
    its permission: a module the app has since stopped declaring assignable is precisely the
    assignment you most need to clear, and insisting it still qualifies would make the row
    unreachable.
    """
    from terp.capabilities.access import ModuleRoleService

    load_app_for_cli(app_ref, app_root)
    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        subject_id, label = resolve_subject(session, subject)
        removed = ModuleRoleService().revoke(session, subject_id, module)
    if not removed:
        return f"{label} held no role in module {module!r}; nothing to revoke"
    return f"revoked the role of {label} ({subject_id}) in module {module!r}"


def module_role_list_command(
    subject: str,
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
) -> str:
    """List the rungs assigned to *subject*, marking any the app no longer supports.

    Direct assignments only, which is the honest scope for a listing keyed on a subject: what
    that subject *effectively* holds also depends on the groups they belong to, and answering
    that here would quietly mix two questions. A stale row is shown rather than filtered, on
    the same reasoning ``terp grant list`` gives — a filtered row is a right nobody can
    explain.
    """
    from terp.capabilities.access import ModuleRoleService, assignable_modules

    app = load_app_for_cli(app_ref, app_root)
    plane, specs = _declarations(app)
    assignable = assignable_modules(specs)
    ranks = {r.rank: r.name for r in plane.permissions.roles}  # type: ignore[attr-defined]

    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        subject_id, label = resolve_subject(session, subject)
        rows, _total = ModuleRoleService().list_for(
            session, subject_id, skip=0, limit=1000
        )
    if not rows:
        return f"{label} ({subject_id}) holds no per-module roles"

    lines = []
    for row in sorted(rows, key=lambda r: r.module):
        role_name = ranks.get(row.role_rank) or f"rank {row.role_rank}"
        notes = []
        if row.module not in assignable:
            notes.append("stale: this app no longer declares the module assignable")
        if row.role_rank not in ranks:
            notes.append("stale: this app no longer declares the rank")
        suffix = f"   [{'; '.join(notes)}]" if notes else ""
        lines.append(f"  {row.module}: {role_name}{suffix}")
    return f"{label} ({subject_id}) holds:\n" + "\n".join(lines)


__all__ = [
    "module_role_add_command",
    "module_role_list_command",
    "module_role_revoke_command",
]
