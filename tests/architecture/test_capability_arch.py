"""Capabilities must satisfy the same ``terp.arch`` fitness rules as app modules.

Closes the long-standing gap where shipped capabilities were **not** arch-scanned
(so a capability could bypass the audited chokepoint with no build-time catch — see
the ``TenantScopedService.create`` / ``AccessService.grant`` regression this test
now guards against). Every capability's source tree is run through the full harness
here. The only opt-outs are four governed framework primitives — the durable audit
sink's raw ``session.add`` (it *is* the base of the write stack), the append-only
``AuditEvent`` table (no ``version``/``updated_at`` by design), the central
tenant predicate registered by the tenancy capability (the very thing the
``no_manual_scope_filtering`` rule points app modules toward), and the auth
capability's bearer token in its login response (the one credential an endpoint
exists to mint) — each carries a justified ``# arch-allow-*`` marker governed by a
checked-in escape-hatch budget, exactly like a client app's opt-out.
"""

from __future__ import annotations

import pathlib

import pytest

from terp.arch import assert_app_clean, check_app

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CAPS = _REPO_ROOT / "packages" / "backend" / "capabilities"

# Capabilities that must be clean with zero opt-outs.
_CLEAN_CAPS = ("access", "groups", "users", "eventbus", "oidc")
# Capabilities whose only violations are governed framework-primitive opt-outs.
_BUDGETED_CAPS = (
    "auth",
    "identity",
    "tenancy",
    "audit",
    "outbox",
    "jobs_celery",
    "webhooks",
    "files",
    "scheduler_apscheduler",
    "scheduler_celery_beat",
    "sync",
    "redis",
)


def _cap_root(name: str) -> pathlib.Path:
    return _CAPS / name / "src" / "terp" / "capabilities" / name


@pytest.mark.parametrize("name", _CLEAN_CAPS)
def test_clean_capability_passes_the_whole_harness(name: str) -> None:
    # No escape hatches: the capability satisfies every rule outright.
    assert check_app(_cap_root(name)) == []


@pytest.mark.parametrize("name", _BUDGETED_CAPS)
def test_budgeted_capability_passes_with_its_budget(name: str) -> None:
    # The framework-primitive opt-outs are justified and ratcheted by a budget.
    budget = _CAPS / name / "escape-hatch-budget.json"
    assert budget.is_file(), f"{name} capability is missing its escape-hatch budget"
    assert_app_clean(_cap_root(name), budget_path=budget)


def test_every_built_capability_is_covered() -> None:
    """Drift guard: every capability package with source is scanned by this suite.

    If a new capability is added but not listed above, this fails — so a shipped
    capability can never silently escape the harness again.
    """
    on_disk = {
        child.name
        for child in _CAPS.iterdir()
        if child.is_dir() and (_cap_root(child.name)).is_dir()
    }
    covered = set(_CLEAN_CAPS) | set(_BUDGETED_CAPS)
    assert on_disk == covered, (
        "every built capability must be arch-scanned here; "
        f"unscanned: {sorted(on_disk - covered)}; stale: {sorted(covered - on_disk)}"
    )
