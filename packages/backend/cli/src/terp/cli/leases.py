"""``terp leases`` — see who holds what, and recover what a dead worker left behind.

A lease is only as useful as an operator's ability to act on it at 3am, and the two things
they need then are on this command:

* ``terp leases list --expired`` answers "what is stuck, and who was holding it?" — the
  question that, before the lease seam, had no answer at all: a row said ``claimed`` and
  nothing distinguished a worker still going from one that died an hour ago.
* ``terp leases reap`` runs one recovery cycle by hand. It is the same bounded, fenced cycle
  the declared ``leases.reap`` job runs on its cron, so pressing it during an incident does
  exactly what the schedule would have done a few minutes later — no special path, no
  operator-only power to get wrong. It touches **only** already-lapsed leases, so it cannot
  take work away from a holder that is still reporting, and running it twice is a no-op.

Both build the app first (``create_app`` is what installs the lease store), so the CLI acts
through the same configured seam the app does rather than reaching into the database with
settings of its own.

There is deliberately **no** ``terp leases release``. Force-releasing a live lease is the
split brain the epoch fence exists to prevent, and a command for it would be a permanent
invitation to cause one: the holder may be alive, and its next write would land on top of the
successor's. Wait for the expiry — that is what the expiry is for.
"""

from __future__ import annotations

import pathlib
from datetime import datetime

from terp.core.leases import LeaseStore, active_lease_store, registered_lease_reapers

from terp.cli._appref import load_app, push_app_root


def _prepare(app_ref: str, app_root: str | pathlib.Path) -> LeaseStore:
    """Build *app_ref* (installing its lease store) and return the configured store."""
    push_app_root(app_root)
    load_app(app_ref)
    store = active_lease_store()
    if store is None:
        raise SystemExit(
            "this app configured no lease store, so there are no leases to show or reap; "
            "pass create_app(lease_store=DatabaseLeaseStore()) from terp-cap-leases "
            "(`terp guide leases`)"
        )
    return store


def render_leases(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    kind: str | None = None,
    expired_only: bool = False,
    limit: int = 50,
) -> str:
    """Render the lease table: resource, holder, expiry, and whether it has lapsed.

    Generated from the configured store, so it always shows what the app itself would see.
    The registered recoveries are listed underneath, because "nothing reaped it" and "no
    reaper is registered for that kind" look identical on the rows alone — and the second is
    the mistake an author actually makes.
    """
    _prepare(app_ref, app_root)
    from sqlmodel import Session

    from terp.capabilities.leases import list_leases
    from terp.core import PaginationParams
    from terp.core._internal.engine import get_engine

    with Session(get_engine()) as session:
        rows, total, now = list_leases(
            session,
            pagination=PaginationParams(skip=0, limit=limit),
            kind=kind,
            expired_only=expired_only,
        )

    heading = "Expired leases" if expired_only else "Leases"
    lines = [f"{heading} ({len(rows)} of {total})"]
    if not rows:
        lines.append("  <none>")
    for row in rows:
        holder = row.holder or "-"
        lines.append(
            f"  {row.resource_kind}:{row.resource_key}  holder={holder}  "
            f"epoch={row.epoch}  {_state(row.holder, row.expires_at, now)}"
        )
    reapers = registered_lease_reapers()
    lines.append("")
    lines.append(
        "Registered recoveries: " + (", ".join(sorted(reapers)) if reapers else "<none>")
    )
    # Named per kind actually on this page rather than as a blanket note: what an operator
    # needs to know is whether *this* stuck resource has somewhere to be put back, and
    # "nothing reaped it" reads identically to "nobody declared a recovery for it" on the
    # rows alone.
    uncovered = sorted({row.resource_kind for row in rows} - set(reapers))
    if uncovered:
        lines.append("Kinds with no recovery: " + ", ".join(uncovered))
        lines.append(
            "  These are only released on expiry - nothing puts their rows back. Register "
            "one with register_lease_reaper(kind, recovery)."
        )
    return "\n".join(lines)


def _state(holder: str | None, expires_at: datetime | None, now: datetime) -> str:
    """One legible phrase for a lease's condition at *now*."""
    if holder is None or expires_at is None:
        return "free"
    deadline = (
        expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=now.tzinfo)
    )
    if deadline <= now:
        return f"EXPIRED at {deadline.isoformat()} - awaiting reap"
    return f"held until {deadline.isoformat()}"


def reap_leases_command(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    kind: str | None = None,
    limit: int = 100,
    purge_idle_seconds: float | None = None,
) -> str:
    """Run one reap cycle against the app's configured store and report the tally.

    The same cycle the declared ``leases.reap`` job runs, so an operator pressing this during
    an incident gets exactly what the schedule would have done — including each domain's
    registered recovery, written through its own audited service. ``--purge-idle-seconds``
    also trims free lease records idle for that long, which is the maintenance half (a
    row-shaped resource leaves one record per row ever processed).
    """
    store = _prepare(app_ref, app_root)
    try:
        from terp.capabilities.leases import reap_expired_leases
    except ImportError as exc:  # pragma: no cover - defensive: a store implies the package
        raise SystemExit(
            "terp leases reap requires the terp-cap-leases capability, which is not "
            "installed. Add terp-cap-leases to the app's dependencies (wiring a "
            "DatabaseLeaseStore already requires it)."
        ) from exc
    from sqlmodel import Session

    from terp.core._internal.engine import get_engine

    with Session(get_engine()) as session:
        result = reap_expired_leases(
            session,
            store,
            kind=kind,
            limit=limit,
            purge_idle_seconds=purge_idle_seconds,
        )
    return f"lease reap: {result}"


__all__ = ["reap_leases_command", "render_leases"]
