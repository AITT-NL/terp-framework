"""``terp verify`` — the one-command gate over declared profiles.

The profile table is the single source of truth for "what does green mean":
these assertions hold its shape (profiles ratchet up, categories stay in the
known set, every check declares a scope), the manifest surface a driving tool
configures its gate from, and the runner's verdict/envelope semantics — using
the in-process architecture check so the suite spawns no npm/uv toolchains.
"""

from __future__ import annotations

import json
import pathlib
import shlex
import subprocess
import sys

import pytest

# terp-cli is not pip-installed in the dev venv; inject its src (as the other CLI tests do).
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLI_SRC = _REPO_ROOT / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main, profile_ids, verify_manifest  # noqa: E402
from terp.cli.verify import (  # noqa: E402
    PROFILES,
    VerifyCheck,
    _json_documents,
    _run_api_docs_drift,
    _run_platform_install,
    _run_subprocess,
)

_EXAMPLE_ROOT = _REPO_ROOT / "apps" / "example"

#: The gate categories a driving tool understands (the Studio's issue tabs).
_KNOWN_CATEGORIES = {
    "architecture",
    "backend-tests",
    "frontend-boundaries",
    "build",
    "conformance",
}


# --------------------------------------------------------------------------- #
# the profile table — the declared meaning of green
# --------------------------------------------------------------------------- #
def test_profiles_ratchet_up() -> None:
    # Each profile is a superset of the previous: a stricter tier can never
    # silently drop a check the cheaper tier ran.
    quick, full, release = (
        {check.id for check in PROFILES[name]} for name in ("quick", "full", "release")
    )
    assert profile_ids() == ("quick", "full", "release")
    assert quick < full < release


def test_every_check_is_well_formed() -> None:
    seen_ids: set[str] = set()
    for profile, checks in PROFILES.items():
        for check in checks:
            assert check.category in _KNOWN_CATEGORIES, f"{profile}/{check.id}"
            assert check.command.strip(), f"{profile}/{check.id}: empty command"
            assert check.scope, f"{profile}/{check.id}: a check must declare its input scope"
            seen_ids.add(check.id)
    assert "architecture" in seen_ids


def test_the_full_profile_is_the_template_ci_surface() -> None:
    # The merge bar: architecture gate, backend tests, the delegated AppSec
    # baseline (ADR 0085), and the frontend chain — the exact blocking checks
    # the generated project's CI runs. Dropping one here would make "verify is
    # the source of truth" a lie.
    ids = {check.id for check in PROFILES["full"]}
    assert ids == {
        "platform-install",
        "env-seams",
        "architecture",
        "backend-tests",
        "appsec-baseline",
        # The app's own declared import contracts. In the profile rather than in a
        # second command, because `terp guide package-boundaries` prescribes them and
        # this profile claims to be what CI enforces — an app that followed the guide
        # had a boundary the claim did not cover. No workflow change propagates it:
        # the template's CI runs `terp verify --profile full` and delegates the list.
        "package-boundaries",
        # Is every distribution the app imports one it declares? No Terp rule can
        # answer it — the import-name to distribution-name mapping needs installed
        # metadata — so it is delegated to deptry, and it is BLOCKING here rather
        # than advisory: the failure is a green gate over an undeclared import on a
        # path no test reaches, which is a control or it is nothing.
        "dependency-hygiene",
        "frontend-boundaries",
        "routes-drift",
        # The generated API client is an INPUT to the typecheck below and is
        # gitignored, so a fresh checkout has none: producing it belongs to the
        # profile, not to whatever steps a scaffolded workflow happens to list.
        "api-client",
        "frontend-typecheck",
        "frontend-build",
    }


def test_the_routes_drift_check_runs_before_the_typecheck() -> None:
    """A stale route table (ADR 0092) fails the *typecheck*, on the app's own screens,
    when the real fault is one unregenerated artifact. Ordering the drift check first
    means the author reads "regenerate the route table" instead of a pile of type
    errors in code they just wrote."""
    for profile, checks in PROFILES.items():
        ids = [check.id for check in checks]
        if "routes-drift" in ids and "frontend-typecheck" in ids:
            assert ids.index("routes-drift") < ids.index("frontend-typecheck"), profile


def test_the_api_client_is_generated_before_the_typecheck() -> None:
    """The typed client is generated from the backend contract and gitignored, so a
    fresh checkout has none and `tsc` is the only thing that reads it (Vite erases
    type-only imports, so `build` passes without it). Generating it after the
    typecheck would report a pile of implicit-any errors across the app's own screens
    whose single cause is one artifact that was never written."""
    for profile, checks in PROFILES.items():
        ids = [check.id for check in checks]
        if "api-client" in ids and "frontend-typecheck" in ids:
            assert ids.index("api-client") < ids.index("frontend-typecheck"), profile


def test_every_profile_that_typechecks_the_frontend_generates_its_client() -> None:
    """The pair is the invariant, in both directions: a profile that type-checks
    without generating is measuring a stale artifact (or none at all), which is the
    exact shape of a green gate over a red build."""
    for profile, checks in PROFILES.items():
        ids = {check.id for check in checks}
        assert ("frontend-typecheck" in ids) == ("api-client" in ids), profile


def test_no_manifest_command_needs_a_shell() -> None:
    """A driving tool runs manifest commands as a fixed argv with no shell — the
    Studio does, deliberately, because these execute project-controlled code. A
    composite command therefore cannot run there: `&&` reaches the first program as
    an argument, and its complaint is reported as the app's own red. Checks that
    compose steps publish a self-referential `terp verify --only <id>` instead and
    do the composing inside an in-process runner."""
    for profile, checks in PROFILES.items():
        for check in checks:
            for operator in ("&&", "||", "|", ";"):
                assert operator not in check.command, (
                    f"{profile}/{check.id}: {check.command!r} composes with "
                    f"{operator!r}, which a shell-less driver cannot execute"
                )


def _template_ci() -> str:
    return (
        _REPO_ROOT / "template" / "project" / ".github" / "workflows" / "ci.yml.jinja"
    ).read_text(encoding="utf-8")


def test_the_template_ci_delegates_its_check_list_to_the_profile() -> None:
    """CI installs the toolchain; the profile decides what green means.

    The equivalence between the two used to be maintained by hand — CI restated each
    check's command, and a test here asserted the string was present. That is a mirror,
    not an equivalence, and it holds only for a freshly rendered app: the workflow is
    SCAFFOLDED, so a fielded app's copy freezes at the version it was rendered from
    while its packages keep moving. A check added to a profile then reaches the
    template and this test, and never reaches the app — whose CI goes on reporting
    green over a list years out of date. That is the failure this guard exists for now,
    and the reason it derives the forbidden set from PROFILES rather than naming
    commands: restating any check is the defect, whichever one it is.
    """
    workflow = _template_ci()
    assert "terp verify --profile full" in workflow, (
        "the generated CI must invoke the profile rather than enumerate its checks"
    )
    for profile, checks in PROFILES.items():
        for check in checks:
            if check.command.startswith("terp verify"):
                continue  # the self-referential form IS how CI invokes one check
            assert check.command not in workflow, (
                f"{profile}/{check.id}: the template CI restates this check's command "
                f"({check.command!r}). A restated list freezes at the version an app "
                "was rendered from while its packages move on, so the gate silently "
                "stops verifying whatever was added since. Invoke the profile instead."
            )


def test_the_template_ci_reaches_every_blocking_check() -> None:
    """Delegation is only worth as much as its coverage.

    The profiles CI invokes must between them reach every check meant to block a
    merge. What CI deliberately leaves out is asserted exactly, so a check dropped by
    accident cannot hide behind "it must have been advisory".
    """
    workflow = _template_ci()
    reached = {check.id for check in PROFILES["full"]}
    reached |= {
        check.id for check in PROFILES["release"] if f"--only {check.id}" in workflow
    }
    unreached = {check.id for check in PROFILES["release"]} - reached
    assert unreached == {"dependency-audit-python", "dependency-audit-npm"}, (
        "the only release checks the generated CI may leave unreached are the "
        "dependency audits, which move with advisory databases rather than with the "
        f"change under test — but it also leaves out {sorted(unreached)}"
    )


