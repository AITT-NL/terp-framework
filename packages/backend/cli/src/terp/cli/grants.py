"""``terp grant`` — assign, list and revoke a subject's permission grants.

Terp has had per-subject permission grants since ADR 0013, and almost nobody uses
them. The reason is not that operators prefer broad roles; it is that granting was
the expensive option:

- it needed an **admin token**, so you had to already be the thing you were trying
  to avoid needing;
- it needed the subject's **UUID**, which nobody has — people have an email address
  or the name of an integration;
- it needed the **exact permission string**, and nothing anywhere would tell you
  which strings the app actually checks.

Faced with that, the rational move is to bump the account to a role that already
clears the check and move on. Least privilege loses to a ten-second workaround every
time. So this command removes all three costs: it resolves a subject from an email or
a service-account name, it validates the permission against the app's own catalog and
*prints the catalog* when you get it wrong, and it writes through the audited
``AccessService`` chokepoint without an HTTP round trip.

It deliberately does **not** grow a ``--force`` for an unknown permission. A grant of
a string the app never checks is not a lenient grant, it is a silent no-op — and the
person who wrote it will believe the integration is authorized until it is not.
"""

from __future__ import annotations

import contextlib
import pathlib
import uuid

from fastapi import FastAPI
from sqlmodel import Session

from terp.cli._appref import load_app, push_app_root
from terp.core.db import get_session


def _catalog(app: FastAPI) -> dict[str, str]:
    """The app's declared permissions, name -> minimum role name.

    Read off the composed app's control plane rather than a static list, so the
    command can only ever offer permissions this app really enforces.
    """
    plane = getattr(getattr(app, "state", None), "terp_control_plane", None)
    if plane is None:
        raise SystemExit(
            "the app exposes no control plane (create_app records it on app.state) — "
            "pass a terp app factory, e.g. --app app.main:build"
        )
    return {
        permission.name: permission.min_role.name
        for permission in plane.permissions.permissions
    }


def _resolve_permission(app: FastAPI, permission: str) -> str:
    """Check *permission* against the app's catalog, or fail listing the choices.

    The error is the feature: "unknown permission" alone sends the reader back to
    grepping the source, which is the moment they give up and widen the role instead.
    """
    catalog = _catalog(app)
    if permission in catalog:
        return permission
    known = "\n".join(
        f"  {name}  (needs role {min_role} or higher)"
        for name, min_role in sorted(catalog.items())
    )
    raise SystemExit(
        f"unknown permission {permission!r}. This app declares:\n{known}\n\n"
        "A grant of a permission the app never checks is a silent no-op, so it is "
        "refused rather than stored."
    )


def _resolve_subject(session: Session, subject: str) -> tuple[uuid.UUID, str]:
    """Resolve *subject* — a UUID, a user email, or a service-account name.

    Grants are keyed by a bare subject id with no foreign key (ADR 0013), which is
    what lets a user, a service account and a group all be granted the same way. The
    cost is that the id means nothing to a human, so this command accepts what people
    actually have and does the lookup itself.
    """
    with contextlib.suppress(ValueError):
        return uuid.UUID(subject), f"subject {subject}"

    if "@" in subject:
        from terp.capabilities.users import UsersService

        user = UsersService().get_by_email(session, subject)
        if user is None:
            raise SystemExit(f"no user with email {subject!r}")
        return user.id, f"user {subject!r}"

    from terp.capabilities.identity import ServiceAccountService

    account = ServiceAccountService().get_by_name(session, subject)
    if account is None:
        raise SystemExit(
            f"no service account named {subject!r} (pass an email for a user, a "
            "service-account name for a machine, or a subject UUID for anything else)"
        )
    return account.id, f"service account {subject!r}"


def _load(app_ref: str, app_root: str | pathlib.Path) -> FastAPI:
    push_app_root(app_root)
    return load_app(app_ref)


def _rank_shortfall(
    app: FastAPI, session: Session, subject: str, permission: str
) -> str | None:
    """Describe the subject's role if it sits below *permission*'s minimum, else None.

    Only answerable for subjects that carry a rank of their own — a bare UUID or a
    group has none, and for those the question belongs to whatever the id resolves to.
    """
    plane = app.state.terp_control_plane
    declared = next(
        (p for p in plane.permissions.permissions if p.name == permission), None
    )
    if declared is None:
        return None

    rank: int | None = None
    if "@" in subject:
        from terp.capabilities.users import UsersService

        user = UsersService().get_by_email(session, subject)
        rank = None if user is None else user.role
    else:
        from terp.capabilities.identity import ServiceAccountService

        account = ServiceAccountService().get_by_name(session, subject)
        rank = None if account is None else account.role

    if rank is None or rank >= declared.min_role.rank:
        return None
    return f"{plane.permissions.role_for_rank(rank).name} (rank {rank})"


def grant_add_command(
    subject: str,
    permission: str,
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
) -> str:
    """Grant *permission* to *subject*, audited and idempotent."""
    app = _load(app_ref, app_root)
    name = _resolve_permission(app, permission)
    min_role = _catalog(app)[name]

    from terp.capabilities.access import AccessService
    from terp.core import AppError

    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        subject_id, label = _resolve_subject(session, subject)
        try:
            AccessService().grant(session, subject_id, name)
        except AppError as exc:
            raise SystemExit(f"could not grant {name!r} to {label}: {exc}") from exc
        shortfall = _rank_shortfall(app, session, subject, name)
    granted = f"granted {name!r} to {label} ({subject_id})"
    if shortfall is None:
        return granted
    # The guard checks rank before it checks grants, so a grant to a subject below the
    # permission's minimum role is stored but can never fire. Saying so here is the
    # whole point of the command: a grant that silently does nothing is worse than no
    # grant, because the operator walks away believing the integration is authorized.
    return (
        f"{granted}\n"
        f"  WARNING: {name!r} requires role {min_role} or higher and this subject is "
        f"{shortfall}. The grant is stored but will not take effect until the "
        "subject's role rank reaches that minimum."
    )


def grant_revoke_command(
    subject: str,
    permission: str,
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
) -> str:
    """Revoke *permission* from *subject*.

    The permission is **not** validated against the catalog here: a permission the app
    has since stopped declaring is exactly the stale grant you most want to be able to
    clean up.
    """
    _load(app_ref, app_root)

    from terp.capabilities.access import AccessService

    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        subject_id, label = _resolve_subject(session, subject)
        removed = AccessService().revoke(session, subject_id, permission)
    if not removed:
        return f"{label} did not hold {permission!r}; nothing to revoke"
    return f"revoked {permission!r} from {label} ({subject_id})"


def grant_list_command(
    subject: str,
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
) -> str:
    """List everything *subject* holds — the answer to "why can it do that?".

    Grants inherited through group membership are included, because the question being
    asked is what this subject can do, not which rows happen to name it.
    """
    app = _load(app_ref, app_root)
    catalog = _catalog(app)

    from terp.capabilities.access import AccessService

    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        subject_id, label = _resolve_subject(session, subject)
        held = sorted(AccessService().permissions_for(session, subject_id))
    if not held:
        return f"{label} ({subject_id}) holds no permission grants"
    lines = "\n".join(
        f"  {name}"
        + ("" if name in catalog else "   [stale: this app no longer declares it]")
        for name in held
    )
    return f"{label} ({subject_id}) holds:\n{lines}"
