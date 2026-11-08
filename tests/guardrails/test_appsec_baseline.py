"""Guardrail: the delegated generic AppSec baseline cannot be silently disabled.

The Terp Standard deliberately catalogs Terp-specific secure-architecture rules
and **delegates** generic vulnerability classes (command injection, unsafe
deserialization, weak hashes, ...) to ruff's bandit-derived ``S`` baseline
(``docs/decisions/0085-appsec-scope-and-delegated-baseline.md``, building on
ADR 0033). A delegation is only real if it is testable, so this suite holds
the four places it lives:

* the platform repo's own baseline (``pyproject.toml`` + the blocking
  ``generic-checks`` CI step);
* the client template's baseline (the generated project's ``pyproject.toml``
  config + dev dependency + blocking CI step);
* the generated project's *own* ratchet — its architecture test asserts the
  baseline stanza, so a scaffolded app cannot drop the config without a
  visible test edit.

This is the build-time layer of the delegation; the "runtime" is the external
tool itself, which is exactly why the catalog never duplicates its rules
(ADR 0085's admission rule).
"""

from __future__ import annotations

import pathlib
import re
import tomllib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO_ROOT / "template" / "project"

#: The sanctioned baseline (ADR 0033 / ADR 0085): the `S` family on, only the
#: name-heuristic rules excused, and only tests excused for known-subprocess /
#: non-crypto randomness. A wider ignore list is a weakened baseline.
_SANCTIONED_IGNORES = {"S101", "S105", "S106"}
_SANCTIONED_TEST_IGNORES = {"S311", "S603", "S607"}
#: The one per-file ignore outside a test tree, and all it may excuse: pyflakes (`F`)
#: over the rule corpus, whose cases are fragments of an app, never imported or run, so
#: their names live in the app they stand for. It excuses no `S` rule: the corpus keeps
#: the security baseline like any other code.
_SANCTIONED_CORPUS_IGNORE = ("packages/backend/arch/corpus/**", {"F"})
#: Paths a ruff exclude may carve out without weakening the baseline: virtualenvs,
#: the byte-checked vendored mirror, generated Alembic DDL, and the violation cases of the
#: two rules whose cases must carry a form the `S` baseline refuses (dynamic SQL, eval).
#: Those cases are never imported (ADR 0080, ADR 0203), and every other corpus case is
#: linted. Excluding app or framework code is a silent-disable vector, so anything else fails.
_SANCTIONED_ROOT_EXCLUDES = {
    ".venv",
    "vendor",
    "**/migrations/versions",
    "packages/backend/arch/corpus/backend/no_dynamic_sql/violation-*",
    "packages/backend/arch/corpus/backend/no_eval_or_exec/violation-*",
}
_SANCTIONED_TEMPLATE_EXCLUDES = {".venv", "**/migrations/versions"}


def _lint_config(pyproject: dict) -> dict:
    return pyproject.get("tool", {}).get("ruff", {}).get("lint", {})


def _template_ruff_config() -> dict:
    """The template's ``[tool.ruff]`` stanza parsed as real TOML.

    The Jinja expressions all live in the ``[project]`` half of the manifest;
    everything from ``[tool.ruff]`` on is plain TOML, so slicing there gives
    tomllib a valid document — a structural parse, not a substring grep, so a
    widened ignore or an app-covering exclude cannot hide in formatting. (If a
    future edit moves Jinja below the stanza, this parse fails loudly.)
    """
    text = (_TEMPLATE / "pyproject.toml.jinja").read_text(encoding="utf-8")
    return tomllib.loads(text[text.index("[tool.ruff]") :]).get("tool", {}).get("ruff", {})


def test_platform_repo_keeps_the_ruff_security_baseline() -> None:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lint = _lint_config(config)
    assert "S" in lint.get("select", []), (
        "the repo-wide ruff config must select the bandit-derived `S` baseline (ADR 0033)"
    )
    assert set(lint.get("ignore", [])) <= _SANCTIONED_IGNORES, (
        "the repo-wide `S` baseline ignores more than the sanctioned name-heuristic "
        f"rules {sorted(_SANCTIONED_IGNORES)}: {sorted(lint.get('ignore', []))} — widening "
        "the excusals is a weakened baseline and needs an ADR"
    )
    for pattern, codes in lint.get("per-file-ignores", {}).items():
        if (pattern, set(codes)) == _SANCTIONED_CORPUS_IGNORE:
            continue
        assert "test" in pattern, (
            f"per-file-ignores for {pattern!r}: only test trees may excuse baseline rules"
        )
        assert set(codes) <= _SANCTIONED_TEST_IGNORES, (
            f"per-file-ignores for {pattern!r} excuse more than the sanctioned "
            f"{sorted(_SANCTIONED_TEST_IGNORES)}: {sorted(codes)}"
        )
    ruff = config.get("tool", {}).get("ruff", {})
    for key in ("exclude", "extend-exclude"):
        assert set(ruff.get(key, [])) <= _SANCTIONED_ROOT_EXCLUDES, (
            f"[tool.ruff] {key} carves more than the sanctioned "
            f"{sorted(_SANCTIONED_ROOT_EXCLUDES)} out of the security baseline: "
            f"{sorted(ruff.get(key, []))} — excluding app/framework code is a "
            "silent-disable vector"
        )
    lint_group = config.get("dependency-groups", {}).get("lint", [])
    assert any(dep.startswith("ruff") for dep in lint_group), (
        "the CI lint dependency group must pin ruff"
    )


