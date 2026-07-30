"""``terp service-account create`` — provision a machine credential against the store.

The bootstrap problem is the same one ``terp user create`` solves, one step further
along: an integration needs a credential before it can call anything, and the only
alternative to a command like this is for somebody to hand it a person's password.
Given how that ends — a shared admin login nobody can revoke without breaking a
production job — the machine path has to be at least as easy as the wrong one.

The generated secret is printed **once**, to stdout, and never stored in the clear.
There is no command to read it back; a lost secret is re-provisioned. The account's
role rank is required, not defaulted, because the whole point is that an integration's
authority is chosen rather than inherited.
"""

from __future__ import annotations

import contextlib
import datetime
import pathlib

from terp.cli._appref import load_app, push_app_root
from terp.cli.users import resolve_role
from terp.core.db import get_session


def create_service_account_command(
    name: str,
    *,
    role: str,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    description: str | None = None,
    expires_in_days: int | None = 365,
) -> str:
    """Build *app_ref*, then provision service account *name* at *role*, audited.

    *expires_in_days* defaults to a year rather than to "never": a machine credential
    outlives the ticket that justified it and the person who created it, so an end date
    it has to be renewed past is the only thing that reliably forces a second look.
    Pass ``None`` for a non-expiring credential — deliberately, and in writing.
    """
    push_app_root(app_root)
    load_app(app_ref)

    from terp.capabilities.identity import ServiceAccountService
    from terp.capabilities.identity.schemas import ServiceAccountCreate
    from terp.core import AppError

    rank = resolve_role(role)
    expires_at = (
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=expires_in_days)
        if expires_in_days is not None
        else None
    )
    service = ServiceAccountService()
    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        try:
            account, secret = service.provision(
                session,
                ServiceAccountCreate(
                    name=name,
                    role_rank=rank,
                    description=description,
                    expires_at=expires_at,
                ),
            )
        except AppError as exc:
            raise SystemExit(f"could not create service account {name!r}: {exc}") from exc

    expiry = account.expires_at.date().isoformat() if account.expires_at else "never"
    return (
        f"created service account {name!r} (id {account.id}, role rank {rank}, "
        f"expires {expiry})\n"
        f"  client_id:     {account.client_id}\n"
        f"  client_secret: {secret}\n"
        "\nThe secret is shown once and is not recoverable. Store it in the "
        "integration's secret store now; if it is lost, provision a new account."
    )
