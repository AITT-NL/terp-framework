"""``terp --version`` — the platform must be able to say what it is.

Its absence was a real dogfood finding: an app driving an upgrade had no way to
ask which Terp it was on, so the whole bump ran on a number a human supplied.
Worse, Terp ships as a lockstep set of distributions pinned by hand across two
manifests, so a *forgotten* pin yields a mixed install that nothing detected.
These tests pin both halves: the flag answers, and a disagreeing set is named.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

# terp-cli is not pip-installed in the dev venv; inject its src (as test_cli_guide does).
_CLI_SRC = pathlib.Path(__file__).resolve().parents[2] / "packages" / "backend" / "cli" / "src"
sys.path.insert(0, str(_CLI_SRC))

from terp.cli import main  # noqa: E402  (import after sys.path setup)
from terp.cli import version as version_mod  # noqa: E402


def _fake_versions(monkeypatch: pytest.MonkeyPatch, versions: dict[str, str]) -> None:
    monkeypatch.setattr(version_mod, "installed_terp_versions", lambda: versions)


def test_version_flag_answers_instead_of_demanding_a_subcommand(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The regression this exists for: ``command`` is a required subparser, so a
    naively-added flag would still die with "the following arguments are
    required: command" — which is exactly what an app hit."""
    _fake_versions(monkeypatch, {"terp-core": "0.5.4", "terp-cli": "0.5.4"})
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code in (0, None)
    out = capsys.readouterr().out
    assert "terp 0.5.4" in out
    assert "required" not in out


