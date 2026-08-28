"""``terp outbox backlog`` — is anything actually draining the durable queue?

The outbox had no operator surface at all: no router, no command, nothing on the health
endpoints. If nobody ran the worker, rows sat ``pending`` forever and the only way to
find out was to notice that something downstream never happened.

The lease reaper cannot answer it either, by construction. It scans *lapsed* claims, and
work that was never claimed has no claim to lapse — so a queue with zero consumers and a
queue with idle consumers look identical from every existing surface. What tells them
apart is how long the oldest DUE row has been due: a healthy queue drains that to
seconds, a queue nobody is consuming lets it grow without bound.

This command and ``GET /health/detail`` report the same numbers from the same function
(``terp.capabilities.outbox.backlog``), so a value an operator reads at 3am and a value a
monitor alerts on cannot disagree.
"""

from __future__ import annotations

import json
import pathlib

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


def _duration(seconds: float) -> str:
    """A legible age — the units an operator thinks in, not raw seconds."""
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86_400:.1f}d"


__all__ = ["render_backlog"]
