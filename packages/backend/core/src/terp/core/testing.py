"""Terp's pytest plugin — process-global runtime isolation, shipped with the platform.

Installed automatically: ``terp-core`` registers this module under pytest's ``pytest11``
entry point, so every project that depends on Terp gets the fixtures below without a
``conftest.py`` line. That is deliberate. The hazard this guards is invisible until it
bites, and the app author who trips it has done nothing wrong — so the protection
cannot be opt-in.

**What the hazard is.** ``create_app`` installs the audit, event, job, schedule and
password-policy runtimes into process globals (see :mod:`terp.core.runtime` for why
they are globals). A test process composes many apps, so without isolation the last
app composed is still installed when the next test runs. Two failure modes follow, and
both are quiet:

* A unit test driving ``BaseService`` against a bare engine inherits the previous
  test's durable audit sink and live event dispatcher, and exercises a runtime it
  never asked for.
* A test that asserts an event *was* emitted can pass only because an earlier module
  import configured the bus — so the suite is green together and red alone, and which
  it is depends on collection order.

:func:`terp_runtime_isolation` closes both. It **snapshots and restores** rather than
resetting to empty, which matters: an app that composes once at module import (rather
than per test, as ``apps/example`` does) keeps working, while anything a test installs
mid-run is still undone. Isolation therefore costs an existing suite nothing and can
only turn an order-dependent green into a deterministic result.

It does not, and cannot, install a runtime the test needs — that is the app's own
decision. Compose the app in a fixture (the pattern ``apps/example/tests/conftest.py``
uses) when a test needs the whole runtime, or use :func:`terp_events` when a
service-level test needs only the event bus. See ``terp guide testing``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

__all__ = ["terp_default_runtime", "terp_events", "terp_runtime_isolation"]

# Imports of terp.core live INSIDE the fixtures, deliberately. pytest loads a pytest11
# plugin before coverage instrumentation starts, so importing the kernel here would
# execute every module-level statement in it untraced — silently erasing the import-time
# coverage of whatever this module touches, in every project that measures it.


@pytest.fixture(autouse=True)
def terp_runtime_isolation() -> Iterator[None]:
    """Restore every process-global Terp runtime to its pre-test state (autouse).

    Snapshots each seam registered in :mod:`terp.core.runtime` before the test and puts
    it back afterwards, so no test can inherit — or leak — a composed app's audit sink,
    event dispatcher, job queue, schedule catalog, password policy or decrypt call site.
    """
    from terp.core.runtime import capture_runtimes, restore_runtimes

    state = capture_runtimes()
    try:
        yield
    finally:
        restore_runtimes(state)


@pytest.fixture
def terp_default_runtime(terp_runtime_isolation: None) -> None:
    """Run this test against the platform **defaults**, whatever the process has installed.

    The third case, and the one that is easy to miss. A test that drives a service
    against a fake or bare session and then asserts on *what was written* is reading
    ambient runtime: if any earlier fixture composed an app, the durable audit sink is
    installed and quietly adds audit rows to the session under assertion. The test then
    fails — or, worse, passes — for a reason that has nothing to do with what it checks.

    Requesting this fixture states the baseline instead of assuming it: log-only audit
    sink, empty event catalog and no-op dispatcher, empty job and schedule catalogs,
    default password policy. It depends on :func:`terp_runtime_isolation`, so the
    snapshot is taken *before* the reset and the process is left exactly as it was found.
    """
    from terp.core.runtime import reset_runtimes

    reset_runtimes()


@pytest.fixture
def terp_events() -> Callable[..., None]:
    """Install an event *catalog* (and optional dispatcher) for the duration of one test.

    The sanctioned way for a service-level test to switch the event bus on without
    composing the whole app::

        terp_events(event_catalog, dispatcher=dispatch_in_process)

    ``configure_events`` is deliberately not part of the ``terp.core`` public surface —
    installing the runtime is ``create_app``'s job in production, and this fixture is
    the one place a test may do it instead. :func:`terp_runtime_isolation` undoes it.
    """
    from terp.core.events import configure_events

    def _install(catalog: object, *, dispatcher: object | None = None) -> None:
        configure_events(catalog, dispatcher=dispatcher)  # type: ignore[arg-type]

    return _install
