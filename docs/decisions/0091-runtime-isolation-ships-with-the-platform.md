# 0091 — Runtime isolation ships with the platform

Status: accepted

## Context

Terp keeps five runtime decisions in process globals: the audit policy and sink, the
event catalog and dispatcher, the job catalog and queue, the schedule catalog, and the
password policy. Each is installed once by `create_app` and read from deep inside a
service — which is exactly why they are globals rather than arguments threaded through
every call.

In production a process composes one app, so a global is simply where that app's
decision lives. In a *test* process the assumption breaks: a suite composes many apps,
or none, and whatever the last `create_app` installed is still installed when the next
test runs.

Two failure modes follow, and both are quiet:

* A unit test driving `BaseService` against a bare engine inherits the previous test's
  durable audit sink and live event dispatcher, and exercises a runtime it never asked
  for.
* A test asserting an event *was* emitted can pass only because an earlier module
  import configured the bus. Run `pytest tests/test_catalogs.py` alone and it raises
  `EventError`; run the suite and it is green.

The second is the sharp one. A suite that is green together and red alone is not a
flake — the **green is the wrong answer**, and the platform produced it.

The framework has always known this. Its own repo-root `conftest.py` carried an autouse
fixture resetting each seam after every test, with a docstring naming the responsibility
("process-global runtime isolation … so suites stay order-independent"). It was never
shipped. So Terp solved the problem for Terp and left every app on Terp to rediscover
the hazard from the symptom, then re-derive the fixture — and to know, unprompted, which
globals exist. This was found by dogfooding: a real app's event suite passed for exactly
this reason, and the app author's report ("this is the sharpest thing on this list") was
correct.

A protection whose absence is invisible cannot be opt-in.

## Decision

**1. Seams register themselves.** `terp.core.runtime` is a registry of *per-app runtime
seams*; each owning module registers a `capture` / `restore` / `reset` triple at import.
Nothing else needs to know the list.

**2. The platform ships a pytest plugin.** `terp.core.testing` is registered under
pytest's `pytest11` entry point, so every project depending on `terp-core` gets an
autouse isolation fixture with no `conftest.py` line and no configuration.

**3. Isolation snapshots and restores; it does not blanket-reset.** Restore-to-previous
is a strict superset of reset-to-default: at session start nothing is installed, so the
snapshot *is* the default and existing behaviour is unchanged; and an app that composes
once at module import keeps its runtime instead of losing it after the first test. The
cost to an existing suite is therefore zero, and the only reachable effect is turning an
order-dependent green into a deterministic result. A seam registered *after* a snapshot
(a capability imported mid-test) is reset rather than skipped, so nothing leaks forward.

**4. Isolation does not install.** What runtime a test needs is the app's decision, not
the platform's. Three sanctioned ways: compose the app in a fixture (the pattern
`apps/example/tests/conftest.py` uses — function-scoped engine, `build()` per test);
`terp_events` when a service-level test needs only the bus; and `terp_default_runtime`
when a test drives a *fake or bare* session and asserts on what was written to it.
`configure_events` stays off the `terp.core` public surface: installing a runtime is
`create_app`'s job in production, and the fixture is the one place a test may do it
instead.

The third case was found by making this change: turning the framework's own reset into
restore surfaced two kernel unit tests that were asserting on a fake session while a
composed app's durable audit sink was installed, so the sink added audit rows to the
session under assertion. They had been passing only because the blanket reset happened
to wipe the sink first. That is the same class of bug as the one this ADR closes —
a test reading ambient runtime — one level down, and the fix is the same shape: say
what you need instead of inheriting it.

**5. Per-app runtime is not capability registration.** Only state `create_app` installs
per app belongs in the registry. The job tenant-context seam and the scope predicates
are installed at import *by a capability* and are meant to outlive a composed app;
isolating them per test would break the capability rather than protect the test. The
kernel's naming convention already carries the distinction — a per-app seam's reset is
`reset_<name>_runtime` — so it can be read back mechanically.

**6. The set is pinned.** `tests/architecture/test_runtime_seams.py` asserts that every
`reset_*_runtime` function in `terp.core` is a registered seam. A sixth seam added later
cannot be silently left out of isolation, which is the one way this decision could decay
without anyone noticing.

**7. The framework consumes its own plugin.** The repo-root `conftest.py` fixture is
deleted, not kept alongside. If the shipped plugin regressed, Terp's own suites would go
order-dependent exactly like an app's would.

**8. Coverage is measured from process start.** Shipping an entry-point plugin changed
what `pytest --cov` can see: pytest loads `pytest11` plugins *before* pytest-cov begins
instrumenting, so everything the plugin imports executes untraced and its import-time
lines read as missed. The framework's own gate fell from 100% to 89% with all 1802 tests
still passing — a coverage number that silently stops meaning what it says is worse than
one that fails. The gate therefore runs `coverage run -m pytest` + `coverage report`
(ADR 0003), which starts measuring before pytest exists. The plugin additionally defers
its `terp.core` imports into the fixture bodies, so it is not the module that forces a
consuming project to discover this the hard way.

## Consequences

An app author no longer needs to know that Terp has process globals at all. The hazard
is closed before it can be met, and the knowledge that was previously implicit in one
un-shipped conftest is now a documented seam (`terp guide testing`), a shipped plugin,
and an architecture test.

The cost is a pytest plugin active in every consuming project. It is autouse and does
one thing — snapshot and restore — so a project that has never touched a Terp runtime
sees no behavioural difference at all.
