"""``terp outbox`` — is anything draining the durable queue, and what gave up?

The outbox had no operator surface at all: no router, no command, nothing on the health
endpoints. If nobody ran the worker, rows sat ``pending`` forever and the only way to
find out was to notice that something downstream never happened.

The lease reaper cannot answer it either, by construction. It scans *lapsed* claims, and
work that was never claimed has no claim to lapse — so a queue with zero consumers and a
queue with idle consumers look identical from every existing surface. What tells them
apart is how long the oldest DUE row has been due: a healthy queue drains that to
seconds, a queue nobody is consuming lets it grow without bound.

``backlog`` is the surface that always exists. ``GET /health/detail`` reports the same
numbers from the same function (``terp.capabilities.outbox.backlog``), so an operator at
3am and a monitor's threshold cannot disagree — but it is opt-in
(``create_app(expose_health_detail=True)``), because ``/health`` is mounted outside the
policy guard and queue depths are business signal.

``dead-letters`` answers the question the aggregate leaves open. The backlog says how
many deliveries gave up; ``last_error`` — written by the worker on the way to
``dead_lettered`` — says why, and had no reader anywhere: no schema, no router, no
command, no health field. So the platform recorded the cause of every dead letter and
could not be asked for it, which costs exactly the moment it is most expensive. The two
sibling capabilities that own a retrying table each expose their per-row failure reason
(webhooks' delivery log, sync's per-record log); the outbox was the one that did not.

There is deliberately **no redrive here**. ADR 0045 §1 and the model's own docstring fix
the lifecycle as one-way — a row is inserted ``pending`` and only ever moves to
``dispatched`` or ``dead_lettered`` — so putting a dead letter back is a change to a
recorded invariant, not capability completion, and it has real questions to answer
first (what happens to ``attempts`` and ``dead_lettered_at``, and whether the evidence of
the first failure survives the retry). That belongs in an ADR with its own columns.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime, timedelta

from terp.cli._appref import load_app, push_app_root


def render_backlog(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    fmt: str = "text",
) -> str:
    """Render what is waiting in the outbox, for a human or for a monitor.

    Builds the app first, exactly as ``terp leases`` does: the CLI acts through the same
    configured engine the app uses rather than reaching into a database with settings of
    its own.
    """
    push_app_root(app_root)
    load_app(app_ref)

    try:
        from terp.capabilities.outbox import backlog
    except ModuleNotFoundError as exc:  # pragma: no cover - guarded by the message
        raise SystemExit(
            "terp-cap-outbox is not installed, so this app has no durable outbox to "
            "report on (`terp guide outbox`)"
        ) from exc

    from sqlmodel import Session

    from terp.core._internal.engine import get_engine

    with Session(get_engine()) as session:
        waiting = backlog(session)

    if fmt == "json":
        return json.dumps(waiting.as_dict(), indent=2)

    lines = [
        "Outbox backlog",
        f"  pending       {waiting.pending}",
        f"  due now       {waiting.due}",
        f"  dead-lettered {waiting.dead_lettered}",
    ]
    if waiting.oldest_due_age_seconds is None:
        lines.append("  oldest due    <nothing due>")
        return "\n".join(lines)

    age = waiting.oldest_due_age_seconds
    lines.append(f"  oldest due    {_duration(age)} ago ({waiting.oldest_due_at})")
    # The interpretation, not just the number: an operator reading this at 3am should not
    # have to know what counts as normal. A worker claims due rows every few seconds, so
    # minutes of untouched backlog is a consumer that is not running.
    if age >= 300:
        lines.append("")
        lines.append(
            "  Nothing has claimed the oldest due row in over five minutes. A running "
            "worker claims due rows continuously, so this reads as NO CONSUMER: check "
            "that `terp jobs worker` is running and reaching this database."
        )
    return "\n".join(lines)


def render_dead_letters(
    *,
    app_ref: str = "app.main:app",
    app_root: str | pathlib.Path = ".",
    name: str | None = None,
    since_days: int | None = None,
    limit: int = 50,
    fmt: str = "text",
) -> str:
    """Render the deliveries that gave up, and the reason each one did.

    Newest first, bounded: the shape of this failure is a downstream that went away and
    took a batch with it, so the useful answer is the most recent ones rather than every
    row since the table was created.
    """
    push_app_root(app_root)
    load_app(app_ref)

    try:
        from terp.capabilities.outbox import dead_letters
    except ModuleNotFoundError as exc:  # pragma: no cover - guarded by the message
        raise SystemExit(
            "terp-cap-outbox is not installed, so this app has no durable outbox to "
            "report on (`terp guide outbox`)"
        ) from exc

    from sqlmodel import Session

    from terp.core._internal.engine import get_engine

    since = (
        None
        if since_days is None
        else datetime.now(UTC) - timedelta(days=since_days)
    )
    with Session(get_engine()) as session:
        rows = dead_letters(session, name=name, since=since, limit=limit)

    if fmt == "json":
        return json.dumps([row.as_dict() for row in rows], indent=2)

    scope = f" for {name!r}" if name else ""
    window = f", last {since_days}d" if since_days is not None else ""
    lines = [f"Outbox dead letters{scope}{window} ({len(rows)}, newest first)"]
    if not rows:
        lines.append("  <none>")
        # A green answer is worth stating, because the operator arrived here from a
        # non-zero count on the backlog and an empty list otherwise reads as a broken
        # command rather than as a filter that excluded everything.
        lines.append("")
        lines.append(
            "  Nothing gave up in this window. `terp outbox backlog` reports the "
            "dead-lettered count over ALL time, so a non-zero count there and nothing "
            "here means the failures are older than the window."
        )
        return "\n".join(lines)
    for row in rows:
        when = "-" if row.dead_lettered_at is None else row.dead_lettered_at.isoformat()
        lines.append(
            f"  {row.kind}:{row.name}  attempts={row.attempts}  gave up {when}\n"
            f"      id={row.id}\n"
            f"      {row.last_error or '<no error recorded>'}"
        )
    lines.append("")
    lines.append(
        "  A dead letter is terminal: the outbox does not put one back (ADR 0045). "
        "Fix the cause, then re-run the work through whatever produced it."
    )
    return "\n".join(lines)


def _duration(seconds: float) -> str:
    """A legible age — the units an operator thinks in, not raw seconds."""
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86_400:.1f}d"


__all__ = ["render_backlog", "render_dead_letters"]
