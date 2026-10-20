"""Read the outbox backlog on an interval and say whether anything is draining it."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Final

from sqlmodel import Session

from terp.capabilities.outbox import OutboxBacklog, backlog

_log = logging.getLogger("monitor")

#: How often the backlog is read. A minute is fine-grained enough for a person reading
#: the log and coarse enough that the read costs the database nothing worth measuring.
INTERVAL_SECONDS: Final = 60.0

#: How long the oldest due row may wait before it means "no worker is running". The
#: worker re-runs every few seconds, so five minutes is far past a slow batch.
STALE_AFTER_SECONDS: Final = 300.0


def verdict(measured: OutboxBacklog, *, stale_after: float = STALE_AFTER_SECONDS) -> int:
    """The log level this backlog deserves: a warning once due work has gone stale."""
    age = measured.oldest_due_age_seconds
    if age is not None and age > stale_after:
        return logging.WARNING
    return logging.INFO


def check_once(session_factory: Callable[[], Session]) -> OutboxBacklog:
    """Read the backlog once and log it at the level :func:`verdict` gives it."""
    with session_factory() as session:
        measured = backlog(session)
    level = verdict(measured)
    if level >= logging.WARNING:
        _log.warning(
            "outbox: due work has waited %.0fs and nothing is draining it; "
            "is `terp jobs worker` running? %s",
            measured.oldest_due_age_seconds,
            measured.as_dict(),
        )
    else:
        _log.info("outbox: %s", measured.as_dict())
    return measured


def run(
    session_factory: Callable[[], Session],
    stop: threading.Event,
    *,
    interval: float = INTERVAL_SECONDS,
) -> int:
    """Check the backlog every *interval* seconds until *stop* is set; return the count.

    Waits on the event rather than sleeping, so a stop signal ends the wait at once
    instead of after the rest of the interval. A failed read is logged and the loop goes
    on: the database being briefly away is a reason to report, not to exit.
    """
    checks = 0
    while not stop.is_set():
        try:
            check_once(session_factory)
        except Exception:  # noqa: BLE001 - a monitor that dies on one bad read watches nothing
            _log.exception("outbox: the backlog could not be read")
        checks += 1
        stop.wait(interval)
    return checks