def test_platform_install_runs_first_in_every_profile() -> None:
    """It decides whether the rest of the run means anything, so nothing may precede
    it. A gate run against a Terp set at two versions proves nothing about the app in
    either direction (ADR 0063): the green is not evidence, and a red may belong to the
    mismatch rather than to the code. This used to be asserted as a `--only
    platform-install` step in the scaffolded workflow, which a fielded app could lose
    by never re-rendering; ordering it here binds every driver of the profile."""
    for profile, checks in PROFILES.items():
        assert checks[0].id == "platform-install", profile


def test_an_adoption_hint_is_readable_in_text_mode(tmp_path: pathlib.Path) -> None:
    """A check that passes by SKIPPING has to say so where people look.

    `routes-drift` passes on an app that has not adopted route types (ADR 0092) and
    carried the "add the routes script" hint only in `--format json`'s output_tail — an
    opt-in announced in machine mode does not get adopted. The `note:` prefix marks
    output worth reading on a PASS; everything else stays quiet, because a passing
    check's output is otherwise a whole test log.
    """
    from terp.cli.verify import NOTE_PREFIX, _run_routes_drift

    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
    exit_code, output = _run_routes_drift(tmp_path)
    assert exit_code == 0, "an unadopted generator must not fail the gate"
    assert output.startswith(NOTE_PREFIX)
    assert "terp-routes" in output


def test_every_adoptable_skip_is_readable_in_text_mode(tmp_path: pathlib.Path) -> None:
    """The rule above, held for EVERY check that passes by skipping — not one of them.

    `routes-drift` got the `note:` treatment when it was reported and `api-docs-drift`
    did not, so `docs/ not committed - drift check skipped (commit docs/ to enable)`
    stayed invisible in the only mode a human reads. One check fixed is not the rule
    kept: the hint IS the adoption mechanism, so a check that skips silently has no
    way of ever being turned on.

    Asserted per check rather than as a single case, because the failure mode is a new
    skipping check added without the prefix — which no test of one existing check can
    see. The distinction being held is *adoptable* versus *inapplicable*: `no frontend/
    - route types not applicable` stays plain on purpose, because a backend-only app
    has nothing to turn on and a hint there would be noise.
    """
    from terp.cli.verify import (
        NOTE_PREFIX,
        _run_api_client,
        _run_api_docs_drift,
        _run_package_boundaries,
        _run_routes_drift,
    )

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{"scripts": {}}', encoding="utf-8")

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    adoptable = {
        "routes-drift": _run_routes_drift,
        "api-client": _run_api_client,
        "api-docs-drift": _run_api_docs_drift,
        "package-boundaries": _run_package_boundaries,
    }
    for check_id, run in sorted(adoptable.items()):
        exit_code, output = run(tmp_path)
        assert exit_code == 0, f"{check_id}: an unadopted feature must not fail the gate"
        assert output.startswith(NOTE_PREFIX), (
            f"{check_id} passes by skipping but its hint is invisible in text mode — "
            f"the runner only prints a passing check's output when it carries "
            f"{NOTE_PREFIX!r}, so this adoption hint reaches nobody. Got: {output!r}"
        )


def test_a_declared_package_boundary_is_in_the_profile(tmp_path: pathlib.Path) -> None:
    """An app that declares import contracts gets them checked by `terp verify`.

    `terp guide package-boundaries` prescribes import-linter contracts, and this profile
    is documented as exactly what CI enforces. While the linter lived outside the profile
    those two statements contradicted each other, and the app paid: it wrote a pytest
    wrapper shelling out to the console script, or forgot the command and shipped a
    boundary nothing verified.

    Three states, and the middle one is the point:

    * no contracts declared → skip with a note, because an upgrade must not fail a gate
      for a seam the app never wired;
    * contracts declared, linter missing → RED. A declared boundary that cannot be
      checked is not a boundary, and answering "ok" there is the exact failure this
      check removes;
    * contracts declared and runnable → the linter's own verdict.

    The table is read as TOML, not matched as text: `[[tool.importlinter.contracts]]`
    alone creates the table, so an app that declares only contracts is still covered —
    and the word appearing in a comment is not.
    """
    from terp.cli.verify import PROFILES, _run_package_boundaries

    for profile, checks in PROFILES.items():
        ids = [check.id for check in checks]
        assert "package-boundaries" in ids, (
            f"{profile} does not run the app's declared package graph, so an app that "
            "followed `terp guide package-boundaries` has a boundary this profile "
            "claims to enforce and does not"
        )
        assert ids.index("package-boundaries") > ids.index("architecture"), (
            f"{profile}: the app's own graph is checked after Terp's own rules"
        )

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    exit_code, output = _run_package_boundaries(tmp_path)
    assert exit_code == 0, "an app with no contracts must not fail the gate"
    assert "importlinter" in output

    # Declared through the contracts array alone — the table is implicit, and a text
    # match for the section header would miss it.
    (tmp_path / "pyproject.toml").write_text(
        '[[tool.importlinter.contracts]]\nname = "c"\n', encoding="utf-8"
    )
    exit_code, output = _run_package_boundaries(tmp_path)
    assert exit_code != 0, (
        "contracts are declared, so the check must reach the linter and report its "
        f"verdict rather than skipping; got exit 0 with {output!r}"
    )


def test_a_mixed_install_fails_the_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Lockstep (ADR 0063) makes a disagreeing set a forgotten pin, not a supported
    combination — so it is refused, not reported. `terp --version` already warned
    about this, but a warning in a command nobody runs before shipping is not a
    control."""
    import terp.cli.version as version_module

    monkeypatch.setattr(
        version_module,
        "installed_terp_versions",
        lambda: {"terp-core": "0.5.4", "terp-cli": "0.5.4", "terp-cap-oidc": "0.5.3"},
    )
    exit_code, output = _run_platform_install(tmp_path)
    assert exit_code == 1
    assert "terp-cap-oidc" in output, "the failure must name the package that disagrees"
    assert "0.5.4" in output, "and the version the rest of the set is on"

    monkeypatch.setattr(
        version_module,
        "installed_terp_versions",
        lambda: {"terp-core": "0.5.4", "terp-cli": "0.5.4"},
    )
    assert _run_platform_install(tmp_path)[0] == 0


def test_an_undescribable_environment_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The CLI running the check is itself a ``terp-*`` distribution, so an empty set
    means the environment cannot describe itself. Passing would make the check
    weakest exactly where the install is most broken."""
    import terp.cli.version as version_module

    monkeypatch.setattr(version_module, "installed_terp_versions", dict)
    assert _run_platform_install(tmp_path)[0] == 1


