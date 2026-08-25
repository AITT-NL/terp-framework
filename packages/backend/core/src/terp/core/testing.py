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

**And what strict mode still cannot see.** The reset runs *before* fixtures do, so an
autouse fixture that installs a runtime for a whole package is invisible to it: every
test gets a bus it never asked for, and strict mode agrees every time. A green strict
run therefore does not mean your installs are precise, only that none of them happen
before the suite. ``--terp-report-runtime-installs`` is the other half — it compares
the state each test starts from with the state it ends with and reports, per seam, the
tests that installed it. One or two test ids under a seam is a test installing what it
needs; *every* test id under a seam is a fixture installing it for them, which is the
thing to go and look at.

It does not, and cannot, install a runtime the test needs — that is the app's own
decision. Compose the app in a fixture (the pattern ``apps/example/tests/conftest.py``
uses) when a test needs the whole runtime, or use :func:`terp_events` /
:func:`terp_audit` when a service-level test needs only the event bus or only the
durable audit sink. See ``terp guide testing``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Protocol

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from terp.core.audit import AuditPolicy, AuditSink
    from terp.core.events import EventCatalog, EventDispatcher
    from terp.core.leases import LeaseStore

__all__ = [
    "InstallAudit",
    "InstallEvents",
    "InstallLeases",
    "terp_audit",
    "terp_default_runtime",
    "terp_events",
    "terp_leases",
    "terp_runtime_isolation",
]


class InstallLeases(Protocol):
    """What :func:`terp_leases` hands a test: ``configure_leases``' own signature.

    Exported for the same reason as :class:`InstallEvents` — so an app's ``conftest.py``
    can annotate a wrapper without importing the non-public ``configure_leases``.
    """

    def __call__(self, store: LeaseStore | None = None) -> None: ...


class InstallEvents(Protocol):
    """What :func:`terp_events` hands a test: ``configure_events``' own signature.

    Exported so an app's ``conftest.py`` can annotate a wrapper without importing the
    non-public ``configure_events`` — the fixture exists precisely to keep that import
    out of app code, and a fixture that costs its callers a type is a poor trade.
    """

    def __call__(
        self, catalog: EventCatalog, *, dispatcher: EventDispatcher | None = None
    ) -> None: ...


class InstallAudit(Protocol):
    """What :func:`terp_audit` hands a test: ``configure_audit``' own signature.

    The audit twin of :class:`InstallEvents`, and exported for the same reason — so an
    app's ``conftest.py`` can annotate a wrapper without importing the non-public
    ``configure_audit``.
    """

    def __call__(self, policy: AuditPolicy, *, sink: AuditSink | None = None) -> None: ...

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

_REPORT_FLAG = "--terp-report-runtime-installs"
_REPORT_HELP = (
    "After the run, report which tests installed which Terp runtime seam. Answers the "
    "question strict isolation cannot: a seam installed by every test in a package is "
    "an autouse installer handing tests a runtime they never asked for, which a strict "
    "run agrees with every time because the install happens after the reset."
)

_INSTALLS_KEY: pytest.StashKey[dict[str, list[str]]] = pytest.StashKey()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Declare the isolation switches (pytest hook, called when the plugin loads)."""
    parser.addini(_STRICT_INI, help=_STRICT_HELP, type="bool", default=False)
    parser.addoption(_STRICT_FLAG, action="store_true", default=False, help=_STRICT_HELP)
    parser.addoption(_REPORT_FLAG, action="store_true", default=False, help=_REPORT_HELP)


def _strict(config: pytest.Config) -> bool:
    """Whether this run resets to the baseline as well as restoring."""
    return bool(config.getoption(_STRICT_FLAG) or config.getini(_STRICT_INI))


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print the runtime-install report (pytest hook; silent unless asked for).

    Grouped by seam rather than by test, because the shape of the answer is the point:
    one or two test ids under a seam is a test installing what it needs, and *every*
    test id under a seam is a fixture installing it for the whole package — the case a
    green strict run cannot rule out, since strict resets before fixtures run.
    """
    installs = terminalreporter.config.stash.get(_INSTALLS_KEY, None)
    if installs is None:
        return
    terminalreporter.write_sep("=", "terp runtime installs")
    if not installs:
        terminalreporter.write_line("No test installed a Terp runtime seam.")
        return
    for seam_name in sorted(installs):
        node_ids = installs[seam_name]
        terminalreporter.write_line(f"{seam_name}: installed by {len(node_ids)} test(s)")
        for node_id in node_ids:
            terminalreporter.write_line(f"  {node_id}")


