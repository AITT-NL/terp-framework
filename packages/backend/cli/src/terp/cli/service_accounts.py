"""``terp service-account`` — provision, inspect and revoke machine credentials (ADR 0088).

The bootstrap problem is the same one ``terp user create`` solves, one step further
along: an integration needs a credential before it can call anything, and the only
alternative to a command like this is for somebody to hand it a person's password.
Given how that ends — a shared admin login nobody can revoke without breaking a
production job — the machine path has to be at least as easy as the wrong one.

**Issuing was the whole command for four releases.** ``revoke()`` and the
``ServiceAccountRead`` DTO both existed and neither had a caller outside the
framework's own tests, so a credential could be issued and never administered: a leaked
or stale secret had no supported way to be turned off, and "is this integration still
running?" — the question ``last_used_at`` is written to answer — had no surface that
could ask it. ``list`` and ``revoke`` close that. Identity ships no router by design
(it is a library capability), so the CLI is the sanctioned seam, the same one ADR 0088
§5 already put ``create`` on and the same shape ``terp leases`` uses for a state an
operator has to act on: see what is there, then do the one thing about it.

There is deliberately **no ``rotate``**. The secret is write-once by decision (ADR 0088
Consequences: "there is no command to read a secret back — a lost secret is
re-provisioned, not recovered"), and ``ServiceAccountUpdate`` says the same from the
other side: "Rotating a secret is a re-provision, not an edit … no field here could
quietly replace the credential without the operator being handed the new one." Renewal
is ``create`` then ``revoke``, in that order, which is also the only order that does not
interrupt the integration.

The generated secret is printed **once**, to stdout, and never stored in the clear.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import pathlib
import uuid

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


def _as_utc(moment: datetime.datetime) -> datetime.datetime:
    """A stored timestamp as aware UTC.

    PostgreSQL round-trips a timezone-aware column aware; SQLite returns it NAIVE, and a
    naive/aware comparison raises rather than answers. The service resolves the same
    ambiguity the same way for its expiry check — a naive stamp is UTC, because UTC is
    the only thing this capability ever writes.
    """
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=datetime.UTC)


def render_service_accounts(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    expiring_within_days: int | None = None,
    include_revoked: bool = False,
    fmt: str = "text",
) -> str:
    """List the machine credentials this app has issued, and their standing.

    The DTO does the rendering, not an ad-hoc tuple: ``ServiceAccountRead`` already
    carries exactly the safe fields (``hashed_secret`` is not among them), and it is
    exported so an app that wants its own admin page reuses it rather than assembling a
    second answer to the same question.

    ``--expiring-within-days`` is the question a renewal is actually planned from. An
    expiry that arrives unannounced is an integration that stops at 3am, and the default
    is a year, so the interval between "nobody is thinking about this" and "it is
    already broken" is the whole point of asking early.

    Revoked accounts are hidden unless asked for: after a revocation the row stays for
    the audit trail, and a list that showed every credential ever issued would bury the
    live ones — which is the set an operator is checking.
    """
    push_app_root(app_root)
    load_app(app_ref)

    from sqlmodel import Session, select

    from terp.capabilities.identity.models import ServiceAccount
    from terp.capabilities.identity.schemas import ServiceAccountRead
    from terp.core._internal.engine import get_engine

    now = datetime.datetime.now(datetime.UTC)
    cutoff = (
        None
        if expiring_within_days is None
        else now + datetime.timedelta(days=expiring_within_days)
    )
    with Session(get_engine()) as session:
        rows = list(session.exec(select(ServiceAccount).order_by(ServiceAccount.name)))

    accounts = [ServiceAccountRead.model_validate(row, from_attributes=True) for row in rows]
    if not include_revoked:
        accounts = [account for account in accounts if account.is_active]
    if cutoff is not None:
        accounts = [
            account
            for account in accounts
            if account.expires_at is not None and _as_utc(account.expires_at) <= cutoff
        ]

    if fmt == "json":
        return json.dumps(
            [account.model_dump(mode="json") for account in accounts], indent=2
        )

    heading = "Service accounts" if include_revoked else "Service accounts (active)"
    if expiring_within_days is not None:
        heading += f", expiring within {expiring_within_days}d"
    lines = [f"{heading} ({len(accounts)})"]
    if not accounts:
        lines.append("  <none>")
        return "\n".join(lines)
    for account in accounts:
        lines.append(
            f"  {account.name}  rank={account.role}  client_id={account.client_id}\n"
            f"      {_standing(account, now)}"
        )
    return "\n".join(lines)


def _standing(account: object, now: datetime.datetime) -> str:
    """One legible phrase for a credential's condition — expiry first, then use.

    Both halves in one line because they are read together: a credential that expires on
    Friday and was last used in March is a renewal nobody needs to do, and one that
    expires on Friday and ran an hour ago is an outage scheduled for Saturday.
    """
    expires_at = getattr(account, "expires_at", None)
    if expires_at is None:
        expiry = "expires never"
    else:
        deadline = _as_utc(expires_at)
        days = (deadline - now).days
        expiry = (
            f"EXPIRED {deadline.date().isoformat()}"
            if deadline <= now
            else f"expires {deadline.date().isoformat()} ({days}d)"
        )
    last_used_at = getattr(account, "last_used_at", None)
    used = (
        "never used"
        if last_used_at is None
        else f"last used {_as_utc(last_used_at).date().isoformat()}"
    )
    revoked = "" if getattr(account, "is_active", True) else "REVOKED  "
    return f"{revoked}{expiry}, {used}"


def revoke_service_account_command(
    subject: str,
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
) -> str:
    """Deactivate the credential named by *subject* (a name or an id), audited.

    Calls the service's own ``revoke``, which bumps the token epoch and writes through
    the audited chokepoint — so outstanding access tokens stop working immediately rather
    than at their own convenience, and the revocation is in the audit log. That behaviour
    already existed and was already tested; what did not exist was any way to ask for it
    short of an app writing the call itself.

    Accepts the name an operator actually has, the way ``terp grant`` already does: a
    UUID is used as-is, anything else is looked up by name.
    """
    push_app_root(app_root)
    load_app(app_ref)

    from terp.capabilities.identity import ServiceAccountService

    service = ServiceAccountService()
    with contextlib.closing(get_session()) as gen:
        session = next(gen)
        try:
            account_id = uuid.UUID(subject)
            label = f"service account {subject}"
        except ValueError:
            account = service.get_by_name(session, subject)
            if account is None:
                raise SystemExit(
                    f"no service account named {subject!r} — `terp service-account list` "
                    "shows the live ones"
                ) from None
            account_id, label = account.id, f"service account {subject!r}"
        if not service.revoke(session, account_id):
            raise SystemExit(f"no service account with id {account_id}")
    return (
        f"revoked {label}: deactivated and token epoch bumped, so any access token "
        "already issued for it stops working now."
    )


__all__ = [
    "create_service_account_command",
    "render_service_accounts",
    "revoke_service_account_command",
]