def _backend_consistent_at(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    import terp.cli.version as version_module

    monkeypatch.setattr(
        version_module,
        "installed_terp_versions",
        lambda: {"terp-core": version, "terp-cli": version},
    )


def _write_manifest(path: pathlib.Path, dependencies: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": "x", "dependencies": dependencies}), encoding="utf-8")


def test_a_frontend_package_left_behind_fails_the_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The mixed install by the other route, which used to pass green.

    The check read only ``metadata.distributions()`` — backend wheels — so an app
    with ``@terpjs/react-core`` pinned a release behind ``terp-core`` sailed
    through this gate AND the full profile: a fresh CI install would build the
    frontend against a platform combination that was never released, with a
    green gate as evidence. The changelog's lockstep claim was, for an app,
    unenforced.
    """
    _backend_consistent_at(monkeypatch, "0.6.0")
    _write_manifest(
        tmp_path / "frontend" / "package.json", {"@terpjs/react-core": "^0.5.7"}
    )
    exit_code, output = _run_platform_install(tmp_path)
    assert exit_code == 1
    assert "frontend/package.json" in output
    assert "@terpjs/react-core" in output
    assert "^0.6.0" in output, "the failure must state the fix"

    _write_manifest(
        tmp_path / "frontend" / "package.json", {"@terpjs/react-core": "^0.6.0"}
    )
    exit_code, output = _run_platform_install(tmp_path)
    assert exit_code == 0
    assert "1 frontend manifest" in output


def test_every_manifest_declaring_terpjs_is_covered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The template ships @terpjs/* pins in TWO manifests; a check that named
    only frontend/package.json would leave conformance/package.json to go stale
    — the recipe's step 3 made exactly that mistake, so the gate discovers."""
    _backend_consistent_at(monkeypatch, "0.6.0")
    _write_manifest(
        tmp_path / "frontend" / "package.json", {"@terpjs/react-core": "^0.6.0"}
    )
    _write_manifest(
        tmp_path / "conformance" / "package.json", {"@terpjs/conformance": "^0.5.7"}
    )
    exit_code, output = _run_platform_install(tmp_path)
    assert exit_code == 1
    assert "conformance/package.json" in output


def test_the_pre_rename_npm_scope_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """`@terp/*` predates the rename and nothing was ever published under it, so a
    surviving declaration does not resolve to an older release — it 404s, and the job
    that installs it dies before verifying anything. The lockstep scan cannot see it:
    that scan collects manifests BY their `@terpjs/*` declarations, so a manifest
    holding only legacy names is never even opened, and this check reported green on a
    tree no registry could satisfy."""
    _backend_consistent_at(monkeypatch, "0.7.0")
    _write_manifest(
        tmp_path / "frontend" / "package.json", {"@terpjs/react-core": "^0.7.0"}
    )
    _write_manifest(
        tmp_path / "conformance" / "package.json", {"@terp/conformance": "^0.1.0"}
    )
    exit_code, output = _run_platform_install(tmp_path)
    assert exit_code == 1
    assert "conformance/package.json" in output
    assert "@terpjs/conformance" in output, "the fix must name the renamed package"


def test_the_current_scope_is_not_mistaken_for_the_legacy_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """`@terpjs/` shares a prefix with `@terp/`; the trailing slash is what separates
    them, so a correctly-pinned app must not trip the legacy refusal."""
    _backend_consistent_at(monkeypatch, "0.7.0")
    _write_manifest(
        tmp_path / "frontend" / "package.json", {"@terpjs/react-core": "^0.7.0"}
    )
    assert _run_platform_install(tmp_path)[0] == 0


def test_a_stale_installed_copy_fails_even_when_the_range_is_right(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Repinning without reinstalling leaves node_modules on the old release —
    the declared range then reads correct while the build still uses the mix."""
    _backend_consistent_at(monkeypatch, "0.6.0")
    _write_manifest(
        tmp_path / "frontend" / "package.json", {"@terpjs/react-core": "^0.6.0"}
    )
    installed = (
        tmp_path / "frontend" / "node_modules" / "@terpjs" / "react-core" / "package.json"
    )
    installed.parent.mkdir(parents=True)
    installed.write_text(
        json.dumps({"name": "@terpjs/react-core", "version": "0.5.7"}), encoding="utf-8"
    )
    exit_code, output = _run_platform_install(tmp_path)
    assert exit_code == 1
    assert "installed at 0.5.7" in output


def test_an_unreadable_manifest_is_not_a_lockstep_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A package.json this gate cannot parse says nothing about the lockstep.

    ``rglob`` walks the whole app, so it meets manifests the gate does not own —
    a fixture's deliberately broken JSON, a half-written file. Failing on them
    would report someone else's problem as a platform-mix failure; the walk
    skips them and keeps judging the manifests it could read.
    """
    _backend_consistent_at(monkeypatch, "0.6.0")
    _write_manifest(
        tmp_path / "frontend" / "package.json", {"@terpjs/react-core": "^0.6.0"}
    )
    broken = tmp_path / "fixtures" / "package.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{not json", encoding="utf-8")
    exit_code, output = _run_platform_install(tmp_path)
    assert exit_code == 0
    assert "1 frontend manifest" in output


def test_the_independently_released_spec_mirror_is_not_a_missed_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """@terpjs/spec is the npm mirror of terp-spec: its own cadence, its own
    version — the same exclusion the backend half already makes."""
    _backend_consistent_at(monkeypatch, "0.6.0")
    _write_manifest(tmp_path / "frontend" / "package.json", {"@terpjs/spec": "^0.24.0"})
    assert _run_platform_install(tmp_path)[0] == 0


def test_the_platform_install_check_runs_in_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It reads installed metadata, so it costs no subprocess and no toolchain —
    which is why it can lead every profile, including the cheapest."""
    monkeypatch.setitem(PROFILES, "quick", (PROFILES["quick"][0],))
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "quick", "--root", str(tmp_path), "--format", "json"])
    assert excinfo.value.code == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check["id"] == "platform-install" and check["ok"] is True


# --------------------------------------------------------------------------- #
# the manifest — what a driving tool configures its gate from
# --------------------------------------------------------------------------- #
def test_manifest_lists_the_profile_checks() -> None:
    manifest = verify_manifest("release")
    assert manifest["terp_verify_manifest"] == 1
    entries = {entry["id"]: entry for entry in manifest["checks"]}
    assert entries["conformance"]["requires"], (
        "the conformance check must state its workbench precondition"
    )
    assert "requires" not in entries["architecture"]
    assert entries["architecture"]["scope"] == [
        "app/**",
        "control_plane/**",
        "escape-hatch-budget.json",
    ]


def test_manifest_refuses_an_unknown_profile() -> None:
    with pytest.raises(SystemExit, match="unknown profile"):
        verify_manifest("nightly")


def test_cli_list_prints_the_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "full", "--list", "--format", "json"])
    assert excinfo.value.code == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["profile"] == "full"
    assert [entry["id"] for entry in manifest["checks"]] == [
        check.id for check in PROFILES["full"]
    ]


# --------------------------------------------------------------------------- #
# the runner — verdicts, the terp_verify envelope, embedded check reports
# --------------------------------------------------------------------------- #
def test_verify_architecture_only_is_green_on_the_example_app(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "verify",
                "--profile",
                "quick",
                "--root",
                str(_EXAMPLE_ROOT),
                "--only",
                "architecture",
                "--format",
                "json",
            ]
        )
    assert excinfo.value.code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["terp_verify"] == 1
    assert envelope["ok"] is True
    (check,) = envelope["checks"]
    assert check["id"] == "architecture" and check["ok"] is True
    # The embedded machine document: the Terp Standard check report, carried
    # structurally so a consumer never re-parses the output tail.
    (report,) = check["reports"]
    assert report["terp_check_report"] == 1
    assert report["ok"] is True


def test_verify_fails_red_with_findings_on_a_violating_app(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = tmp_path / "app"
    module = app / "modules" / "billing"
    module.mkdir(parents=True)
    (module / "module.py").write_text(
        "module = ModuleSpec(name='billing', router=router)\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "verify",
                "--profile",
                "quick",
                "--root",
                str(tmp_path),
                "--only",
                "architecture",
                "--format",
                "json",
            ]
        )
    assert excinfo.value.code == 1
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is False
    (check,) = envelope["checks"]
    (report,) = check["reports"]
    assert {finding["rule"] for finding in report["findings"]} >= {
        "backend/modules_declare_policy"
    }


def test_verify_refuses_an_unknown_only_selection() -> None:
    with pytest.raises(SystemExit, match="names no check"):
        main(["verify", "--profile", "quick", "--only", "nonexistent"])


def test_a_missing_executable_fails_visibly() -> None:
    check = VerifyCheck(
        id="ghost",
        category="build",
        command="definitely-missing-terp-binary-xyz --flag",
        scope=("frontend/**",),
    )
    exit_code, output = _run_subprocess(check, pathlib.Path("."))
    assert exit_code == 127
    assert "not found" in output


def test_json_documents_finds_indented_and_inline_docs() -> None:
    stdout = "\n".join(
        [
            "prose before",
            '{"terp_findings": 1, "rules": []}',
            "{",
            '  "terp_check_report": 1,',
            '  "ok": true',
            "}",
            "prose { not json } after",
        ]
    )
    documents = _json_documents(stdout)
    markers = [next(iter(doc)) for doc in documents]
    assert "terp_findings" in markers and "terp_check_report" in markers


# --------------------------------------------------------------------------- #
# the subprocess/api-docs runners + the human (text) surfaces
# --------------------------------------------------------------------------- #
def _python_check(check_id: str, code: str, *, category: str = "build") -> VerifyCheck:
    """A profile check running this interpreter (portable: no npm/uv spawn)."""
    return VerifyCheck(
        id=check_id,
        category=category,
        command=f'"{pathlib.Path(sys.executable).as_posix()}" -c "{code}"',
        scope=("app/**",),
    )


def test_subprocess_checks_carry_their_published_documents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A subprocess check's stdout documents (here a legacy terp_findings
    # envelope) are parsed out and carried structurally in the terp_verify
    # envelope — the consumer never re-derives them from the output tail.
    envelope_code = (
        "import json; print(json.dumps({'terp_findings': 1, 'rules': []}))"
    )
    monkeypatch.setitem(
        PROFILES, "quick", (_python_check("fake-lint", envelope_code),)
    )
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "quick", "--root", str(tmp_path), "--format", "json"])
    assert excinfo.value.code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is True
    (check,) = envelope["checks"]
    assert check["id"] == "fake-lint" and check["exit_code"] == 0
    (report,) = check["reports"]
    assert report["terp_findings"] == 1


def test_text_mode_prints_the_failing_tail_and_the_verdict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The human surface: a failing check's output tail lands on stderr and the
    # run ends with the profile verdict — RED here, green on a passing rerun.
    failing = "import sys; print('the build exploded'); sys.exit(3)"
    monkeypatch.setitem(PROFILES, "quick", (_python_check("fake-build", failing),))
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "quick", "--root", str(tmp_path)])
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "the build exploded" in captured.err
    assert "profile quick is RED" in captured.err

    monkeypatch.setitem(
        PROFILES, "quick", (_python_check("fake-build", "print('ok')"),)
    )
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "quick", "--root", str(tmp_path)])
    assert excinfo.value.code == 0
    assert "profile quick is green" in capsys.readouterr().err


def test_cli_list_prints_the_human_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    # `--list` without --format json: the same manifest for human eyes,
    # including each check's requires note — and still runs nothing.
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "release", "--list"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "profile release:" in out
    for check in PROFILES["release"]:
        assert check.id in out
    assert "[requires the Docker workbench" in out


def _git(root: pathlib.Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_api_docs_drift_check_detects_a_stale_committed_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    # The release-profile drift pair: regenerate docs/ (in the project root)
    # and fail when the committed copy differs. api_docs itself boots the
    # project's kernel — faked here; the check's own contract is the chdir +
    # regenerate + `git diff --exit-code -- docs` choreography.
    import terp.cli

    root = tmp_path
    docs = root / "docs"
    docs.mkdir()
    (docs / "api.md").write_text("old\n", encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "committed docs")

    def fake_api_docs(out: str) -> list[pathlib.Path]:
        target = pathlib.Path(out) / "api.md"
        target.write_text("regenerated\n", encoding="utf-8")
        return [target]

    monkeypatch.setattr(terp.cli, "api_docs", fake_api_docs)
    exit_code, output = _run_api_docs_drift(root)
    assert exit_code != 0
    assert "wrote" in output and "drifted from the committed copy" in output
    # And the clean case: regenerating exactly the committed content passes.
    (docs / "api.md").write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(
        terp.cli, "api_docs", lambda out: [pathlib.Path(out) / "api.md"]
    )
    exit_code, output = _run_api_docs_drift(root)
    assert exit_code == 0


def test_api_docs_drift_is_a_noop_until_docs_are_committed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No docs/ directory = the pair is not enabled yet: success with a hint,
    # exercised through the profile dispatch (the "api-docs-drift" runner).
    from terp.cli.verify import _API_DOCS_DRIFT

    monkeypatch.setitem(PROFILES, "quick", (_API_DOCS_DRIFT,))
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "quick", "--root", str(tmp_path), "--format", "json"])
    assert excinfo.value.code == 0
    envelope = json.loads(capsys.readouterr().out)
    (check,) = envelope["checks"]
    assert check["ok"] is True
    assert "drift check skipped" in check["output_tail"]


# --------------------------------------------------------------------------- #
# the assurance profile — the release claim (assurance-profile.schema.json)
# --------------------------------------------------------------------------- #
def _assurance_schema() -> dict:
    from terp_spec import spec_dir

    return json.loads(
        (spec_dir() / "assurance-profile.schema.json").read_text(encoding="utf-8")
    )


def test_assurance_lanes_mirror_the_pinned_spec_vocabulary() -> None:
    """The lane constants are the spec's normative vocabulary, in order —
    mirrored here (with the requirement mapping from the spec README's
    assurance table) and held to the pinned schema so they cannot drift."""
    from terp.cli.verify import ASSURANCE_LANES

    schema = _assurance_schema()
    enum = schema["properties"]["lanes"]["items"]["properties"]["id"]["enum"]
    assert [lane_id for lane_id, _requirement, _checks in ASSURANCE_LANES] == list(enum)
    assert {req for _lane, req, _checks in ASSURANCE_LANES} == {"required", "recommended"}


def test_assurance_lanes_compose_only_release_profile_checks() -> None:
    """Every composing check id is a member of the release profile — the run
    the claim is emitted from always carries a verdict for every realised
    lane (an absent verdict can therefore never be misread as a pass)."""
    from terp.cli.verify import ASSURANCE_LANES

    release_ids = {check.id for check in PROFILES["release"]}
    for lane_id, _requirement, check_ids in ASSURANCE_LANES:
        assert set(check_ids) <= release_ids, f"{lane_id} composes unknown checks"
    # The required lanes are realised by this toolchain; a11y is declared
    # not-run until its integration lands — never silently dropped.
    composed = {lane: checks for lane, _req, checks in ASSURANCE_LANES}
    assert composed["terp-standard"] and composed["appsec-baseline"]
    assert composed["dependency-audit"]
    assert composed["a11y"] == ()


def _release_stub_profile(ok_ids: set[str], fail_ids: set[str]) -> tuple[VerifyCheck, ...]:
    """The release profile's check ids as fast interpreter stubs."""
    checks = []
    for check in PROFILES["release"]:
        code = "pass" if check.id in ok_ids else "import sys; sys.exit(1)"
        if check.id in ok_ids or check.id in fail_ids:
            checks.append(_python_check(check.id, code, category=check.category))
    return tuple(checks)


def test_assurance_emission_claims_on_required_lanes_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Every release check green except conformance (a recommended lane): the
    # claim HOLDS (exit 0) while the document reports the red lane honestly.
    release_ids = {check.id for check in PROFILES["release"]}
    monkeypatch.setitem(
        PROFILES,
        "release",
        _release_stub_profile(release_ids - {"conformance"}, {"conformance"}),
    )
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "release", "--root", str(tmp_path), "--format", "assurance"])
    assert excinfo.value.code == 0
    document = json.loads(capsys.readouterr().out)
    schema = _assurance_schema()
    assert set(schema["required"]) <= set(document)
    assert set(document) <= set(schema["properties"])
    assert document["terp_assurance"] == 1
    assert document["ok"] is True
    assert document["profile"] == "release"
    lanes = {lane["id"]: lane for lane in document["lanes"]}
    assert [lane["id"] for lane in document["lanes"]] == list(
        schema["properties"]["lanes"]["items"]["properties"]["id"]["enum"]
    )
    assert lanes["terp-standard"]["status"] == "passed"
    assert lanes["dependency-audit"]["status"] == "passed"
    assert lanes["dependency-audit"]["checks"] == [
        "dependency-audit-python",
        "dependency-audit-npm",
    ]
    assert lanes["blackbox-conformance"]["status"] == "failed"
    assert lanes["a11y"] == {"id": "a11y", "status": "not-run", "checks": []}


