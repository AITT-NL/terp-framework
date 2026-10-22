"""The reference app's companion: a second deployable that watches the outbox drain.

``create_app`` never mounts this package. It ships from the same repository, runs as its
own service on the backend image (``python -m monitor``), and is declared once in
``[tool.terp.arch] companions`` so ``terp check`` and the app's architecture test hold it
to every rule that applies to Python that ships (ADR 0141). The import-linter contracts
in ``pyproject.toml`` keep it and ``app`` from importing each other.

What it does is the check the outbox guide asks every deployment to wire: the worker
can stop and the API stays healthy, because rows waiting in a table are invisible to a
readiness probe. Once a minute it reads the backlog through the outbox capability's own
measure and logs it; when the oldest due row has waited past :data:`STALE_AFTER_SECONDS`
it logs a warning that nothing is draining the queue.
"""

from __future__ import annotations

from monitor.watch import INTERVAL_SECONDS, STALE_AFTER_SECONDS, check_once, run, verdict

__all__ = ["INTERVAL_SECONDS", "STALE_AFTER_SECONDS", "check_once", "run", "verdict"]
