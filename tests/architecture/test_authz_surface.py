"""The authorization-surface baseline: what it reduces to, and what it refuses.

The access graph has always replayed enforcement — every allowance in it is
``decide``'s own answer, from the function the kernel guard runs — so the platform
could always *say* who may reach what. What nothing did was notice when the answer
changed, and a widening is a one-line edit: a policy moving from a named permission to
a role tier, a ``require_permission`` dropped off a route, an endpoint added under a
public mount. These tests pin the noticing.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from terp.cli.access import build_access_graph_for_app
from terp.cli.authz_surface import (
    SURFACE_ARTIFACT,
    authz_surface,
    diff_authz_surface,
    read_baseline,
    render_authz_surface,
)
from terp.cli.verify import _run_authz_surface
from terp.core import (
    VIEWER,
    ControlPlane,
    ModuleSpec,
    Permission,
    PermissionModel,
    Policy,
    create_app,
)

from fastapi import APIRouter

_EXAMPLE = pathlib.Path(__file__).resolve().parents[2] / "apps" / "example"


def _graph(policy: Policy, *, permissions: tuple[Permission, ...] = ()) -> dict:
    router = APIRouter()

    @router.get("/thing")
    def read_thing() -> dict:
        return {}

    @router.post("/thing")
    def write_thing() -> dict:
        return {}

    app = create_app(
        [
            ModuleSpec(
                name="probe", router=router, policy=policy, permissions=permissions
            )
        ],
        control_plane=ControlPlane(permissions=PermissionModel(permissions=permissions)),
        # A policy naming a Permission refuses to boot without one, on purpose: a
        # grant must never be degraded to a role tier. The projection has no subject
        # to ask about, so what it answers is 'grant' either way.
        permission_enforcer=lambda _session, _subject, _name: False,
    )
    return build_access_graph_for_app(app)


def _probe_module(surface: dict) -> dict:
    """The module this file composed, by name — never `modules[0]`.

    The projection is sorted, so index 0 is whichever discovered capability happens to
    sort first. A test that mutated one of its endpoints would still pass while saying
    nothing about the module it meant to exercise.
    """
    return next(module for module in surface["modules"] if module["name"] == "probe")


# --------------------------------------------------------------------------- #
# the projection
# --------------------------------------------------------------------------- #
def test_the_surface_keeps_only_what_is_an_authority_claim() -> None:
    """A baseline that churned on unrelated fields would be regenerated unread.

    The graph carries a model's traits and the reconciliation's own bookkeeping, which
    move for honest reasons. Keeping them would make the diff noisy, and a noisy diff
    is one nobody reads — which is the whole value of the artifact.
    """
    surface = authz_surface(_graph(Policy.default()))
    assert set(surface) == {"authz_surface", "roles", "permissions", "modules"}
    endpoint = _probe_module(surface)["endpoints"][0]
    assert set(endpoint) == {
        "path",
        "methods",
        "requirement",
        "extra_permissions",
        "by_role",
    }


def test_the_rendering_is_stable_across_runs() -> None:
    """The artifact is committed and diffed, so identical input must render identically.

    Pinned because the projection sorts at four levels and a single unsorted one would
    show up as churn in an unrelated pull request rather than as a bug here.
    """
    first = render_authz_surface(_graph(Policy.default()))
    second = render_authz_surface(_graph(Policy.default()))
    assert first == second
    assert first.endswith("\n")
    assert json.loads(first)["authz_surface"] == 1


# --------------------------------------------------------------------------- #
# the diff — each line is a change somebody has to approve
# --------------------------------------------------------------------------- #
def test_an_unchanged_surface_reports_nothing() -> None:
    surface = authz_surface(_graph(Policy.default()))
    assert diff_authz_surface(surface, copy.deepcopy(surface)) == []


def test_a_lowered_requirement_is_reported_with_both_values() -> None:
    """The reviewer needs what it was, not only what it is."""
    before = authz_surface(_graph(Policy.default()))
    after = copy.deepcopy(before)
    _probe_module(after)["endpoints"][0]["requirement"] = "viewer"

    (line,) = diff_authz_surface(before, after)
    assert "requirement" in line
    assert "'viewer'" in line


def test_a_rung_that_gains_access_is_named() -> None:
    """The question a matrix answers, asked as a diff: who can reach this now?

    Reported separately from the requirement change because the two are not the same
    fact — a permission can be granted to more subjects without any requirement moving.
    """
    before = authz_surface(_graph(Policy.default()))
    after = copy.deepcopy(before)
    # The POST, deliberately: `Policy.default()` already lets a viewer READ, so
    # widening the GET would change nothing and the test would pass over an
    # unchanged surface.
    write = next(
        endpoint
        for endpoint in _probe_module(after)["endpoints"]
        if "POST" in endpoint["methods"]
    )
    assert write["by_role"]["viewer"] == "rank"
    write["by_role"]["viewer"] = "allowed"

    (line,) = diff_authz_surface(before, after)
    assert "now reachable by ['viewer']" in line


def test_a_dropped_grant_requirement_is_reported() -> None:
    """A `require_permission` removed off a route is a widening with no tier change.

    Asserted on a surface built by hand rather than from a composed app, because the
    grants a route carries come from its dependency tree and not from the module
    policy — so producing a non-empty `extra_permissions` needs a real
    `require_permission`, and the first version of this test settled for mutating an
    already-empty list behind an `or before == after` escape. It passed without ever
    reaching the branch it names, which is precisely the vacuous shape the platform's
    own `no_empty_tests` rule is about; coverage is what caught it.
    """
    before = {
        "authz_surface": 1,
        "roles": [],
        "permissions": [],
        "modules": [
            {
                "name": "probe",
                "policy": None,
                "access": None,
                "endpoints": [
                    {
                        "path": "/api/v1/probe/thing",
                        "methods": ["POST"],
                        "requirement": "role:editor",
                        "extra_permissions": ["probe.write"],
                        "by_role": {"editor": "grant"},
                    }
                ],
            }
        ],
    }
    after = copy.deepcopy(before)
    after["modules"][0]["endpoints"][0]["extra_permissions"] = []

    (line,) = diff_authz_surface(before, after)
    assert "required grants" in line
    assert "probe.write" in line


def test_a_new_endpoint_is_reported_as_unreviewed() -> None:
    """Added routes are the common case, and silence about them is the common failure."""
    before = authz_surface(_graph(Policy.default()))
    after = copy.deepcopy(before)
    added = copy.deepcopy(_probe_module(after)["endpoints"][0])
    added["path"] = "/api/v1/probe/new"
    _probe_module(after)["endpoints"].append(added)

    (line,) = diff_authz_surface(before, after)
    assert "NEW endpoint" in line
    assert "nothing has reviewed" in line


def test_a_removed_endpoint_is_reported_too() -> None:
    """Not a widening, but a surface change a baseline must not silently absorb."""
    before = authz_surface(_graph(Policy.default()))
    after = copy.deepcopy(before)
    _probe_module(after)["endpoints"] = []

    assert all("gone from the surface" in line for line in diff_authz_surface(before, after))


def test_a_changed_role_ladder_is_reported() -> None:
    """A rank silently re-scores every floor above it, so the ladder is part of the claim."""
    before = authz_surface(_graph(Policy.default()))
    after = copy.deepcopy(before)
    after["roles"][0]["rank"] = 99

    assert any("role ladder changed" in line for line in diff_authz_surface(before, after))


def test_changed_permission_floors_are_reported() -> None:
    before = authz_surface(_graph(Policy.default()))
    after = copy.deepcopy(before)
    after["permissions"] = [{"name": "invented.permission", "min_role": "viewer"}]

    assert any("permissions or their floors" in line for line in diff_authz_surface(before, after))


# --------------------------------------------------------------------------- #
# the verify runner
# --------------------------------------------------------------------------- #
def test_an_unadopted_project_is_skipped_with_the_adopt_command(
    tmp_path: pathlib.Path,
) -> None:
    """Upgrading the framework must not turn an app's gate red for a feature it never wired.

    And the note names the command, because a skip that does not say how to stop
    skipping is a skip forever.
    """
    exit_code, output = _run_authz_surface(tmp_path)
    assert exit_code == 0
    assert SURFACE_ARTIFACT in output
    assert "--format surface" in output


def test_read_baseline_is_none_when_unadopted(tmp_path: pathlib.Path) -> None:
    assert read_baseline(tmp_path) is None


def test_the_example_app_baseline_matches_its_composed_surface() -> None:
    """The reference app adopts the check, so the artifact is exercised rather than described.

    This is also the test that fails when a change to the example app's authority
    surface lands without regenerating the baseline — which is exactly what it is for.
    """
    baseline = read_baseline(_EXAMPLE)
    assert baseline is not None, (
        f"apps/example must commit {SURFACE_ARTIFACT} so this check is exercised"
    )
    exit_code, output = _run_authz_surface(_EXAMPLE)
    assert exit_code == 0, output


def test_a_baseline_that_does_not_match_fails_with_a_readable_report(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure has to be actionable: what changed, and how to accept it.

    Driven through the runner rather than the diff so the message a developer actually
    sees is the thing under test.
    """
    stale = authz_surface(_graph(Policy.default()))
    _probe_module(stale)["endpoints"][0]["requirement"] = "something-else"
    (tmp_path / SURFACE_ARTIFACT).write_text(json.dumps(stale), encoding="utf-8")

    import terp.cli.verify as verify_module

    monkeypatch.setattr(verify_module, "_DEFAULT_APP_REF", "tests.architecture.test_authz_surface:_probe_app")
    exit_code, output = _run_authz_surface(tmp_path)

    assert exit_code == 1
    assert "requirement" in output
    # It names the way to accept the change, and says to do it in the same change so a
    # reviewer sees the diff.
    assert "--format surface" in output
    assert "SAME CHANGE" in output