def test_assurance_emission_fails_the_claim_on_a_red_required_lane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    release_ids = {check.id for check in PROFILES["release"]}
    monkeypatch.setitem(
        PROFILES,
        "release",
        _release_stub_profile(
            release_ids - {"dependency-audit-npm"}, {"dependency-audit-npm"}
        ),
    )
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "release", "--root", str(tmp_path), "--format", "assurance"])
    assert excinfo.value.code == 1
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is False
    lanes = {lane["id"]: lane for lane in document["lanes"]}
    # One red composing check fails the whole lane — never a partial pass.
    assert lanes["dependency-audit"]["status"] == "failed"


def test_assurance_refuses_partial_runs() -> None:
    """A partial run can never quietly become a release claim: any profile but
    release, an --only subset, and --list are each refused outright."""
    for argv in (
        ["verify", "--profile", "quick", "--format", "assurance"],
        ["verify", "--profile", "release", "--only", "architecture", "--format", "assurance"],
        ["verify", "--profile", "release", "--list", "--format", "assurance"],
    ):
        with pytest.raises(SystemExit, match="never become a release claim"):
            main(argv)


def test_assurance_toolchain_versions_a_source_checkout_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same fallback as check_report_envelope: no installed terp-cli
    # distribution => toolchain version "0", never a crash.
    import importlib.metadata

    from terp.cli.verify import assurance_document

    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", missing)
    document = assurance_document([])
    assert document["toolchain"] == {"tool": "terp-verify", "version": "0"}
    # No results at all: every realised lane fails, the unrealised stays not-run.
    lanes = {lane["id"]: lane["status"] for lane in document["lanes"]}
    assert lanes["terp-standard"] == "failed" and lanes["a11y"] == "not-run"
    assert document["ok"] is False


