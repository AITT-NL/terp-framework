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
import terp.cli.verify as verify_module
from terp.cli.authz_changes import authority_changes
from terp.cli.authz_surface import (
    SURFACE_ARTIFACT,
    authz_surface,
    check,
    diff_authz_surface,
    pinned_problem,
    read_baseline,
    render_authz_surface,
    verdict,
)
from terp.core import (
    ControlPlane,
    ModuleSpec,
    Permission,
    PermissionModel,
    Policy,
    Roles,
    create_app,
)
from terp.core.routing import route_policy

from fastapi import APIRouter
from fastapi.testclient import TestClient

_EXAMPLE = pathlib.Path(__file__).resolve().parents[2] / "apps" / "example"


def _run_authz_surface(root: pathlib.Path) -> tuple[int, str]:
    """The check as `terp verify` runs it, on the app ref it composes (read at call time,
    so a test can point it at an app of its own)."""
    return check(root, verify_module._DEFAULT_APP_REF, note_prefix=verify_module.NOTE_PREFIX)


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


def test_a_pinned_tree_whose_app_cannot_be_composed_is_red(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tree that commits a baseline has said its surface is pinned.

    An app that cannot then be composed is a surface nobody checked. This was a skip
    once, so every change passed for as long as the app failed to import, which is the
    one moment nobody is looking. A tree with no baseline still skips earlier, with the
    adopt command (`test_an_unadopted_project_is_skipped_with_the_adopt_command`).
    """
    import terp.cli.verify as verify_module

    (tmp_path / SURFACE_ARTIFACT).write_text('{"authz_surface": 1}', encoding="utf-8")
    monkeypatch.setattr(verify_module, "_DEFAULT_APP_REF", "no.such.module:build")

    exit_code, output = _run_authz_surface(tmp_path)
    assert exit_code == 1
    assert "no.such.module:build" in output
    assert "nothing was checked" in output


# --------------------------------------------------------------------------- #
# what the surface cannot see is red, never a pass
# --------------------------------------------------------------------------- #
def _strict_router() -> APIRouter:
    router = APIRouter()

    @router.get("/thing")
    def read_thing() -> dict:
        return {"who": "strict"}

    return router


def _compose(router: APIRouter, policy: Policy | None = None):
    return create_app(
        [ModuleSpec(name="probe", router=router, policy=policy or Policy.default())],
        control_plane=ControlPlane(),
    )


def _strict_app():
    return _compose(_strict_router())


def _shadowed_app():
    """`GET /thing` twice, the public one registered first: that one answers."""
    router = APIRouter()

    @router.get("/thing")
    @route_policy(Policy.public(reason="a shadow registered first"))
    def shadow() -> dict:
        return {"who": "shadow"}

    @router.get("/thing")
    def read_thing() -> dict:
        return {"who": "strict"}

    return _compose(router)


def _nested_app():
    """A public route on a router included inside the module's router."""
    router = _strict_router()
    nested = APIRouter()

    @nested.get("/export")
    @route_policy(Policy.public(reason="a nested export"))
    def export() -> dict:
        return {"who": "nested"}

    router.include_router(nested, prefix="/deep")
    return _compose(router)


def _hidden_nested_app():
    """The same public route, declared out of the OpenAPI document."""
    router = _strict_router()
    nested = APIRouter()

    @nested.get("/export", include_in_schema=False)
    @route_policy(Policy.public(reason="a nested export"))
    def export() -> dict:
        return {"who": "nested"}

    router.include_router(nested, prefix="/deep")
    return _compose(router)


def _pin_the_strict_surface(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, ref: str):
    import terp.cli.verify as verify_module

    (tmp_path / SURFACE_ARTIFACT).write_text(
        render_authz_surface(build_access_graph_for_app(_strict_app())), encoding="utf-8"
    )
    monkeypatch.setattr(verify_module, "_DEFAULT_APP_REF", ref)


def test_a_path_two_routes_serve_is_red(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The router answers with the first route, the diff compared whichever it met last.

    So a public route registered ahead of a guarded one at the same method and path
    served anonymous callers while the diff saw nothing change.
    """
    _pin_the_strict_surface(
        tmp_path, monkeypatch, "tests.architecture.test_authz_surface:_shadowed_app"
    )
    assert TestClient(_shadowed_app()).get("/api/v1/probe/thing").json() == {"who": "shadow"}

    exit_code, output = _run_authz_surface(tmp_path)
    assert exit_code == 1
    assert "GET /api/v1/probe/thing: served by 2 routes" in output


def test_a_route_the_graph_cannot_place_is_red(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The graph lists a nested router's route under `omitted_routes`, its leak alarm.

    The surface dropped that list, so a public route served one router down passed as
    no change at all.
    """
    _pin_the_strict_surface(
        tmp_path, monkeypatch, "tests.architecture.test_authz_surface:_nested_app"
    )
    assert TestClient(_nested_app()).get("/api/v1/probe/deep/export").status_code == 200

    exit_code, output = _run_authz_surface(tmp_path)
    assert exit_code == 1
    assert "GET /api/v1/probe/deep/export: served, but the access graph cannot place it" in output


def test_a_route_kept_out_of_the_openapi_document_is_red_all_the_same(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The leak alarm was reconciled against ``app.openapi()``, which one keyword empties.

    ``include_in_schema=False`` on the nested route took it out of that document, so the
    alarm had nothing to report and an anonymous request was served under a green check.
    """
    _pin_the_strict_surface(
        tmp_path, monkeypatch, "tests.architecture.test_authz_surface:_hidden_nested_app"
    )
    app = _hidden_nested_app()
    assert "/api/v1/probe/deep/export" not in app.openapi()["paths"]
    assert TestClient(app).get("/api/v1/probe/deep/export").json() == {"who": "nested"}

    exit_code, output = _run_authz_surface(tmp_path)
    assert exit_code == 1
    assert "GET /api/v1/probe/deep/export: served, but the access graph cannot place it" in output


def _both_methods() -> APIRouter:
    router = APIRouter()

    @router.api_route("/both", methods=["GET", "POST"])
    def both() -> dict:
        return {}

    return router


def test_a_lowered_read_tier_on_a_route_serving_two_methods_is_reported() -> None:
    """The graph judges one method per route, so the endpoint lines did not move.

    The module's policy did, and it is compared now.
    """
    before = authz_surface(
        build_access_graph_for_app(
            _compose(_both_methods(), Policy(read=Roles.ADMIN, write=Roles.ADMIN))
        )
    )
    after = authz_surface(
        build_access_graph_for_app(
            _compose(_both_methods(), Policy(read=Roles.VIEWER, write=Roles.ADMIN))
        )
    )
    differences = diff_authz_surface(before, after)
    assert any(line.startswith("module probe: policy ") for line in differences), differences


def test_a_module_that_starts_taking_module_roles_is_reported() -> None:
    """A per-module role can lift a caller over a floor (ADR 0121) with no rung's answer
    changing in this view, so the module's `access` is compared on its own."""
    before = authz_surface(_graph(Policy.default()))
    after = copy.deepcopy(before)
    _probe_module(after)["access"] = {
        "assignable": True,
        "label": "Probe",
        "platform_reason": None,
    }
    differences = diff_authz_surface(before, after)
    assert any(line.startswith("module probe: access ") for line in differences), differences


def test_a_difference_no_line_names_is_still_reported() -> None:
    """A field the entries do not compare (a later format's, say) moves no itemised line.

    Whatever the lines do not name is reported whole, because "no difference" is the one
    answer this check must never give about a surface that changed.
    """
    before = authz_surface(_graph(Policy.default()))
    after = copy.deepcopy(before)
    _probe_module(after)["a_field_no_entry_compares"] = True
    assert diff_authz_surface(before, after) == [
        "the authorization surface changed in a way this check does not itemise; "
        f"read the diff of {SURFACE_ARTIFACT} line by line"
    ]


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


# --------------------------------------------------------------------------- #
# ADR 0209: each change is labelled, and only a proven narrowing is not a widening
# --------------------------------------------------------------------------- #
def _hand_surface(*endpoints: dict, policy: dict | None = None, access=None) -> dict:
    """A surface built by hand, so each rule is tested on exactly the answers it reads."""
    return {
        "authz_surface": 1,
        "roles": [
            {"name": "viewer", "rank": 10},
            {"name": "editor", "rank": 20},
            {"name": "admin", "rank": 30},
        ],
        "permissions": [
            {"min_role": "editor", "name": "notes.delete"},
            {"min_role": "editor", "name": "notes.purge"},
        ],
        "modules": [
            {
                "name": "probe",
                "policy": policy,
                "access": access,
                "endpoints": list(endpoints),
            }
        ],
    }


def _endpoint(by_role: dict, *, requirement: str = "role:viewer", grants=(), path="/x") -> dict:
    return {
        "path": f"/api/v1/probe{path}",
        "methods": ["GET"],
        "requirement": requirement,
        "extra_permissions": list(grants),
        "by_role": by_role,
    }


_ALL = {"viewer": "allowed", "editor": "allowed", "admin": "allowed"}
_EDITORS = {"viewer": "rank", "editor": "allowed", "admin": "allowed"}


def _only(before: dict, after: dict) -> dict:
    (entry,) = authority_changes(before, after)
    return entry


def test_a_rung_that_gains_reach_widens_and_one_that_loses_it_narrows() -> None:
    gained = _only(_hand_surface(_endpoint(_EDITORS)), _hand_surface(_endpoint(_ALL)))
    assert (gained["widens"], gained["gains"]) == (True, ["viewer"])
    lost = _only(_hand_surface(_endpoint(_ALL)), _hand_surface(_endpoint(_EDITORS)))
    assert (lost["widens"], lost["loses"]) == (False, ["viewer"])


def test_a_grant_reaches_whoever_holds_it() -> None:
    """A new endpoint only a grant opens is reachable, so it is a widening: the rule names
    the refused answers, and `grant` is not one of them."""
    granted = {"viewer": "rank", "editor": "grant", "admin": "grant"}
    new = _only(
        _hand_surface(),
        _hand_surface(_endpoint(granted, requirement="permission:notes.delete")),
    )
    assert new["widens"] is True
    assert new["gains"] == ["admin", "editor"]
    unreachable = _only(_hand_surface(), _hand_surface(_endpoint({"viewer": "no_policy"})))
    assert unreachable["widens"] is False


def test_a_grant_moved_to_another_permission_widens() -> None:
    """The holders of two permissions may differ, though every rung's answer is `grant`."""
    granted = {"viewer": "rank", "editor": "grant", "admin": "grant"}
    moved = _only(
        _hand_surface(_endpoint(granted, requirement="permission:notes.delete")),
        _hand_surface(_endpoint(granted, requirement="permission:notes.purge")),
    )
    assert moved["widens"] is True
    assert [item["name"] for item in moved["permissions"]] == ["notes.delete", "notes.purge"]


def test_fewer_required_grants_widen_and_more_narrow() -> None:
    fewer = _only(
        _hand_surface(_endpoint(_EDITORS, grants=["notes.delete"])),
        _hand_surface(_endpoint(_EDITORS)),
    )
    assert fewer["widens"] is True
    more = _only(
        _hand_surface(_endpoint(_EDITORS)),
        _hand_surface(_endpoint(_EDITORS, grants=["notes.delete"])),
    )
    assert more["widens"] is False


def test_a_new_endpoint_widens_and_a_gone_one_narrows() -> None:
    new = _only(_hand_surface(), _hand_surface(_endpoint(_ALL)))
    assert (new["widens"], new["gains"]) == (True, ["admin", "editor", "viewer"])
    gone = _only(_hand_surface(_endpoint(_ALL)), _hand_surface())
    assert gone["widens"] is False


def test_a_public_endpoint_says_anyone_can_reach_it() -> None:
    public = {"viewer": "public", "editor": "public", "admin": "public"}
    entry = _only(_hand_surface(_endpoint(_ALL)), _hand_surface(_endpoint(public, requirement="public")))
    assert (entry["widens"], entry["anonymous"]) == (True, True)


def test_a_module_policy_is_judged_tier_by_tier() -> None:
    admins = {"public": False, "authenticated": True, "read": "role:admin", "write": "role:admin"}
    viewers = dict(admins, read="role:viewer")
    lowered = _only(_hand_surface(policy=admins), _hand_surface(policy=viewers))
    assert lowered["widens"] is True
    raised = _only(_hand_surface(policy=viewers), _hand_surface(policy=admins))
    assert raised["widens"] is False
    public = {"public": True, "public_reason": "r", "allows_public_writes": False}
    assert _only(_hand_surface(policy=admins), _hand_surface(policy=public))["widens"] is True
    assert _only(_hand_surface(policy=public), _hand_surface(policy=admins))["widens"] is False
    to_grant = dict(admins, read="permission:notes.delete")
    assert _only(_hand_surface(policy=viewers), _hand_surface(policy=to_grant))["widens"] is False
    assert _only(_hand_surface(policy=to_grant), _hand_surface(policy=admins))["widens"] is True


def test_a_module_that_takes_module_roles_widens() -> None:
    on = {"assignable": True, "label": "Probe", "platform_reason": None}
    assert _only(_hand_surface(), _hand_surface(access=on))["widens"] is True
    assert _only(_hand_surface(access=on), _hand_surface())["widens"] is False
    relabelled = dict(on, label="Renamed")
    assert _only(_hand_surface(access=on), _hand_surface(access=relabelled))["widens"] is False


def test_the_ladder_widens_however_it_moved_and_a_floor_only_when_it_fell() -> None:
    before = _hand_surface()
    reranked = copy.deepcopy(before)
    reranked["roles"][0]["rank"] = 5
    assert _only(before, reranked)["widens"] is True
    lowered = copy.deepcopy(before)
    lowered["permissions"][0]["min_role"] = "viewer"
    assert _only(before, lowered)["widens"] is True
    raised = copy.deepcopy(before)
    raised["permissions"][0]["min_role"] = "admin"
    assert _only(before, raised)["widens"] is False


def test_what_no_entry_names_is_a_widening() -> None:
    before = _hand_surface()
    after = copy.deepcopy(before)
    after["modules"][0]["a_field_no_entry_compares"] = True
    entry = _only(before, after)
    assert (entry["subject"], entry["widens"]) == ("surface", True)


def test_an_entry_carries_the_labels_a_person_reads_it_by() -> None:
    """The operation's label and the permissions' labels come from the access graph."""
    graph = _graph(Policy.default())
    current = authz_surface(graph)
    before = copy.deepcopy(current)
    _probe_module(before)["endpoints"] = []
    entries = authority_changes(before, current, graph)
    assert entries and all(entry["widens"] for entry in entries)
    assert {entry["module"] for entry in entries} == {"probe"}
    assert all("operation" in entry for entry in entries)


# --------------------------------------------------------------------------- #
# ADR 0209: the pin, the verdict's states, and the JSON a tool reads
# --------------------------------------------------------------------------- #
def _pin(root: pathlib.Path, value: str = '["authz-surface"]') -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "probe"\n\n[tool.terp.verify]\npinned = {value}\n', encoding="utf-8"
    )


def test_a_pinned_app_without_a_baseline_is_red_and_names_the_command(
    tmp_path: pathlib.Path,
) -> None:
    _pin(tmp_path)
    result = verdict(tmp_path, "app.main:build", "note: ")
    assert result.exit_code == 1
    assert result.fields["authority_state"] == "missing"
    assert "--format surface > authz-surface.json" in result.output


def test_an_unpinned_app_without_a_baseline_still_skips(tmp_path: pathlib.Path) -> None:
    result = verdict(tmp_path, "app.main:build", "note: ")
    assert (result.exit_code, result.fields["authority_state"]) == (0, "not_pinned")
    assert result.output.startswith("note: ")


def test_only_the_authority_surface_can_be_pinned() -> None:
    assert pinned_problem(None) == ""
    assert pinned_problem(["authz-surface"]) == ""
    assert "only authz-surface" in pinned_problem(["api-contract"])
    assert "list of check ids" in pinned_problem("authz-surface")


def test_verify_reads_the_pin_and_refuses_a_bad_one(tmp_path: pathlib.Path) -> None:
    from terp.cli.verify import app_declared_checks

    _pin(tmp_path)
    assert app_declared_checks(tmp_path) == ()
    _pin(tmp_path, '["api-contract"]')
    with pytest.raises(SystemExit, match="only authz-surface"):
        app_declared_checks(tmp_path)


def test_the_json_names_changes_and_unseen_routes_apart(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tool asks an owner about `authority_changes` and hands `authority_unseen` to
    whoever fixes the code: the second is never a change to approve."""
    from terp.cli.verify import run_verify_command

    _pin_the_strict_surface(
        tmp_path, monkeypatch, "tests.architecture.test_authz_surface:_shadowed_app"
    )
    run_verify_command(profile="full", only=["authz-surface"], root=str(tmp_path), fmt="json")
    (result,) = json.loads(capsys.readouterr().out)["checks"]
    assert result["authority_state"] == "unseen"
    assert result["authority_changes"] == []
    assert [item["kind"] for item in result["authority_unseen"]] == ["served_twice"]

    widened = authz_surface(build_access_graph_for_app(_strict_app()))
    _probe_module(widened)["endpoints"][0]["by_role"]["viewer"] = "rank"
    (tmp_path / SURFACE_ARTIFACT).write_text(json.dumps(widened), encoding="utf-8")
    monkeypatch.setattr(
        verify_module, "_DEFAULT_APP_REF", "tests.architecture.test_authz_surface:_strict_app"
    )
    run_verify_command(profile="full", only=["authz-surface"], root=str(tmp_path), fmt="json")
    (result,) = json.loads(capsys.readouterr().out)["checks"]
    assert result["authority_state"] == "changed"
    (entry,) = result["authority_changes"]
    assert entry["widens"] is True and entry["gains"] == ["viewer"]


def test_the_text_says_which_lines_widen(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = authz_surface(build_access_graph_for_app(_strict_app()))
    _probe_module(stale)["endpoints"][0]["by_role"]["viewer"] = "rank"
    (tmp_path / SURFACE_ARTIFACT).write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(
        verify_module, "_DEFAULT_APP_REF", "tests.architecture.test_authz_surface:_strict_app"
    )
    exit_code, output = _run_authz_surface(tmp_path)
    assert exit_code == 1
    assert "  - widens: GET /api/v1/probe/thing: now reachable by ['viewer']" in output


def test_what_cannot_be_ranked_is_a_widening_and_a_renamed_answer_is_not() -> None:
    """The edges of the rule: a policy added or removed, a caller no longer required to sign
    in, a requirement whose floor this surface cannot place, and two answers that reach the
    same rung under different names."""
    admins = {"public": False, "authenticated": True, "read": "role:admin", "write": "role:admin"}
    assert _only(_hand_surface(policy=admins), _hand_surface(policy=None))["widens"] is False
    assert _only(_hand_surface(policy=None), _hand_surface(policy=admins))["widens"] is True
    signed_out = dict(admins, authenticated=False)
    assert _only(_hand_surface(policy=admins), _hand_surface(policy=signed_out))["widens"] is True
    for unplaceable in ("role:ghost", "permission:no.such", "something-else"):
        moved = dict(admins, read=unplaceable)
        assert _only(_hand_surface(policy=admins), _hand_surface(policy=moved))["widens"] is True
    renamed = _only(
        _hand_surface(_endpoint({"viewer": "allowed"})),
        _hand_surface(_endpoint({"viewer": "allowed_in_module"})),
    )
    assert renamed["widens"] is False
    assert "answers per rung changed" in renamed["change"]


def test_an_unreadable_baseline_is_red_and_says_to_restore_it(tmp_path: pathlib.Path) -> None:
    """An empty file is what a failed `> authz-surface.json` leaves behind. It was a crash;
    now it is a red check that says to restore the committed file rather than write over
    it, which would accept whatever the app serves now."""
    (tmp_path / SURFACE_ARTIFACT).write_text("", encoding="utf-8")
    result = verdict(tmp_path, "app.main:build", "note: ")
    assert result.exit_code == 1
    assert result.fields["authority_state"] == "unseen"
    assert [item["kind"] for item in result.fields["authority_unseen"]] == ["unreadable_baseline"]
    assert "Restore the committed file" in result.output
    (tmp_path / SURFACE_ARTIFACT).write_text("[]", encoding="utf-8")
    shaped = verdict(tmp_path, "app.main:build", "note: ")
    assert (shaped.exit_code, shaped.fields["authority_state"]) == (1, "unseen")
    assert "not a surface" in shaped.output
