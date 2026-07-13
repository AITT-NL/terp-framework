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
#: Paths a ruff exclude may carve out without weakening the baseline: virtualenvs,
#: the byte-checked vendored mirror, and generated Alembic DDL. Excluding app or
#: framework code is a silent-disable vector, so anything else fails.
_SANCTIONED_ROOT_EXCLUDES = {".venv", "vendor", "**/migrations/versions"}
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


def test_template_ships_the_baseline_config() -> None:
    """The generated project inherits the delegation: exact config + dev dep."""
    ruff = _template_ruff_config()
    lint = ruff.get("lint", {})
    assert lint.get("select") == ["S"], (
        "template pyproject must select exactly the ruff `S` baseline (ADR 0085)"
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
    assert "uv run ruff check ." in ci, (
        "the generated project's CI must run the ruff `S` baseline as a blocking step"
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
