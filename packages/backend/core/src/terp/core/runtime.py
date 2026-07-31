"""The registry of **per-app runtime seams** — the process globals ``create_app`` installs.

Terp keeps a handful of runtime decisions in process globals rather than threading
them through every call: the audit policy and sink, the event catalog and dispatcher,
the job catalog and queue, the schedule catalog, and the password policy. Each is
installed once by :func:`terp.core.create_app` and read from deep inside a service,
which is why they are globals in the first place.

That design has one sharp edge, and it only shows up in tests. A test process composes
many apps — or none at all — so whatever the last ``create_app`` installed is still
installed when the next test runs. A unit test driving ``BaseService`` against a bare
engine inherits the previous test's durable audit sink and live event dispatcher; a
test asserting "no event was emitted" can pass for the wrong reason; and a test
asserting "an event *was* emitted" can pass only because some earlier module import
happened to configure the bus. The suite is green either way, and the greenness
depends on collection order.

The framework has always known this: its own repo-root ``conftest.py`` carried an
autouse fixture resetting each seam after every test. It was never shipped, so every
app on Terp had to rediscover the hazard and re-derive the fixture — and would first
meet it as a test suite that passes together and fails alone. This module is that
knowledge moved into the platform: seams **register themselves**, so
:mod:`terp.core.testing` can isolate all of them without knowing what they are, and
:func:`terp.core.runtime.runtime_seams` can be checked against the kernel's own
``reset_*_runtime`` functions (``tests/architecture/test_runtime_seams.py``) so a
sixth seam cannot be added and silently left out of that isolation.

**Per-app runtime, not capability registration.** Only state that ``create_app``
installs *per app* belongs here. A capability registration — the job tenant-context
seam (:func:`terp.core.jobs.reset_job_tenant_context`), the scope predicates
(:func:`terp.core.scoping.reset_scope_predicates`) — is installed at import by the
capability and is *meant* to outlive a composed app, so isolating it per test would
break the capability rather than protect the test. The naming convention carries the
distinction: a per-app seam's reset is ``reset_<name>_runtime``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "RuntimeSeam",
    "capture_runtimes",
    "register_runtime_seam",
    "reset_runtimes",
    "restore_runtimes",
    "runtime_seams",
]


@dataclass(frozen=True)
class RuntimeSeam:
    """One process-global runtime seam: how to read it, put it back, and clear it.

    *capture* returns an opaque snapshot of the seam's current state; *restore* takes
    one back. The snapshot is never inspected by this module — only handed back to the
    seam that produced it — so a seam is free to change what it holds without changing
    anything here.
    """

    name: str
    capture: Callable[[], Any]
    restore: Callable[[Any], None]
    reset: Callable[[], None]


_seams: dict[str, RuntimeSeam] = {}


def register_runtime_seam(
    name: str,
    *,
    capture: Callable[[], Any],
    restore: Callable[[Any], None],
    reset: Callable[[], None],
) -> None:
    """Register a per-app runtime seam under *name* (called at import by the owning module).

    Registration is idempotent per name and rejects a second, different registration:
    two modules claiming one seam name would make ``capture``/``restore`` ambiguous and
    silently isolate only one of them.
    """
    existing = _seams.get(name)
    seam = RuntimeSeam(name=name, capture=capture, restore=restore, reset=reset)
    if existing is not None and existing != seam:
        raise ValueError(f"runtime seam {name!r} is already registered")
    _seams[name] = seam


def runtime_seams() -> tuple[RuntimeSeam, ...]:
    """Every registered seam, in name order (a stable order for reporting and tests)."""
    return tuple(_seams[name] for name in sorted(_seams))


def capture_runtimes() -> dict[str, Any]:
    """Snapshot every registered seam, for a later :func:`restore_runtimes`."""
    return {seam.name: seam.capture() for seam in runtime_seams()}


def restore_runtimes(state: dict[str, Any]) -> None:
    """Put every seam back to the *state* :func:`capture_runtimes` returned.

    A seam missing from *state* (registered after the snapshot was taken — a capability
    imported mid-test) is **reset** rather than skipped, so nothing an isolated test
    installed can outlive it.
    """
    for seam in runtime_seams():
        if seam.name in state:
            seam.restore(state[seam.name])
        else:
            seam.reset()


def reset_runtimes() -> None:
    """Restore every seam to its safe default (the composition-root / test baseline)."""
    for seam in runtime_seams():
        seam.reset()
