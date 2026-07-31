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

**What snapshot-and-restore does not catch, and how to catch it.** Restoring is
faithful, which cuts both ways: a runtime that was already installed when the first
test started — a stray ``import app.main`` at collection time, a module-scope
``create_app()`` — is part of the snapshot, so it is restored before every test and
covers every test equally. The suite stays green together and red alone, and the
fixture cannot tell the difference, because from its point of view nothing leaked.
Set ``terp_strict_isolation = true`` (or pass ``--terp-strict-isolation``) and the
snapshot is followed by a reset, so every test starts from the platform baseline and a
test that was only ever passing on ambient state fails where it stands instead of
where the collection order happens to put it. It is opt-in because turning it on can
fail a suite that is *deliberately* composed once at import — a legitimate design that
the platform will not break under anyone. New projects generated from the template
start with it on, which is the cheap moment to adopt it.

It does not, and cannot, install a runtime the test needs — that is the app's own
decision. Compose the app in a fixture (the pattern ``apps/example/tests/conftest.py``
uses) when a test needs the whole runtime, or use :func:`terp_events` when a
service-level test needs only the event bus. See ``terp guide testing``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Protocol

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from terp.core.events import EventCatalog, EventDispatcher

__all__ = [
    "InstallEvents",
    "terp_default_runtime",
    "terp_events",
    "terp_runtime_isolation",
]


class InstallEvents(Protocol):
    """What :func:`terp_events` hands a test: ``configure_events``' own signature.

    Exported so an app's ``conftest.py`` can annotate a wrapper without importing the
    non-public ``configure_events`` — the fixture exists precisely to keep that import
    out of app code, and a fixture that costs its callers a type is a poor trade.
    """

    def __call__(
        self, catalog: EventCatalog, *, dispatcher: EventDispatcher | None = None
    ) -> None: ...

# Imports of terp.core live INSIDE the fixtures, deliberately. pytest loads a pytest11
# plugin before `pytest --cov` starts instrumenting, so importing the kernel here runs
# its module-level statements untraced and their lines read as missed. A suite that
# measures coverage should start it from process start (`coverage run -m pytest`, as
# this repo's gate does); keeping the plugin's own imports lazy keeps it from being
# the thing that forces the issue.

_STRICT_INI = "terp_strict_isolation"
_STRICT_FLAG = "--terp-strict-isolation"
_STRICT_HELP = (
    "Reset every Terp runtime to the platform baseline before each test, instead of "
    "only restoring it afterwards. Fails a test that passes on a runtime installed "
    "before the suite started (a stray import at collection time) rather than on one "
    "it installed itself."
)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Declare the strict-isolation switch (pytest hook, called when the plugin loads)."""
    parser.addini(_STRICT_INI, help=_STRICT_HELP, type="bool", default=False)
    parser.addoption(_STRICT_FLAG, action="store_true", default=False, help=_STRICT_HELP)


def _strict(config: pytest.Config) -> bool:
    """Whether this run resets to the baseline as well as restoring."""
    return bool(config.getoption(_STRICT_FLAG) or config.getini(_STRICT_INI))


@pytest.fixture(autouse=True)
def terp_runtime_isolation(pytestconfig: pytest.Config) -> Iterator[None]:
    """Restore every process-global Terp runtime to its pre-test state (autouse).

    Snapshots each seam registered in :mod:`terp.core.runtime` before the test and puts
    it back afterwards, so no test can inherit — or leak — a composed app's audit sink,
    event dispatcher, job queue, schedule catalog, password policy or decrypt call site.

    Under ``terp_strict_isolation`` the snapshot is followed by a reset, so the test
    also cannot inherit a runtime that was installed before the suite began — the one
    leak a faithful restore reproduces instead of removing. See the module docstring.
    """
    from terp.core.runtime import capture_runtimes, reset_runtimes, restore_runtimes

    state = capture_runtimes()
    if _strict(pytestconfig):
        reset_runtimes()
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
def terp_events() -> InstallEvents:
    """Install an event *catalog* (and optional dispatcher) for the duration of one test.

    The sanctioned way for a service-level test to switch the event bus on without
    composing the whole app::

        terp_events(event_catalog, dispatcher=dispatch_in_process)

    ``configure_events`` is deliberately not part of the ``terp.core`` public surface —
    installing the runtime is ``create_app``'s job in production, and this fixture is
    the one place a test may do it instead. :func:`terp_runtime_isolation` undoes it.

    The fixture *is* ``configure_events``, typed as :class:`InstallEvents`: the test
    gets the real signature — completion, and a type error for the wrong catalog —
    without the import.
    """
    from terp.core.events import configure_events

    return configure_events
