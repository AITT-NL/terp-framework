"""Repo-root pytest fixtures shared by every suite (``tests`` + ``apps/example``).

The responsibility is **process-global runtime isolation**: the audit sink, the
event dispatcher, the job runtime, and the password policy are process-global seams
(``terp.core.audit`` / ``terp.core.events`` / ``terp.core.jobs`` / ``terp.core.passwords``),
installed per app by ``create_app``. A test that composes the example app installs the
durable audit sink and the in-process event dispatcher; a unit test that drives
``BaseService`` against a bare engine must not inherit them. This autouse fixture
resets each runtime to its safe default (log-only audit sink, empty event catalog +
no-op dispatcher, empty job catalog + in-process queue, default password policy) after
every test, so suites stay order-independent.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from terp.core.audit import reset_audit_runtime
from terp.core.events import reset_events_runtime
from terp.core.jobs import reset_jobs_runtime
from terp.core.passwords import reset_password_policy_runtime
from terp.core.scheduling import reset_schedules_runtime


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    """Restore the default audit + event + job + schedule + password-policy runtimes after each test."""
    yield
    reset_audit_runtime()
    reset_events_runtime()
    reset_jobs_runtime()
    reset_schedules_runtime()
    reset_password_policy_runtime()
