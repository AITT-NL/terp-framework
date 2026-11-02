"""The heartbeat of a long-running worker or scheduler (ADR 0191).

A worker and a scheduler serve no request, so nothing could ask them whether they were
alive: their container ran or it did not, and a loop stuck in a job that never returns ran
as well as a healthy one. Each now writes a heartbeat, a small JSON file in its own
container's temporary directory, from the loop whose progress it vouches for:

* ``terp jobs worker --forever`` beats before each claim, after each job it finishes, and
  between its drains, so a worker idling on an empty outbox beats every ``--poll-seconds``
  and a worker stuck in one job stops beating;
* ``terp jobs scheduler`` beats from an interval job on the scheduler's own engine, every
  :data:`SCHEDULER_BEAT_SECONDS`, so a scheduler whose engine stopped dispatching stops
  beating.

The file says when it was written (``at``, seconds since the epoch) and how old it may grow
before the process counts as stuck (``stale_after``): the writer knows its own pace, so a
worker given a longer lease is given a longer bound with it, and a stuck process cannot
move its own deadline. A container healthcheck reads it with the standard library alone,
the probe the deployment generator renders (``terp.arch.deployment``): no HTTP, no
database, and no import of the app. A deploy tool reads the same answer per unit from the
container's health status and the probe's last output, or asks the container directly.

The heartbeat is removed when the process starts and when it stops, so a container that
restarts is not called healthy by the file its previous run left behind.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import pathlib
import tempfile
import time
from collections.abc import Callable
from typing import Final

_logger = logging.getLogger("terp.cli.heartbeat")

#: How much longer than its own pace a process may stay silent before it counts as stuck.
#: A slow database round trip or a garbage collection must not read as a hang.
HEARTBEAT_GRACE_SECONDS: Final[float] = 30.0

#: How often ``terp jobs scheduler`` beats.
SCHEDULER_BEAT_SECONDS: Final[float] = 10.0


def heartbeat_path(role: str) -> pathlib.Path:
    """Where the *role* process (``worker`` or ``scheduler``) writes its heartbeat.

    One file per role in the process's temporary directory, which in a container is the
    container's own: the file is per unit by construction, and the healthcheck that reads
    it runs in the same container, with the same environment, so it finds the same path.
    """
    return pathlib.Path(tempfile.gettempdir()) / f"terp-{role}.heartbeat"


def worker_stale_after(*, lease_seconds: float, poll_seconds: float) -> float:
    """How old a worker's heartbeat may grow: its longest healthy silence, plus the grace.

    A worker is silent for at most one pause between drains, or for one job; a job that
    outlives its lease is delivered again to another worker anyway, so the lease is the
    longest a healthy job may hold the loop.
    """
    return max(lease_seconds, poll_seconds) + HEARTBEAT_GRACE_SECONDS


#: How old the scheduler's heartbeat may grow: three missed beats, plus the grace.
SCHEDULER_STALE_AFTER: Final[float] = 3 * SCHEDULER_BEAT_SECONDS + HEARTBEAT_GRACE_SECONDS


class Heartbeat:
    """Write *role*'s heartbeat to *path* (default :func:`heartbeat_path`).

    :meth:`beat` replaces the file atomically, so a reader never sees half of one. A beat
    that cannot be written is logged once and does not stop the process: the work goes on,
    and the healthcheck, finding no fresh heartbeat, reports what is true, that nothing
    vouches for it. *clock* is injectable for tests.
    """

    def __init__(
        self,
        role: str,
        *,
        stale_after: float,
        path: pathlib.Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.role = role
        self.stale_after = stale_after
        self.path = path if path is not None else heartbeat_path(role)
        self._clock = clock
        self._beats = 0
        self._failing = False

    def beat(self) -> None:
        """Record that the loop is making progress now."""
        self._beats += 1
        record = {
            "role": self.role,
            "pid": os.getpid(),
            "at": round(self._clock(), 3),
            "stale_after": self.stale_after,
            "beats": self._beats,
        }
        partial = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            partial.write_text(json.dumps(record), encoding="utf-8")
            os.replace(partial, self.path)
        except OSError as exc:
            if not self._failing:
                _logger.error(
                    "the %s heartbeat could not be written to %s (%s); its healthcheck "
                    "will report it unhealthy until it can",
                    self.role,
                    self.path,
                    exc,
                )
            self._failing = True
            return
        if self._failing:
            _logger.warning("the %s heartbeat is written to %s again", self.role, self.path)
        self._failing = False

    def clear(self) -> None:
        """Remove the heartbeat, so nothing vouches for a process that is not running."""
        with contextlib.suppress(OSError):
            self.path.unlink()


__all__ = [
    "HEARTBEAT_GRACE_SECONDS",
    "SCHEDULER_BEAT_SECONDS",
    "SCHEDULER_STALE_AFTER",
    "Heartbeat",
    "heartbeat_path",
    "worker_stale_after",
]