def test_platform_ci_runs_the_baseline_blocking() -> None:
    ci = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    match = re.search(r"- name: ruff[^\n]*\n(?:\s+continue-on-error: true\n)?\s+run: (.+)", ci)
    assert match and "ruff check" in match.group(1), (
        "ci.yml must run `ruff check` in the generic-checks job"
    )
    assert "continue-on-error" not in match.group(0), (
        "the ruff security baseline step must be blocking, never advisory"
    )


def test_the_secret_scan_is_scoped_to_the_history_under_test() -> None:
    """`gitleaks detect` walks every ref in the clone unless told otherwise.

    The checkout above it uses ``fetch-depth: 0``, which fetches every remote branch —
    so without ``--log-opts`` this step reports secrets from branches the pull request
    under test has never touched. That is a false positive with the worst possible shape
    for a security control: it lands on somebody else's change, it cannot be fixed there,
    and the only way to make it go away is to stop reading the check. A control people
    learn to scroll past has already failed.

    Scoping to ``HEAD`` is not a narrowing. Every branch's own history is still scanned
    in full — main's on every push, a pull request's on its own run, and the merge ref
    carries the base — so a secret still cannot reach the default branch unscanned.
    """
    ci = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    match = re.search(r"^\s+\./gitleaks detect .*$", ci, re.MULTILINE)
    assert match, "ci.yml must run `gitleaks detect` in the generic-checks job"
    command = match.group(0)
    assert "--log-opts HEAD" in command, (
        "the secret scan must be scoped to the history under test "
        f"(--log-opts HEAD); found: {command.strip()}"
    )


def test_template_ships_the_baseline_config() -> None:
    """The generated project inherits the delegation: exact config + dev dep."""
    ruff = _template_ruff_config()
    lint = ruff.get("lint", {})
    # Exact, not a superset: the delegation is a named set, and a rule quietly added
    # here is a rule nobody reviewed. `F` is part of that set because `select` REPLACES
    # ruff's default rather than extending it, so naming only `S` switched pyflakes off
    # -- taking F821 (undefined name) with it, which is correctness rather than tidiness
    # and which nothing else in the profile answers.
    assert lint.get("select") == ["S", "F"], (
        "template pyproject must select exactly the ruff `S` security baseline plus the "
        "`F` pyflakes rules (ADR 0085); dropping `F` lets a dead import, a dead local "
        "or a typo'd name pass the whole merge bar"
    )
    assert set(lint.get("ignore", [])) == _SANCTIONED_IGNORES, (
        f"template baseline ignores must be exactly {sorted(_SANCTIONED_IGNORES)}, "
        f"got {sorted(lint.get('ignore', []))}"
    )
    per_file = lint.get("per-file-ignores", {})
    assert per_file, "the template must excuse its test trees explicitly (and only those)"
    for pattern, codes in per_file.items():
        assert "tests" in pattern.split("/"), (
            f"template per-file-ignores {pattern!r}: only test trees may excuse "
            "baseline rules"
        )
        assert set(codes) <= _SANCTIONED_TEST_IGNORES, (
            f"template per-file-ignores {pattern!r} excuse more than the sanctioned "
            f"{sorted(_SANCTIONED_TEST_IGNORES)}: {sorted(codes)}"
        )
    for key in ("exclude", "extend-exclude"):
        assert set(ruff.get(key, [])) <= _SANCTIONED_TEMPLATE_EXCLUDES, (
            f"template [tool.ruff] {key} carves more than the sanctioned "
            f"{sorted(_SANCTIONED_TEMPLATE_EXCLUDES)} out of the baseline: "
            f"{sorted(ruff.get(key, []))}"
        )
    pyproject = (_TEMPLATE / "pyproject.toml.jinja").read_text(encoding="utf-8")
    assert '"ruff>=' in pyproject, (
        "the template's dev dependency group must include ruff so "
        "`uv run ruff check .` works out of the box"
    )