def _probe_app():
    """A composed app for the runner test above (referenced by dotted path)."""
    router = APIRouter()

    @router.get("/thing")
    def read_thing() -> dict:
        return {}

    @router.post("/thing")
    def write_thing() -> dict:
        return {}

    return create_app(
        [ModuleSpec(name="probe", router=router, policy=Policy.default())],
        control_plane=ControlPlane(),
    )


def test_the_surface_format_is_reachable_through_the_renderer() -> None:
    """`--format surface` is the adopt command, so the renderer has to serve it.

    Exercised through `render_access_graph` rather than `render_authz_surface`, because
    the format string is the part a user types and the branch that dispatches on it is
    the part that can be broken without any other test noticing.
    """
    from terp.cli.access import render_access_graph

    graph = _graph(Policy.default())
    assert render_access_graph(graph, "surface") == render_authz_surface(graph)
    assert render_access_graph(graph, "surface") != render_access_graph(graph, "json")


def test_a_tree_with_no_importable_app_is_named_rather_than_silently_passed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The platform's own checkout has a baseline-shaped tree and no `app.main`.

    Skipped, but skipped *out loud*: a runner that returned a bare success here would
    be indistinguishable from one that checked something, which is the failure mode the
    whole adoption shape exists to avoid.
    """
    import terp.cli.verify as verify_module

    (tmp_path / SURFACE_ARTIFACT).write_text('{"authz_surface": 1}', encoding="utf-8")
    monkeypatch.setattr(verify_module, "_DEFAULT_APP_REF", "no.such.module:build")

    exit_code, output = _run_authz_surface(tmp_path)
    assert exit_code == 0
    assert "no importable" in output
    assert "no.such.module:build" in output


def test_the_verify_dispatcher_routes_the_check_to_its_runner(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A registered check whose runner is never dispatched would fall through to a
    subprocess and try to execute its own `command` string — green for the wrong reason,
    or red for a reason that has nothing to do with authorization. Driven through
    `run_verify` so the wiring itself is the thing under test."""
    from terp.cli.verify import run_verify_command

    exit_code = run_verify_command(
        profile="full", only=["authz-surface"], root=str(tmp_path)
    )
    assert exit_code == 0
    assert SURFACE_ARTIFACT in capsys.readouterr().err