def test_verify_dispatches_env_seams_through_its_own_runner(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`env-seams` is an in-process runner, not a subprocess like most checks, so the
    dispatcher has a branch of its own for it. Everything else about the check is proven
    in test_cli_env_seams.py against the function directly — this proves `terp verify`
    actually reaches that function instead of shelling out to a command that does not exist.
    """
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "verify",
                "--profile",
                "quick",
                "--root",
                str(tmp_path),
                "--only",
                "env-seams",
                "--format",
                "json",
            ]
        )
    assert excinfo.value.code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is True
    # The no-op success shape for an app that declares nothing, reached in-process.
    assert "not applicable" in json.dumps(envelope)


# --------------------------------------------------------------------------- #
# the api-client runner
#
# It generates the typed client the frontend typecheck downstream of it reads, so it
# is ordered first in every profile that type-checks — and its verdict is "can this
# be produced at all", not a drift diff, because the client is gitignored.
# --------------------------------------------------------------------------- #
def _generating_frontend(root: pathlib.Path) -> pathlib.Path:
    """A frontend that declares the codegen script and looks installed.

    No lockfile on purpose: `_node_modules_problem` returns None without one, which
    keeps these tests about the runner rather than about the platform diagnosis that
    has its own suite.
    """
    frontend = root / "frontend"
    (frontend / "node_modules").mkdir(parents=True)
    (frontend / "package.json").write_text(
        json.dumps({"scripts": {"generate": "openapi-typescript ../openapi.json"}}),
        encoding="utf-8",
    )
    return frontend


def test_an_app_with_no_frontend_skips_the_client_rather_than_failing(
    tmp_path: pathlib.Path,
) -> None:
    """Upgrading the framework must not fail a gate for a seam the app never wired."""
    from terp.cli.verify import _run_api_client

    exit_code, output = _run_api_client(tmp_path)

    assert exit_code == 0
    assert "not applicable" in output


def test_an_unreadable_frontend_manifest_is_a_red_that_says_which_file(
    tmp_path: pathlib.Path,
) -> None:
    """Not a skip: whether this app generates a client cannot be established, and a
    check that cannot reach its own subject must not report green."""
    from terp.cli.verify import _run_api_client

    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{not json", encoding="utf-8")

    exit_code, output = _run_api_client(tmp_path)

    assert exit_code == 1
    assert "frontend/package.json" in output
    assert "unreadable" in output


def test_a_frontend_without_the_generate_script_skips_with_the_adoption_hint(
    tmp_path: pathlib.Path,
) -> None:
    """The `note:` prefix, for the same reason routes-drift carries one: an opt-in
    announced only in JSON does not get adopted."""
    from terp.cli.verify import NOTE_PREFIX, _run_api_client

    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"scripts": {}}', encoding="utf-8")

    exit_code, output = _run_api_client(tmp_path)

    assert exit_code == 0
    assert output.startswith(NOTE_PREFIX)
    assert "openapi-typescript" in output, "the hint has to name what to add"


def test_a_broken_install_is_diagnosed_before_npm_is_spawned(
    tmp_path: pathlib.Path,
) -> None:
    """Ordered ahead of the spawn deliberately: by the time npm has run, the reader is
    already looking at a module-resolution trace instead of the fix."""
    from terp.cli.verify import _run_api_client

    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"generate": "openapi-typescript"}}), encoding="utf-8"
    )

    exit_code, output = _run_api_client(tmp_path)

    assert exit_code == 1
    assert "npm --prefix frontend ci" in output


def test_an_app_ref_that_resolves_to_no_fastapi_app_is_a_red_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """export_openapi refuses with SystemExit; the runner turns that into a verdict, or
    the profile would abort mid-run and the remaining checks would never report."""
    import terp.cli.openapi as openapi_module
    from terp.cli.verify import _run_api_client

    _generating_frontend(tmp_path)

    def refuse(**_kwargs: object) -> pathlib.Path:
        raise SystemExit("no app at app.main:build")

    monkeypatch.setattr(openapi_module, "export_openapi", refuse)

    exit_code, output = _run_api_client(tmp_path)

    assert exit_code == 1
    assert "could not export the OpenAPI document" in output
    assert "no app at app.main:build" in output


def _stub_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, *, returncode: int
) -> list[dict[str, object]]:
    """Stub the export and the npm spawn, recording how the spawn was invoked."""
    import terp.cli.openapi as openapi_module
    import terp.cli.verify as verify_module

    monkeypatch.setattr(
        openapi_module, "export_openapi", lambda **_k: tmp_path / "openapi.json"
    )
    calls: list[dict[str, object]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(argv, returncode, "generated 1 file\n", "")

    monkeypatch.setattr(verify_module.subprocess, "run", fake_run)
    return calls


def test_the_client_is_generated_from_the_app_root_and_reports_what_it_wrote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    from terp.cli.verify import _run_api_client

    _generating_frontend(tmp_path)
    calls = _stub_generation(monkeypatch, tmp_path, returncode=0)
    before = pathlib.Path.cwd()

    exit_code, output = _run_api_client(tmp_path)

    assert exit_code == 0
    assert "wrote openapi.json" in output
    assert "generated 1 file" in output, "npm's own output has to reach the reader"
    (call,) = calls
    assert call["argv"][1:] == ["--prefix", "frontend", "run", "generate"]
    assert call["shell"] is not True if "shell" in call else True
    assert pathlib.Path.cwd() == before, "the chdir must be undone even on the happy path"


def test_a_failed_generation_says_why_the_typecheck_after_it_would_mislead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The ordering is load-bearing, so the failure explains it: a red typecheck
    downstream of a missing client is a verdict about the client, not about the app."""
    from terp.cli.verify import _run_api_client

    _generating_frontend(tmp_path)
    _stub_generation(monkeypatch, tmp_path, returncode=2)

    exit_code, output = _run_api_client(tmp_path)

    assert exit_code == 2
    assert "frontend typecheck" in output


def test_the_profile_dispatches_the_api_client_runner_in_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The runner is reached by its `runner` tag, not by shelling out to its `command`
    — which is what lets the check hold a callable and still publish a command a
    reader can run by hand."""
    api_client = VerifyCheck(
        id="api-client",
        category="build",
        command="terp verify --only api-client",
        runner="api-client",
    )
    monkeypatch.setitem(PROFILES, "quick", (api_client,))

    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "quick", "--root", str(tmp_path), "--format", "json"])

    assert excinfo.value.code == 0
    (check,) = json.loads(capsys.readouterr().out)["checks"]
    assert check["id"] == "api-client"
    assert "not applicable" in check["output_tail"], "the runner ran, not its command string"


def test_the_package_graph_check_is_reachable_through_the_runner(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Through `--only`, so the dispatch wiring is exercised and not just the function.

    A runner tag that is declared on the check and missing from the dispatch falls through
    to the generic subprocess branch, which would run `lint-imports` unconditionally —
    the conditional skip is the whole point of having a runner at all, and a unit test on
    the function cannot see that the wiring reaches it.
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "verify",
                "--profile",
                "quick",
                "--root",
                str(tmp_path),
                "--only",
                "package-boundaries",
                "--format",
                "json",
            ]
        )
    assert excinfo.value.code == 0
    envelope = json.loads(capsys.readouterr().out)
    [check] = envelope["checks"]
    assert check["id"] == "package-boundaries" and check["ok"] is True
    # The skip's note travels in the envelope, which is what makes it adoptable.
    assert "importlinter" in check["output_tail"]


def test_the_package_graph_check_on_a_tree_with_no_manifest_or_a_broken_one(
    tmp_path: pathlib.Path,
) -> None:
    """Two edges, and they answer differently on purpose.

    No `pyproject.toml` at all is *not applicable* — there is nothing to declare
    contracts in, and nothing for the reader to turn on, so it passes plainly rather than
    with an adoption hint. A manifest that exists and cannot be parsed is a RED: whether
    this app declares a package boundary is now unknowable, and answering "ok" to an
    unknowable question is the failure this check exists to remove.
    """
    from terp.cli.verify import NOTE_PREFIX, _run_package_boundaries

    exit_code, output = _run_package_boundaries(tmp_path)
    assert exit_code == 0
    assert not output.startswith(NOTE_PREFIX), (
        "no manifest is inapplicable rather than adoptable; a hint here is noise"
    )

    (tmp_path / "pyproject.toml").write_text("[project\nname = ", encoding="utf-8")
    exit_code, output = _run_package_boundaries(tmp_path)
    assert exit_code == 1
    assert "unreadable" in output


# --------------------------------------------------------------------------- #
# the app's own checks — [[tool.terp.verify.checks]]
# --------------------------------------------------------------------------- #
def _declaring(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    """A project root whose pyproject.toml carries *body*."""
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    return tmp_path


_SIDECAR = """
[[tool.terp.verify.checks]]
id = "engine-architecture"
command = "terp check --package engine"
profile = "quick"
scope = ["engine/**"]
"""


def test_the_category_vocabulary_is_the_one_a_driving_tool_files() -> None:
    """The set an app check is held to is the set this suite asserts for built-ins.

    Two copies on purpose — the runtime constant and this file's independent
    statement of the contract — so a category added on one side without the
    other is loud rather than a tab in Studio that silently never fills.
    """
    from terp.cli.verify import CHECK_CATEGORIES

    assert set(CHECK_CATEGORIES) == _KNOWN_CATEGORIES


def test_an_app_can_declare_a_check_of_its_own(tmp_path: pathlib.Path) -> None:
    """The profile is a floor, not a ceiling.

    Before this seam, an app with a check of its own — a sidecar package's
    architecture scan, a domain invariant, a generated-artifact drift test — had
    to put it in a pytest wrapper or a CI step outside the one command documented
    as what green means. Both leave the app's own gate where nothing driving the
    project through the manifest looks.
    """
    from terp.cli.verify import app_declared_checks, profile_checks

    root = _declaring(tmp_path, _SIDECAR)
    ((check, declared_profile),) = app_declared_checks(root)
    assert (check.id, declared_profile) == ("engine-architecture", "quick")
    assert check.category == "architecture", "the default category"
    assert check.command == "terp check --package engine"
    assert check.scope == ("engine/**",)

    # It rides the ratchet from the profile it names, exactly as a built-in does.
    for profile in profile_ids():
        assert profile_checks(profile, root)[-1].id == "engine-architecture"
    # ...and runs AFTER the platform's floor, so a red from Terp's own rules
    # still reports first.
    assert [check.id for check in PROFILES["quick"]] == [
        check.id for check in profile_checks("quick", root)[:-1]
    ]


def test_a_declared_check_joins_only_its_profile_and_above(
    tmp_path: pathlib.Path,
) -> None:
    from terp.cli.verify import profile_checks

    root = _declaring(
        tmp_path,
        """
[[tool.terp.verify.checks]]
id = "domain-invariants"
command = "uv run pytest tests/invariants"
profile = "release"
scope = ["app/**"]
category = "backend-tests"
requires = "a seeded database"
""",
    )
    assert "domain-invariants" not in {c.id for c in profile_checks("quick", root)}
    assert "domain-invariants" not in {c.id for c in profile_checks("full", root)}
    (declared,) = [
        c for c in profile_checks("release", root) if c.id == "domain-invariants"
    ]
    assert declared.requires == "a seeded database"


def test_the_platform_floor_is_what_the_profile_means_without_an_app(
    tmp_path: pathlib.Path,
) -> None:
    from terp.cli.verify import profile_checks

    assert profile_checks("quick") == PROFILES["quick"]
    # An app that never adopted the seam is untouched: upgrading the framework
    # must not add a check to a gate nobody declared.
    assert profile_checks("quick", _declaring(tmp_path, "[project]\nname='x'\n")) == (
        PROFILES["quick"]
    )
    # Neither does a project with no pyproject.toml at all.
    assert profile_checks("quick", tmp_path / "nowhere") == PROFILES["quick"]


def test_profile_checks_refuses_an_unknown_profile() -> None:
    from terp.cli.verify import profile_checks

    with pytest.raises(SystemExit, match="unknown profile"):
        profile_checks("nightly")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "architecture"\n'
            'command = "true"\nprofile = "quick"\nscope = ["app/**"]\n',
            "already a Terp check",
            id="an app check may not shadow a platform check's id",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\n'
            'command = "true"\nprofil = "quick"\nscope = ["engine/**"]\n',
            "unknown key",
            id="a typo is refused, never ignored",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "Engine_Arch"\n'
            'command = "true"\nprofile = "quick"\nscope = ["engine/**"]\n',
            "lowercase words joined by hyphens",
            id="an id that does not read like a check id",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = 3\n'
            'command = "true"\nprofile = "quick"\nscope = ["engine/**"]\n',
            "lowercase words joined by hyphens",
            id="an id that is not a string",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\n'
            'command = "   "\nprofile = "quick"\nscope = ["engine/**"]\n',
            "non-empty `command`",
            id="a command that splits to no argv",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\n'
            'command = "lint . && test ."\nprofile = "quick"\n'
            'scope = ["engine/**"]\n',
            "no shell",
            id="a command separator, which would become an argument",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\n'
            'command = 7\nprofile = "quick"\nscope = ["engine/**"]\n',
            "non-empty `command`",
            id="a command that is not a string",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\n'
            'command = "true"\nprofile = "nightly"\nscope = ["engine/**"]\n',
            "cheapest profile it joins",
            id="a profile outside the ratchet",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\ncommand = "true"\n'
            'profile = "quick"\nscope = ["engine/**"]\ncategory = "vibes"\n',
            "no driving tool can file",
            id="a category with no tab to land in",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\n'
            'command = "true"\nprofile = "quick"\nscope = "engine/**"\n',
            "list of globs",
            id="a scope that is not a list",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\n'
            'command = "true"\nprofile = "quick"\nscope = [3]\n',
            "list of globs",
            id="a scope holding something that is not a glob",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\n'
            'command = "true"\nprofile = "quick"\nscope = []\n',
            "non-empty `scope`",
            id="no declared inputs, so no safe skip",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\ncommand = "true"\n'
            'profile = "quick"\nscope = ["engine/**"]\nrequires = 1\n',
            "`requires` to be a string",
            id="a precondition that is not prose",
        ),
        pytest.param(
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\ncommand = "true"\n'
            'profile = "quick"\nscope = ["engine/**"]\n\n'
            '[[tool.terp.verify.checks]]\nid = "engine-arch"\ncommand = "false"\n'
            'profile = "quick"\nscope = ["engine/**"]\n',
            "declared twice",
            id="the same id declared twice",
        ),
        pytest.param(
            '[tool.terp]\nverify = "yes"\n',
            "not a table",
            id="[tool.terp.verify] is not a table",
        ),
        pytest.param(
            '[tool.terp.verify]\nchecks = 1\n',
            "list of tables",
            id="`checks` is not a list",
        ),
        pytest.param(
            '[tool.terp.verify]\nchecks = [1]\n',
            "is not a table",
            id="an entry that is not a table",
        ),
        pytest.param(
            '[tool.terp.verify]\nprofile = "quick"\n',
            "unknown key",
            id="an unknown key on the table itself",
        ),
        pytest.param(
            "[tool.terp.verify\n",
            "unreadable",
            id="pyproject.toml does not parse",
        ),
    ],
)
def test_a_malformed_declaration_fails_closed(
    tmp_path: pathlib.Path, body: str, expected: str
) -> None:
    """Every refusal above could have been a silent skip, and must not be.

    A seam that drops what it cannot parse hands the app a gate that is green
    because its own check never ran — the precise failure this seam was opened
    to remove, and worse coming from the seam itself. So the reader fails closed
    on every branch and names the entry it refused.
    """
    from terp.cli.verify import app_declared_checks

    with pytest.raises(SystemExit, match=expected):
        app_declared_checks(_declaring(tmp_path, body))


def test_the_manifest_carries_the_apps_checks_too(tmp_path: pathlib.Path) -> None:
    """A driving tool reads the whole gate, not the platform half of it."""
    root = _declaring(tmp_path, _SIDECAR)
    manifest = verify_manifest("quick", root)
    assert manifest["checks"][-1] == {
        "id": "engine-architecture",
        "category": "architecture",
        "command": "terp check --package engine",
        "scope": ["engine/**"],
    }
    assert [entry["id"] for entry in verify_manifest("quick")["checks"]] == [
        check.id for check in PROFILES["quick"]
    ], "without a root, the manifest is the platform floor"


def test_cli_list_shows_a_declared_check(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _declaring(tmp_path, _SIDECAR)
    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--profile", "quick", "--root", str(root), "--list"])
    assert excinfo.value.code == 0
    assert "engine-architecture" in capsys.readouterr().out


def test_a_declared_check_runs_and_carries_the_verdict(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The point of the seam: the app's own check decides the exit code."""
    failing = tmp_path / "failing.py"
    failing.write_text("raise SystemExit(3)\n", encoding="utf-8")
    root = _declaring(
        tmp_path,
        f"""
[[tool.terp.verify.checks]]
id = "domain-invariants"
command = "{pathlib.Path(sys.executable).as_posix()} {failing.as_posix()}"
profile = "quick"
scope = ["app/**"]
""",
    )
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "verify",
                "--profile",
                "quick",
                "--root",
                str(root),
                "--only",
                "domain-invariants",
                "--format",
                "json",
            ]
        )
    assert excinfo.value.code == 1, "an app's own red is the run's red"
    (result,) = json.loads(capsys.readouterr().out)["checks"]
    assert result["id"] == "domain-invariants" and result["ok"] is False
    assert result["exit_code"] == 3