def test_short_flag_works_too(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_versions(monkeypatch, {"terp-core": "0.5.4"})
    with pytest.raises(SystemExit):
        main(["-V"])
    assert "terp 0.5.4" in capsys.readouterr().out


def test_a_consistent_install_says_so_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_versions(
        monkeypatch,
        {"terp-core": "0.5.4", "terp-cli": "0.5.4", "terp-cap-auth": "0.5.4"},
    )
    text = version_mod.render_version()
    assert text.strip() == "terp 0.5.4"
    assert "WARNING" not in text


def test_a_missed_pin_is_named_not_averaged_away(monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure mode worth catching: one package left a release behind.

    The set still has an answer (the anchor's version), and the odd one out is
    named with the fix — "it's complicated" would help nobody.
    """
    _fake_versions(
        monkeypatch,
        {"terp-core": "0.5.4", "terp-cli": "0.5.4", "terp-cap-audit": "0.5.3"},
    )
    text = version_mod.render_version()
    assert "terp 0.5.4" in text
    assert "mixed install" in text
    assert "terp-cap-audit" in text
    assert "0.5.3" in text
    assert "uv sync --refresh" in text
    # The packages that are correct are not paraded as problems.
    assert "terp-core " not in text.split("mixed install")[1]


def test_json_is_machine_readable_for_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_versions(monkeypatch, {"terp-core": "0.5.4", "terp-cap-audit": "0.5.3"})
    payload = json.loads(version_mod.render_version(fmt="json"))
    assert payload["version"] == "0.5.4"
    assert payload["consistent"] is False
    assert payload["distributions"]["terp-cap-audit"] == "0.5.3"


def test_an_environment_without_terp_says_so_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_versions(monkeypatch, {})
    assert "not installed" in version_mod.render_version()
    assert json.loads(version_mod.render_version(fmt="json"))["version"] is None


def test_discovery_is_from_the_environment_not_a_hand_written_list() -> None:
    """A declared list would rot into the same drift this command diagnoses, so
    the set comes from installed metadata — including capabilities added later."""
    source = (_CLI_SRC / "terp" / "cli" / "version.py").read_text(encoding="utf-8")
    assert "metadata.distributions()" in source


def test_the_independently_released_spec_is_not_a_missed_pin() -> None:
    """``terp-spec`` shares the prefix but is released from its own repository on
    its own cadence (ADR 0082/0086). Caught live the first time this ran: it
    reported every consistent install as mixed, which is how a check earns being
    ignored."""
    assert "terp-spec" in version_mod._INDEPENDENTLY_VERSIONED
    assert "terp-spec" not in version_mod.installed_terp_versions()


def test_a_malformed_distribution_on_the_path_is_skipped_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`terp --version` is what you reach for when an environment is already
    suspect, so a broken dist on sys.path must not be the thing that stops you
    from diagnosing it."""

    class _Nameless:
        metadata = {"Name": None}
        version = "0.0.0"

    class _Real:
        metadata = {"Name": "terp-core"}
        version = "0.5.4"

    monkeypatch.setattr(
        version_mod.metadata, "distributions", lambda: [_Nameless(), _Real()]
    )
    assert version_mod.installed_terp_versions() == {"terp-core": "0.5.4"}


def test_without_the_anchor_the_majority_answers() -> None:
    """A partial install (capabilities but no terp-core) still gets a useful
    answer rather than a shrug."""
    assert (
        version_mod.platform_version(
            {"terp-cap-auth": "0.5.4", "terp-cap-audit": "0.5.4", "terp-cli": "0.5.3"}
        )
        == "0.5.4"
    )


# --- terp upgrade --check ---------------------------------------------------


def _uv_says(monkeypatch: pytest.MonkeyPatch, packages: list[dict[str, str]]) -> None:
    monkeypatch.setattr(version_mod, "_uv_outdated", lambda: (packages, None))


def test_a_release_that_covers_the_whole_set_is_offered_with_the_recipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_versions(monkeypatch, {"terp-core": "0.5.4", "terp-cap-auth": "0.5.4"})
    _uv_says(
        monkeypatch,
        [
            {"name": "terp-core", "version": "0.5.4", "latest_version": "0.6.0"},
            {"name": "terp-cap-auth", "version": "0.5.4", "latest_version": "0.6.0"},
        ],
    )
    text = version_mod.render_upgrade_check()
    assert "Terp 0.6.0 is available" in text
    assert "can move to 0.6.0 together" in text
    # The recipe must cover both manifests — a frontend package left behind is the
    # same mixed install by another route.
    assert "==0.6.0" in text
    assert "^0.6.0" in text
    # Step 1 must be executable *before* the upgrade: the installed changelog ends
    # at 0.5.4, so the recipe reaches the 0.6.0 notes through an ephemeral CLI at
    # the target version rather than pointing at a copy that cannot contain them.
    assert "uvx --from terp-cli==0.6.0 terp guide changelog" in text
    assert "the copy installed here ends at 0.5.4" in text
    # Step 3 must name every manifest that pins @terpjs/*: the template ships two,
    # and a recipe naming only frontend/package.json left conformance stale.
    assert "conformance/package.json" in text
    assert "WARNING" not in text


def test_a_partial_release_is_refused_rather_than_recommended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole reason this command is Terp's and not uv's.

    uv sees fifteen independent packages and will happily bump the ones that
    have a new release. Only Terp knows they move together, and that a release
    covering some of them is a trap rather than an upgrade — mid-publish, or a
    stale index mirror.
    """
    _fake_versions(
        monkeypatch,
        {"terp-core": "0.5.4", "terp-cap-auth": "0.5.4", "terp-cap-audit": "0.5.4"},
    )
    _uv_says(
        monkeypatch,
        [
            {"name": "terp-core", "version": "0.5.4", "latest_version": "0.6.0"},
            {"name": "terp-cap-auth", "version": "0.5.4", "latest_version": "0.6.0"},
        ],
    )
    text = version_mod.render_upgrade_check()
    assert "WARNING" in text
    assert "does not cover the whole set" in text
    assert "terp-cap-audit" in text
    # It must not hand out a bump recipe for a release it just called a trap.
    assert "uv sync --refresh" not in text


def test_an_up_to_date_app_gets_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_versions(monkeypatch, {"terp-core": "0.5.4", "terp-cap-auth": "0.5.4"})
    _uv_says(monkeypatch, [{"name": "httpx", "latest_version": "9.9.9"}])
    assert version_mod.render_upgrade_check() == (
        "Up to date: all 2 terp-* packages are on 0.5.4."
    )


def test_ten_sorts_above_nine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Picked as the target by string comparison, 0.9.0 beats 0.10.0 — and the
    command would recommend a downgrade with total confidence."""
    _fake_versions(monkeypatch, {"terp-core": "0.9.0", "terp-cap-auth": "0.9.0"})
    _uv_says(
        monkeypatch,
        [
            {"name": "terp-core", "latest_version": "0.10.0"},
            {"name": "terp-cap-auth", "latest_version": "0.10.0"},
        ],
    )
    assert "Terp 0.10.0 is available" in version_mod.render_upgrade_check()


def test_an_unreachable_index_explains_itself_and_still_reports_the_local_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """You run this *because* an environment is in question, so a blocked index
    must produce a sentence, never a traceback — and the half that needs no
    network is still worth printing."""
    _fake_versions(monkeypatch, {"terp-core": "0.5.4"})
    monkeypatch.setattr(version_mod, "_uv_outdated", lambda: (None, "uv is not on PATH."))
    text = version_mod.render_upgrade_check()
    assert "Could not check" in text
    assert "uv is not on PATH." in text
    assert "on 0.5.4" in text


def test_the_check_reads_uv_rather_than_reaching_the_index_itself() -> None:
    """Deliberate: a network client inside a tool that promises deterministic,
    offline, fail-closed answers needs timeouts, proxies and index auth — every
    one a new way for `terp` to hang or lie. uv already has all of it."""
    source = (_CLI_SRC / "terp" / "cli" / "version.py").read_text(encoding="utf-8")
    assert "uv" in version_mod._UV_OUTDATED_COMMAND
    for networking in ("httpx", "urllib.request", "requests", "socket"):
        assert f"import {networking}" not in source


def _answers(root: pathlib.Path, commit: str) -> pathlib.Path:
    """An app root whose copier answers record ``commit`` as the rendered template."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".copier-answers.yml").write_text(
        f"_commit: {commit}\n_src_path: /opt/terp/template\nproject_name: Demo\n",
        encoding="utf-8",
    )
    return root


def test_scaffolding_behind_the_packages_is_reported(tmp_path: pathlib.Path) -> None:
    """The one drift nothing else catches.

    Package drift already fails closed (``verify --only platform-install`` reads every
    ``@terpjs/*`` manifest and its installed ``node_modules``). The template ref is checked
    by nothing, so an app runs current libraries against old scaffolding and stays green —
    with a stale ``AGENTS.md`` briefing every agent from a superseded layout contract.
    """
    lines = version_mod._scaffold_lines(_answers(tmp_path / "app", "v0.5.7"), "0.6.1")
    report = "\n".join(lines)
    assert "v0.5.7" in report and "0.6.1" in report
    assert "AGENTS.md" in report
    assert "copier update" in report

    # The report must state the RULE, not three examples of it. Naming a few
    # template-owned files reads as the complete list, and a reader deciding whether a
    # re-render would carry a fix to a file not among them — docker-compose.yml, say —
    # concluded it would not. Both halves are asserted because either alone is
    # compatible with the old, misleading message.
    assert "EVERY file the template owns" in report
    assert "docker-compose.yml" in report
    for name in version_mod._APP_OWNED_SCAFFOLD_FILES:
        assert name in report, f"the report does not name the app-owned {name}"


def _offered(monkeypatch: pytest.MonkeyPatch, root: pathlib.Path) -> str:
    """The report for an app on 0.5.4 with 0.6.0 available, rooted at *root*."""
    _fake_versions(monkeypatch, {"terp-core": "0.5.4", "terp-cap-auth": "0.5.4"})
    _uv_says(
        monkeypatch,
        [
            {"name": "terp-core", "version": "0.5.4", "latest_version": "0.6.0"},
            {"name": "terp-cap-auth", "version": "0.5.4", "latest_version": "0.6.0"},
        ],
    )
    return version_mod.render_upgrade_check(root)


def test_the_recipe_re_renders_before_it_installs_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The printed order used to be impossible to follow.

    Editing the pins and running the two installers dirties the tree, and
    ``copier update`` refuses a dirty tree — so the recipe's own earlier steps made its
    last step impossible, and whoever followed it had to stash halfway through. The pin
    edits were also work the re-render does: the template owns pyproject.toml and both
    npm manifests, so a re-render writes every one of those pins itself.

    Asserted as an ORDER and not as presence. Both commands appeared in the old recipe
    too — the defect was which came first, so any assertion that merely finds them both
    passes on the version this replaced.
    """
    report = _offered(monkeypatch, _answers(tmp_path / "app", "v0.5.7"))
    rerender = report.index("copier update")
    sync = report.index("uv sync --refresh")
    npm = report.index("npm --prefix frontend install")
    assert rerender < sync, "the re-render has to come before the installs, not after"
    assert rerender < npm
    # And the hand-pinning steps are gone rather than merely reordered: they are the
    # re-render's own output, and doing both is what produced two needless installs.
    assert "Pin every terp-* dependency" not in report
    assert "Pin every @terpjs/* package" not in report


def test_the_re_render_recipe_says_to_clean_the_tree_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The refusal is copier's, so the recipe has to account for it rather than
    leave the reader to discover it three steps in."""
    report = _offered(monkeypatch, _answers(tmp_path / "app", "v0.5.7"))
    clean = report.index("Commit or discard what you have")
    assert clean < report.index("copier update")
    assert "dirty tree is refused" in report


def test_the_re_render_recipe_names_the_two_structural_conflicts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Both conflicts are the template owning a file the app also writes to, so they
    arrive on every re-render rather than occasionally — and naming them is the
    difference between a step and a surprise. The operations one now has a fix
    (ADR 0130); pyproject.toml is told which side wins."""
    report = _offered(monkeypatch, _answers(tmp_path / "app", "v0.5.7"))
    assert "keep your dependencies, take the terp-* pins" in report
    assert "control_plane/app_operations.py" in report


def test_the_re_render_recipe_warns_about_a_containerised_dev_stack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The images bake the terp packages in while the source is bind-mounted, so
    correct new code reloads against old libraries and dies on an import nowhere near
    its cause."""
    report = _offered(monkeypatch, _answers(tmp_path / "app", "v0.5.7"))
    assert "Rebuild it rather than reloading into it" in report


def test_the_re_render_command_is_printed_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The recipe numbers the re-render as a step, so the scaffolding report below it
    must not offer the same command again: printed twice in one report it reads as two
    different things to do, and only the recipe's copy has the tree-cleaning step in
    front of it."""
    report = _offered(monkeypatch, _answers(tmp_path / "app", "v0.5.7"))
    assert report.count("copier update") == 1, report


def test_an_app_with_no_template_answers_is_told_to_pin_by_hand(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Without an answers file ``copier update`` has nothing to re-render from, so the
    pins the template would have written have to be written here — including the
    second npm manifest, which a recipe naming only the frontend left stale."""
    bare = tmp_path / "bare"
    bare.mkdir()
    report = _offered(monkeypatch, bare)
    assert "records no" in report and "template answers file" in report
    assert "Pin every terp-* dependency to ==0.6.0" in report
    assert "conformance/package.json" in report
    # The command is *explained* here — why it is unavailable — and must never appear
    # as a numbered step: sending an app copier cannot update to run it is how the old
    # report sent readers to check something by hand.
    assert "has nothing to re-render from" in report
    numbered = [
        line for line in report.splitlines() if re.match(r"\s+\d+\. ", line)
    ]
    assert numbered, "the hand-pin recipe must still print numbered steps"
    assert not [line for line in numbered if "copier" in line], numbered


def test_the_drift_report_does_not_claim_which_files_differ(
    tmp_path: pathlib.Path,
) -> None:
    """It compares two version numbers, and that is all it knows.

    The old wording said a release's fix to any template-owned file "is still waiting
    here" and named AGENTS.md as the example — which was reported as a false alarm on
    an app whose AGENTS.md was byte-identical to the template's. Reading the template
    and diffing it is not available: the template does not ship inside the CLI wheel,
    which is the same constraint that makes _APP_OWNED_SCAFFOLD_FILES a duplicated
    list. So the honest fix is the claim, not the mechanism.
    """
    report = "\n".join(
        version_mod._scaffold_lines(_answers(tmp_path / "app", "v0.5.7"), "0.6.1")
    )
    assert "may still be waiting" in report
    assert "is still waiting here" not in report, "that states more than it checked"
    assert "not something this can say" in report


def test_the_app_owned_scaffold_list_matches_copier() -> None:
    """The duplicated fact, held against its source.

    ``_APP_OWNED_SCAFFOLD_FILES`` restates ``_skip_if_exists`` from
    ``template/copier.yml``, because the template does not ship inside the CLI wheel and
    the report has to be answerable offline. A duplicate that can drift is worse than no
    list at all: it would state, with authority, that a file is yours when a re-render is
    about to overwrite it. Same treatment as the theme bootstrap's three duplicated facts.
    """
    import yaml

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    config = yaml.safe_load(
        (repo_root / "template" / "copier.yml").read_text(encoding="utf-8")
    )
    skipped = config["_skip_if_exists"]

    assert set(skipped) == set(version_mod._APP_OWNED_SCAFFOLD_FILES), (
        "copier's _skip_if_exists and the CLI's copy of it disagree; a file moved "
        "between 'yours' and 'the template's' and the upgrade report now lies about it"
    )
    # Sorted, so the report reads deterministically and a diff here is a real change.
    assert list(version_mod._APP_OWNED_SCAFFOLD_FILES) == sorted(
        version_mod._APP_OWNED_SCAFFOLD_FILES
    )


def test_scaffolding_level_with_the_packages_says_so_and_stops(
    tmp_path: pathlib.Path,
) -> None:
    """Level is worth one line, not a recipe — an app that re-rendered wants confirmation,
    not instructions for work it already did."""
    lines = version_mod._scaffold_lines(_answers(tmp_path / "app", "v0.6.1"), "0.6.1")
    assert "level with the packages" in "\n".join(lines)
    assert "copier update" not in "\n".join(lines)


def test_a_non_release_template_ref_is_reported_without_a_comparison(
    tmp_path: pathlib.Path,
) -> None:
    """A commit sha carries no ordering, so claiming a gap would be an invention."""
    root = _answers(tmp_path / "app", "112a8c1c6918deadbeef")
    report = "\n".join(version_mod._scaffold_lines(root, "0.6.1"))
    assert "112a8c1c6918deadbeef" in report
    assert "behind" in report
    assert "copier update" not in report


def test_an_app_without_copier_answers_is_not_lectured(tmp_path: pathlib.Path) -> None:
    """An app that was never scaffolded from the template has no scaffolding to update,
    and a report about one would be noise in every run."""
    assert version_mod._scaffold_lines(tmp_path, "0.6.1") == []


def test_the_scaffolding_report_never_orders_a_downgrade(tmp_path: pathlib.Path) -> None:
    """Numeric comparison, because 0.10.0 sorts below 0.9.0 as text — the same trap
    ``_version_key`` exists for. Scaffolding *ahead* of the packages is not drift to fix."""
    lines = version_mod._scaffold_lines(_answers(tmp_path / "app", "v0.10.0"), "0.9.0")
    assert "level with the packages" in "\n".join(lines)


def test_uv_is_invoked_without_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fixed argv list, never a shell string: this runs in whatever directory
    the app lives in, and a shell would make that path an injection surface."""
    seen: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stdout = "[]"
        stderr = ""

    def _fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        seen["command"] = command
        seen["kwargs"] = kwargs
        return _Completed()

    monkeypatch.setattr(version_mod.subprocess, "run", _fake_run)
    packages, error = version_mod._uv_outdated()
    assert (packages, error) == ([], None)
    assert isinstance(seen["command"], tuple)
    assert seen["kwargs"].get("shell") is None  # type: ignore[union-attr]
    assert seen["kwargs"].get("timeout")  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (FileNotFoundError(), "not on PATH"),
        (__import__("subprocess").TimeoutExpired(cmd="uv", timeout=1), "unreachable"),
    ],
)
def test_every_uv_failure_becomes_a_sentence(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, expected: str
) -> None:
    def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise failure

    monkeypatch.setattr(version_mod.subprocess, "run", _raise)
    packages, error = version_mod._uv_outdated()
    assert packages is None
    assert error is not None and expected in error


def test_a_failing_or_garbled_uv_is_reported_not_guessed_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Failed:
        returncode = 2
        stdout = ""
        stderr = "error: no such index\n"

    class _Garbled:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(version_mod.subprocess, "run", lambda *a, **k: _Failed())
    _, error = version_mod._uv_outdated()
    assert error is not None and "no such index" in error

    monkeypatch.setattr(version_mod.subprocess, "run", lambda *a, **k: _Garbled())
    _, error = version_mod._uv_outdated()
    assert error is not None and "could not be parsed" in error


def test_an_environment_without_terp_is_told_where_to_run_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_versions(monkeypatch, {})
    text = version_mod.render_upgrade_check()
    assert "nothing to upgrade" in text
    assert "uv run terp upgrade --check" in text


def test_the_cli_refuses_a_bare_upgrade_instead_of_bumping_anything() -> None:
    """`terp upgrade` reads like it will do the bump. It must say plainly that it
    will not, rather than silently printing a report — a lockstep bump spans two
    manifests and is a reviewed change, not a side effect of a command."""
    with pytest.raises(SystemExit) as excinfo:
        main(["upgrade"])
    assert "--check" in str(excinfo.value)
    assert "does not edit your manifests" in str(excinfo.value)


def test_the_cli_prints_the_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_versions(monkeypatch, {"terp-core": "0.5.4"})
    _uv_says(monkeypatch, [])
    main(["upgrade", "--check"])
    assert "Up to date" in capsys.readouterr().out
