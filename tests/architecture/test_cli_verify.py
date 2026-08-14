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
        "architecture",
        "backend-tests",
        "appsec-baseline",
        "frontend-boundaries",
        "routes-drift",
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


def test_the_template_ci_checks_the_committed_route_table() -> None:
    """The full profile's equivalence with template CI, for the routes half: the
    generated app's CI must refuse a stale committed table, before its typecheck."""
    workflow = (
        _REPO_ROOT / "template" / "project" / ".github" / "workflows" / "ci.yml.jinja"
    ).read_text(encoding="utf-8")
    assert "npm run routes -- --check" in workflow
    assert workflow.index("npm run routes -- --check") < workflow.index("npm run typecheck")


def test_the_template_ci_runs_the_platform_install_check() -> None:
    """The claim above is an equivalence, so a check the profile gained must reach
    CI too. CI installs from the app's ``==`` pins exactly as a developer does, so
    a forgotten pin produces the same mixed install there — silently, and with the
    gate's green stamped on it."""
    workflow = (
        _REPO_ROOT / "template" / "project" / ".github" / "workflows" / "ci.yml.jinja"
    ).read_text(encoding="utf-8")
    assert "--only platform-install" in workflow, (
        "the generated CI must verify the platform install before running the "
        "gate — otherwise CI blesses a combination that was never released"
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