def test_a_declared_check_composes_into_no_assurance_lane() -> None:
    """The lane vocabulary is normative in the spec.

    An app may extend its own gate; it may not thereby restate — or satisfy — a
    claim the Terp Standard defines. Lanes compose by the ids they NAME, so a
    declared check contributes to none of them by construction.
    """
    from terp.cli.verify import ASSURANCE_LANES, assurance_document

    named = {check_id for _lane, _req, ids in ASSURANCE_LANES for check_id in ids}
    results = [
        {"id": check.id, "ok": True} for check in PROFILES["release"]
    ] + [{"id": "domain-invariants", "ok": False}]
    document = assurance_document(results)
    assert document["ok"] is True, (
        "a red app check must not fail a lane it was never part of"
    )
    assert "domain-invariants" not in named
    for lane in document["lanes"]:
        assert "domain-invariants" not in lane["checks"]


# --------------------------------------------------------------------------- #
# dependency hygiene — delegated, and blocking
# --------------------------------------------------------------------------- #
def test_dependency_hygiene_is_blocking_and_lane_less() -> None:
    """It carries the exit code, and it claims no normative lane.

    Advisory was the status quo and is not a control: the failure this catches is
    a green gate over an undeclared import on a path no test reaches — the app
    runs where a transitive dependency happens to be installed and dies on a
    clean machine. So it lands in the merge bar.

    It joins no assurance lane on purpose. The spec's `dependency-audit` lane is
    normatively "both trees against known-vulnerability databases", which is a
    different question from "is what you import declared"; claiming it there
    would widen a normative lane from the toolchain side.
    """
    from terp.cli.verify import ASSURANCE_LANES

    for profile in ("full", "release"):
        assert "dependency-hygiene" in {check.id for check in PROFILES[profile]}
    assert "dependency-hygiene" not in {check.id for check in PROFILES["quick"]}, (
        "quick is static enforcement over source; this one needs a resolved "
        "environment to map an import name to a distribution"
    )
    for _lane, _requirement, check_ids in ASSURANCE_LANES:
        assert "dependency-hygiene" not in check_ids


