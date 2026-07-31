"""Every per-app runtime seam is registered, and therefore isolated in tests.

Terp keeps five runtime decisions in process globals that ``create_app`` installs
per app (see :mod:`terp.core.runtime`). :mod:`terp.core.testing` isolates them
generically, by walking the seam registry — which means a *sixth* seam added later
would be isolated only if its author remembered to register it. Forgetting is not
loud: the suite stays green, and the cost lands months later as a test that passes
in the suite and fails alone.

These tests remove the remembering. The kernel's own naming convention already
discriminates a per-app runtime (``reset_<name>_runtime``) from a capability
registration that is *meant* to outlive a composed app (``reset_job_tenant_context``,
``reset_scope_predicates``), so the convention can be read back as the expected set.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import terp.core
from terp.core.events import EventCatalog
from terp.core.runtime import (
    capture_runtimes,
    register_runtime_seam,
    reset_runtimes,
    restore_runtimes,
    runtime_seams,
)
from terp.core.testing import InstallEvents


def _reset_runtime_functions() -> set[str]:
    """Every ``reset_*_runtime`` callable defined across the ``terp.core`` package."""
    found: set[str] = set()
    for info in pkgutil.iter_modules(terp.core.__path__):
        module = importlib.import_module(f"terp.core.{info.name}")
        for name, value in vars(module).items():
            if (
                name.startswith("reset_")
                and name.endswith("_runtime")
                and callable(value)
                and getattr(value, "__module__", None) == module.__name__
            ):
                found.add(name)
    return found


def test_every_reset_runtime_function_is_a_registered_seam() -> None:
    """A ``reset_*_runtime`` that no seam owns would silently escape test isolation."""
    registered = {seam.reset.__name__ for seam in runtime_seams()}
    assert _reset_runtime_functions() == registered


def test_registered_seams_round_trip_their_state() -> None:
    """Capture then restore must be a true identity, or isolation would corrupt a suite."""
    before = capture_runtimes()
    reset_runtimes()
    restore_runtimes(before)
    assert capture_runtimes() == before


def test_a_seam_registered_after_a_snapshot_is_reset_not_skipped() -> None:
    """A capability imported mid-test must not leave its runtime installed afterwards."""
    installed = ["live"]
    snapshot = capture_runtimes()
    register_runtime_seam(
        "_probe",
        capture=lambda: tuple(installed),
        restore=lambda state: installed.__setitem__(slice(None), state),
        reset=lambda: installed.clear(),
    )
    restore_runtimes(snapshot)
    assert installed == []


def test_registering_a_conflicting_seam_name_is_refused() -> None:
    """Two modules claiming one name would isolate only one of them."""
    seam = runtime_seams()[0]
    register_runtime_seam(
        seam.name, capture=seam.capture, restore=seam.restore, reset=seam.reset
    )  # idempotent
    try:
        register_runtime_seam(
            seam.name, capture=lambda: None, restore=lambda _: None, reset=lambda: None
        )
    except ValueError as exc:
        assert seam.name in str(exc)
    else:  # pragma: no cover - the guard is the point of the test
        raise AssertionError("a conflicting seam registration must be refused")


def test_terp_events_fixture_installs_a_catalog_for_one_test(
    terp_events: InstallEvents,
) -> None:
    """The sanctioned way to switch the bus on without composing the whole app.

    Annotated with the exported :class:`InstallEvents`, which is the point of the
    protocol: a test that must not import ``configure_events`` should not have to pay
    for that with an untyped ``object`` either.

    That the *next* test does not inherit it is what the autouse isolation fixture
    guarantees; :func:`test_registered_seams_round_trip_their_state` pins the mechanism.
    """
    catalog = EventCatalog.default()
    assert callable(terp_events)
    terp_events(catalog)
    assert capture_runtimes()["events"][0] is catalog


def test_terp_events_fixture_carries_the_real_signature(terp_events: InstallEvents) -> None:
    """The fixture hands over ``configure_events`` itself, not a loosely typed shim.

    A wrapper taking ``(catalog: object, *, dispatcher: object | None)`` gives the app
    no completion and no type error for the wrong catalog — worse than the private
    function it exists to replace.
    """
    from terp.core.events import configure_events

    assert inspect.signature(terp_events) == inspect.signature(configure_events)
