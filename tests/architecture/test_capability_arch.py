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

from terp.arch import assert_app_clean, check_app, check_escape_hatch_budget

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CAPS = _REPO_ROOT / "packages" / "backend" / "capabilities"

# Capabilities that must be clean with zero opt-outs.
#
# ``egress`` and ``oidc`` left this list when the four security rules stopped scoping
# themselves to ``modules/`` (ADR 0136) and began seeing capability source at all. Both
# imported an HTTP client and always had; what changed is that the harness could say so.
# **``oidc`` has come back**, and by the route a marker is supposed to take: its two
# opt-outs were removed rather than re-justified when its provider requests moved onto
# the egress capability, so it now has no budget file at all. ``egress`` stays budgeted
# and always will — it *is* the seam the rule names, and the one place the platform is
# allowed to hold an HTTP client is inside the thing every other package reaches it
# through.
_CLEAN_CAPS = ("access", "groups", "users", "eventbus", "realtime", "oidc")
# Capabilities whose only violations are governed framework-primitive opt-outs.
_BUDGETED_CAPS = (
    "auth",
    "egress",
    "identity",
    "tenancy",
    "audit",
    "outbox",
    "jobs_celery",
    "leases",
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
def test_clean_capability_passes_the_whole_harness(
    name: str, tmp_path: pathlib.Path
) -> None:
    """No escape hatches: the capability satisfies every rule outright.

    The empty budget is the half that makes the claim durable, and it is not
    decoration. A marker **suppresses** the rule it names, so a capability that quietly
    acquired one would keep passing ``check_app`` with nothing to show for it — the
    first assertion would go on reading as *zero opt-outs* while the real number
    climbed. Counting markers is a separate check, and running it against ``{}`` is the
    ratchet holding at zero: any marker at all becomes "not in the budget". That is the
    only form of clean that cannot decay, and it is the difference between this list and
    a list of capabilities nobody has looked at lately.
    """
    assert check_app(_cap_root(name)) == []
    empty = tmp_path / "escape-hatch-budget.json"
    empty.write_text("{}", encoding="utf-8")
    assert check_escape_hatch_budget(_cap_root(name), budget_path=empty) == []


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