def test_dependency_hygiene_is_conditional_on_the_app_declaring_it(
    tmp_path: pathlib.Path,
) -> None:
    from terp.cli.verify import NOTE_PREFIX, _run_dependency_hygiene

    exit_code, output = _run_dependency_hygiene(tmp_path / "nowhere")
    assert (exit_code, "not applicable" in output) == (0, True)

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    exit_code, output = _run_dependency_hygiene(tmp_path)
    assert exit_code == 0, "an app that never adopted deptry must not fail the gate"
    assert output.startswith(NOTE_PREFIX) and "deptry" in output


def test_dependency_hygiene_reads_the_table_rather_than_matching_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Declaring only `[tool.deptry.per_rule_ignores]` still creates the parent
    table — and the word in a comment does not. Same reasoning as the package
    graph check next to it."""
    import terp.cli.verify as verify_module

    reached: list[str] = []
    monkeypatch.setattr(
        verify_module,
        "_run_subprocess",
        lambda check, root: (reached.append(check.id), (0, "clean"))[1],
    )
    (tmp_path / "pyproject.toml").write_text(
        '# tool.deptry in a comment\n[tool.deptry.per_rule_ignores]\nDEP003 = ["x"]\n',
        encoding="utf-8",
    )
    assert verify_module._run_dependency_hygiene(tmp_path) == (0, "clean")
    assert reached == ["dependency-hygiene"]

    reached.clear()
    (tmp_path / "pyproject.toml").write_text(
        "# nothing here declares [tool.deptry] for real\n", encoding="utf-8"
    )
    exit_code, _output = verify_module._run_dependency_hygiene(tmp_path)
    assert (exit_code, reached) == (0, []), "a comment is not a declaration"

    # An empty table is the most ordinary adoption there is — every setting left
    # at its default — and an empty table is falsy. Testing the value rather than
    # the key would skip it silently, which is the fail-open this check exists to
    # prevent, occurring inside the check itself.
    reached.clear()
    (tmp_path / "pyproject.toml").write_text("[tool.deptry]\n", encoding="utf-8")
    assert verify_module._run_dependency_hygiene(tmp_path) == (0, "clean")
    assert reached == ["dependency-hygiene"]


def test_dependency_hygiene_names_the_missing_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Declared-but-unrunnable is a RED that says what to install.

    An app that declared the hygiene and cannot run it has a broken gate;
    reporting that as a pass is the failure the check exists to remove.
    """
    import terp.cli.verify as verify_module

    monkeypatch.setattr(
        verify_module,
        "_run_subprocess",
        lambda check, root: (127, "deptry: executable not found on PATH"),
    )
    (tmp_path / "pyproject.toml").write_text("[tool.deptry]\n", encoding="utf-8")
    exit_code, output = verify_module._run_dependency_hygiene(tmp_path)
    assert exit_code == 127
    assert "checked by nothing" in output and 'add "deptry>=0.20"' in output