@pytest.fixture(autouse=True)
def terp_runtime_isolation(
    pytestconfig: pytest.Config, request: pytest.FixtureRequest
) -> Iterator[None]:
    """Restore every process-global Terp runtime to its pre-test state (autouse).

    Snapshots each seam registered in :mod:`terp.core.runtime` before the test and puts
    it back afterwards, so no test can inherit — or leak — a composed app's audit sink,
    event dispatcher, job queue, schedule catalog, password policy or decrypt call site.

    Under ``terp_strict_isolation`` the snapshot is followed by a reset, so the test
    also cannot inherit a runtime that was installed before the suite began — the one
    leak a faithful restore reproduces instead of removing. See the module docstring.

    Under ``--terp-report-runtime-installs`` the snapshot is compared with the state at
    teardown, so the run can say which test installed which seam. That is the tooling
    half of the same problem: strict mode resets *before* fixtures run, so it cannot
    see an autouse installer, and only the comparison can.
    """
    from terp.core.runtime import capture_runtimes, reset_runtimes, restore_runtimes

    state = capture_runtimes()
    reporting = bool(pytestconfig.getoption(_REPORT_FLAG))
    if _strict(pytestconfig):
        reset_runtimes()
    # What the test actually starts from: under strict mode that is the baseline, not
    # the snapshot, so comparing against the snapshot would report the reset itself.
    started = capture_runtimes() if reporting else state
    try:
        yield
    finally:
        _record_installs(pytestconfig, request.node.nodeid, started)
        restore_runtimes(state)


def _record_installs(config: pytest.Config, node_id: str, started: dict[str, Any]) -> None:
    """Note every seam this test left holding something other than what it started with.

    "Installed by this test" means installed by the test *or any of its fixtures*, and
    that is the useful reading: when the same seam shows up under every test in a
    package, the installer is a fixture, not the tests.
    """
    if not config.getoption(_REPORT_FLAG):
        return
    from terp.core.runtime import capture_runtimes

    installs = config.stash.setdefault(_INSTALLS_KEY, {})
    for name, snapshot in capture_runtimes().items():
        if name not in started or snapshot != started[name]:
            installs.setdefault(name, []).append(node_id)


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


@pytest.fixture
def terp_leases() -> InstallLeases:
    """Install a lease *store* for the duration of one test.

    The lease twin of :func:`terp_events`, and it exists because the seam fails closed by
    design: there is deliberately no in-process default store (a per-process lease would
    let two workers hold one resource), so the FIRST lease call in a test process raises
    :class:`~terp.core.leases.LeaseError`. The moment an app adopts leases, every
    service-level test that touches a claim breaks — and the app's own fix is to reach for
    ``configure_leases``, which is not on the public surface, or to compose the whole
    runtime for a test that wanted one store::

        from terp.core.leases import InMemoryLeaseStore
        terp_leases(InMemoryLeaseStore())

    **Pass a clock to test a reaper**, which is the case that cannot be tested any other
    way: a lease expires by the passage of time, so a test that cannot move time can only
    assert that nothing has lapsed yet. Both stores take one — the in-memory store here in
    core, and ``terp-cap-leases``' ``DatabaseLeaseStore`` — so the whole recovery path is
    reachable without sleeping::

        now = datetime(2026, 1, 1, tzinfo=UTC)
        clock = lambda: now
        terp_leases(InMemoryLeaseStore(clock=clock))
        ...                      # claim under the frozen clock
        now += timedelta(hours=1)  # the holder is now silent, and the claim has lapsed

    The in-memory store is deliberately **unmarked**, so an app asserting
    ``create_app(require_durable_leases=True)`` still refuses it — this fixture makes a
    lease testable, not durable. :func:`terp_runtime_isolation` undoes the install, so one
    test's store never reaches the next.
    """
    from terp.core.leases import configure_leases

    return configure_leases


@pytest.fixture
def terp_audit() -> InstallAudit:
    """Install an audit *policy* and *sink* for the duration of one test.

    The audit twin of :func:`terp_events`, and it exists because its absence had a
    sharp edge. The default sink only *logs*, so a service-level test that writes a
    row and then asserts on ``select(AuditEvent)`` reads an empty table — and an
    assertion about an empty result **passes**. The test reported that audit worked;
    what it actually established was that no durable sink was installed. Events had a
    first-class seam for exactly this and audit did not, so the asymmetry was doing
    the damage::

        from terp.capabilities.audit import persist_audit
        terp_audit(AuditPolicy.default(), sink=persist_audit)

    ``configure_audit`` is deliberately not on the ``terp.core`` public surface —
    installing the runtime is ``create_app``'s job in production, and this fixture is
    the one place a test may do it instead. :func:`terp_runtime_isolation` undoes it.

    The durable sink itself comes from ``terp.capabilities.audit``: the kernel cannot
    name it (a capability sits above core), which is why the sink is the caller's
    argument rather than a default. Passing none reinstalls the log-only sink, which
    is the state that produced the empty table — so if your assertion still finds
    nothing, the sink is what to check first.
    """
    from terp.core.audit import configure_audit

    return configure_audit