def test_template_ci_and_project_gate_enforce_the_baseline() -> None:
    ci = (_TEMPLATE / ".github" / "workflows" / "ci.yml.jinja").read_text(encoding="utf-8")
    # The baseline blocks because it is a check of the `full` profile and CI invokes that
    # profile unconditionally — not because a step in this YAML spells `ruff`. The
    # distinction decides whether a FIELDED app is covered: the workflow is scaffolded and
    # freezes at the version it was rendered from, so a baseline wired as a CI step stops
    # running the moment an app stops re-rendering, while one wired into the profile keeps
    # running off the installed packages. `appsec-baseline`'s membership is asserted in
    # test_cli_verify.py::test_the_full_profile_is_the_template_ci_surface.
    assert "terp verify --profile full" in ci, (
        "the generated project's CI must invoke the profile that carries the ruff `S` "
        "baseline, as a blocking step"
    )
    assert "continue-on-error" not in ci, (
        "the generated project's CI steps are all blocking; the baseline must not "
        "become advisory"
    )
    arch_test = (_TEMPLATE / "tests" / "test_architecture.py.jinja").read_text(encoding="utf-8")
    assert "test_generic_appsec_baseline_is_wired" in arch_test, (
        "the generated project's own gate must assert the baseline, so a "
        "scaffolded app cannot drop it silently (ADR 0085)"
    )
    # The in-project ratchet must PARSE the stanza and pin the CI step — a
    # substring check would survive an app-wide per-file-ignore, an exclude,
    # or a deleted workflow step (the silent-disable vectors ADR 0085 names).
    for anchor in ("tomllib.loads", "per-file-ignores", "extend-exclude", "uv run ruff check ."):
        assert anchor in arch_test, (
            f"the generated project's baseline ratchet lost its {anchor!r} check — "
            "it must parse the ruff stanza and pin the CI step (ADR 0085)"
        )


def test_template_acceptance_proves_a_rendered_project_passes_the_baseline() -> None:
    """The platform CI renders the template and runs the baseline on the output.

    The in-project ratchet guards drift *after* scaffolding; this step proves
    the template as shipped actually passes its own baseline (a config error or
    an S-flagged starter file) before it ever reaches a user.
    """
    ci = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uv run ruff check ." in ci, (
        "the template-acceptance job must run `uv run ruff check .` against the "
        "rendered project (ADR 0085)"
    )


#: The one place a credential-shaped literal is required: the violation cases of the rule
#: that exists to flag one. Every other corpus case, and every other file, is still scanned.
_SECRET_SCAN_ALLOWED_PATHS = frozenset(
    {"^packages/backend/arch/corpus/backend/no_hardcoded_credentials/violation-"}
)


def test_the_secret_scan_is_narrowed_only_where_a_match_cannot_be_real() -> None:
    """The credential rule's violation cases are the one place a credential-shaped literal is required.

    A violation case for ``backend/no_hardcoded_credentials`` that holds no credential-shaped
    literal is a broken case: the check it exists to hold would have nothing to flag. So the
    scan finds some there today and would find one more with every case added, and a per-line
    baseline would grow an entry each time until appending to it is the reflex.

    Narrowing is only defensible while it stays that narrow, so this holds the parsed
    configuration to one shape rather than searching its text: ``[extend]`` keeps the default
    ruleset on and disables none of it, nothing else is declared at the top level (no
    ``rules`` replacing or adding detectors, no singular ``allowlist``), and each allowlist
    carries only a description and paths - nothing allowed by value, by commit or for a chosen
    rule - whose paths are exactly that one tree.
    """
    config = _REPO_ROOT / ".gitleaks.toml"
    assert config.is_file(), (
        "the credential rule's violation cases carry credential-shaped literals by "
        "construction; .gitleaks.toml is where that is recorded, scoped and reviewable"
    )
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert parsed.get("extend") == {"useDefault": True}, (
        f".gitleaks.toml declares [extend] as {parsed.get('extend')!r}. It must be exactly "
        "`useDefault = true`: without it the file REPLACES the default ruleset rather than "
        "extending it, and `disabledRules`, `path` or `url` would switch detectors off or "
        "swap them for others"
    )
    extra = sorted(set(parsed) - {"extend", "allowlists"})
    assert not extra, (
        f".gitleaks.toml declares {extra}. Only [extend] and [[allowlists]] belong here: "
        "`rules` adds or overrides detectors, and a singular `allowlist` is a second, "
        "unguarded place to narrow the scan"
    )
    allowlists = parsed.get("allowlists", [])
    assert allowlists, "the file narrows nothing; delete it instead"
    paths: set[str] = set()
    for allowlist in allowlists:
        widening = sorted(set(allowlist) - {"description", "paths"})
        assert not widening, (
            f"an allowlist declares {widening}. Allow by path alone: `regexes` and `stopwords` "
            "allow a match by value, `commits` by commit, and either hides the same literal "
            "anywhere in the repository; `targetRules` and `condition` change what a path "
            "entry means"
        )
        paths.update(allowlist.get("paths", []))
    assert paths == _SECRET_SCAN_ALLOWED_PATHS, (
        f"the secret scan is taken off {sorted(paths)}; it may be taken off exactly "
        f"{sorted(_SECRET_SCAN_ALLOWED_PATHS)}. Only that rule's violation cases are invented "
        "by construction and required to hold a credential-shaped literal; anywhere else a "
        "match may be a real credential, and the answer to one of those is to rotate it"
    )