def test_dependency_hygiene_refuses_an_unreadable_manifest(
    tmp_path: pathlib.Path,
) -> None:
    from terp.cli.verify import _run_dependency_hygiene

    (tmp_path / "pyproject.toml").write_text("[tool.deptry\n", encoding="utf-8")
    exit_code, output = _run_dependency_hygiene(tmp_path)
    assert exit_code == 1 and "unreadable" in output


def test_dependency_hygiene_passes_a_clean_run_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    import terp.cli.verify as verify_module

    monkeypatch.setattr(
        verify_module, "_run_subprocess", lambda check, root: (1, "DEP001 missing: yaml")
    )
    (tmp_path / "pyproject.toml").write_text("[tool.deptry]\n", encoding="utf-8")
    assert verify_module._run_dependency_hygiene(tmp_path) == (
        1,
        "DEP001 missing: yaml",
    ), "a real finding travels unaltered; only the missing-tool case is annotated"


def test_the_separator_scan_answers_only_is_this_quoted() -> None:
    """A purpose-built scan, after three attempts to borrow a lexer produced three
    different wrong answers: ``shlex.split`` strips quotes, so a literal
    ``grep -F '&&'`` looked like composition; non-POSIX lexing raised on a quote
    that does not start its token, silently disabling the guard for everything
    after it; and matching whole argv elements missed ``a&&b``."""
    from terp.cli.verify import _shell_separators_in

    assert _shell_separators_in("lint . && test .") == ["&&"]
    assert _shell_separators_in("lint .&&test .") == ["&&"], "welding is not a hiding place"
    assert _shell_separators_in("lint . || true") == ["||"]
    assert _shell_separators_in("grep -F '&&' scripts") == [], "a quoted literal"
    assert _shell_separators_in('grep -F "&&" scripts') == []
    assert _shell_separators_in('curl --url="http://h/p?a=1&b=2"') == []
    assert _shell_separators_in("terp check --package engine") == []
    # A backslash escapes the next character OUTSIDE quotes too. Honouring it
    # inside double quotes only was a fail-OPEN: a `\\"` outside quotes opened a
    # phantom quoted region that swallowed the rest of the line.
    #
    # RAW string on purpose. The first version of this test wrote it non-raw, so
    # `\\"` collapsed to `"` and the input carried no backslash at all -- it passed
    # against the very implementation it was meant to pin.
    swallowed = r'node --eval console.log(\"hi\") && rm -rf /tmp/x'
    assert chr(92) in swallowed, "the input has to contain the character under test"
    assert _shell_separators_in(swallowed) == ["&&"]
    assert "&&" in shlex.split(swallowed), "and the real argv did carry one"

    # ...and inside double quotes, which the docstring promises and nothing else
    # covers.
    assert _shell_separators_in(r'echo "a\"&& b"') == []


def test_quoting_and_escaping_both_mean_literal() -> None:
    """The boundary this scan draws, stated so it is deliberate rather than
    incidental.

    `shlex.split` cannot help here: a quoted `'&&'` and a bare `&&` both arrive as
    the same bare argv element, so argv membership would refuse a literal anyone
    is entitled to pass. The discriminator is what the author wrote, and a command
    line has exactly two ways to say "literally this": quote it, or escape it.
    """
    from terp.cli.verify import _shell_separators_in

    assert _shell_separators_in("lint . && test .") == ["&&"], "plain: refused"
    assert _shell_separators_in("grep -F '&&' x") == [], "quoted: accepted"
    assert _shell_separators_in(r"grep -F \&\& x") == [], "escaped: accepted"
    # Both spellings reach argv as the same bare element, which is exactly why
    # this cannot be decided from argv.
    assert shlex.split("grep -F '&&' x") == shlex.split(r"grep -F \&\& x")


def test_the_separator_length_is_derived_not_assumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first scan hard-coded a two-character slice, so adding a one-character
    separator would have made it silently unmatchable with every test still
    green."""
    import terp.cli.verify as verify_module

    monkeypatch.setattr(
        verify_module, "_COMMAND_SEPARATORS", frozenset({"&&", "||", ";"})
    )
    assert verify_module._shell_separators_in("a ; b") == [";"]
    assert verify_module._shell_separators_in("a && b") == ["&&"], (
        "and the longer one is still read whole, not as two shorter ones"
    )


@pytest.mark.parametrize(
    ("command", "accepted"),
    [
        pytest.param("lint . && test .", False, id="the mistake this catches"),
        pytest.param("lint .&&test .", False, id="welded to its neighbours"),
        pytest.param("lint . || true", False, id="the other separator"),
        pytest.param(
            "awk -F'|' -f a.awk src && rm -rf /tmp/x",
            False,
            id="a quote that does not start its token no longer hides it",
        ),
        pytest.param("grep -F '&&' scripts", True, id="a quoted literal separator"),
        pytest.param(
            "awk -F '|' -f check.awk src", True, id="a quoted pipe is one argument"
        ),
        pytest.param(
            'curl --url="http://host/p?a=1&b=2"',
            True,
            id="an ampersand inside a URL is one argument",
        ),
        pytest.param(
            "node --eval console.log(1)", True, id="parentheses are not composition"
        ),
        pytest.param("pytest -q 2>&1", True, id="a redirection is only an argument"),
        pytest.param(
            "find . -name x -exec rm {} ;", True, id="find's own semicolon"
        ),
        pytest.param("uv run pytest -k 'not slow'", True, id="a quoted expression"),
    ],
)
def test_only_an_unquoted_separator_is_refused(command: str, accepted: bool) -> None:
    """A guard whose false positives are commands people really write is worse
    than the mistake it catches, so only an UNQUOTED ``&&`` or ``||`` is refused.
    No other shell syntax is interpreted at all; the rest fails visibly at run
    time, on the command's own output."""
    from terp.cli.verify import _app_check_from

    entry = {
        "id": "app-check",
        "command": command,
        "profile": "quick",
        "scope": ["app/**"],
    }
    if accepted:
        assert _app_check_from(entry, 0, frozenset()).command == command
    else:
        with pytest.raises(SystemExit, match="no shell"):
            _app_check_from(entry, 0, frozenset())


def test_an_unbalanced_quote_is_a_declaration_error_not_a_traceback(
    tmp_path: pathlib.Path,
) -> None:
    """`shlex.split` raises on it. Uncaught, that is a traceback out of
    `terp verify` about a file the user can fix in a second."""
    from terp.cli.verify import app_declared_checks

    (tmp_path / "pyproject.toml").write_text(
        '[[tool.terp.verify.checks]]\nid = "engine-arch"\n'
        'command = "echo \\"oops"\nprofile = "quick"\n'
        'scope = ["engine/**"]\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="cannot be read as a command line"):
        app_declared_checks(tmp_path)
