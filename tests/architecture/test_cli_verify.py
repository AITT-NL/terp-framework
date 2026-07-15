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
        "architecture",
        "backend-tests",
        "appsec-baseline",
        "frontend-boundaries",
        "frontend-typecheck",
        "frontend-build",
    }


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
