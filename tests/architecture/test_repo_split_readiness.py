"""Repo-split integrity: the three repositories stay decoupled (ADR 0082).

The split is DONE: this repository is the framework (``packages/`` +
``tests/`` + ``apps/`` + ``template/``); the Terp Standard lives in
`AITT-NL/terp-spec <https://github.com/AITT-NL/terp-spec>`_ (consumed as the
published ``terp-spec`` / ``@terpjs/spec`` packages, pinned by release) and
Terp Studio in its own private repository. This guard fails the build the
moment code re-couples them:

* nothing in the framework locates the spec by repo-relative path — the only
  seam is the ``terp_spec`` accessor / ``@terpjs/spec`` package resolution;
* nothing in the framework references ``studio/`` at all;
* the split units never silently return as directories or workspace members;
* the two spec pins (``terp-spec`` in pyproject.toml, ``@terpjs/spec`` in the
  eslint-boundaries package) name the **same** ``X.Y.Z`` release, and the
  lockfiles resolved that same release from the public registries — "bump
  both pins together" is a failing test, not a convention.
"""

from __future__ import annotations

import json
import pathlib
import re
import tomllib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_THIS_FILE = pathlib.Path(__file__).resolve()

# The framework's source + test trees (the unit that stays in this repository).
_FRAMEWORK_TREES = ("packages", "tests", "apps", "template")
_SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jinja"}

# A repo-relative escape to the spec: a pathlib join (`/ "spec"`) or a path-API
# join (`join(..., "spec"...)` / `resolve(..., "spec"...)`). Prose mentions of
# spec/ paths in comments and docstrings are fine — only path *construction* is.
_SPEC_PATH_ESCAPES = re.compile(r'/\s*"spec"|\b(?:join|resolve)\([^)\n]*"spec"')


def _framework_sources() -> list[pathlib.Path]:
    files = []
    for tree in _FRAMEWORK_TREES:
        for path in (_REPO_ROOT / tree).rglob("*"):
            if (
                path.suffix in _SOURCE_SUFFIXES
                and path.is_file()
                and "node_modules" not in path.parts
                and path != _THIS_FILE
            ):
                files.append(path)
    return files


def test_the_framework_never_reaches_into_spec_by_path() -> None:
    offenders = [
        path.relative_to(_REPO_ROOT)
        for path in _framework_sources()
        if _SPEC_PATH_ESCAPES.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert offenders == [], (
        "the spec is a dependency (terp-spec / @terpjs/spec), never a repo-relative path "
        f"(ADR 0082) — construct it via terp_spec.spec_dir() or @terpjs/spec: {offenders}"
    )


def test_the_framework_never_references_studio() -> None:
    offenders = [
        path.relative_to(_REPO_ROOT)
        for path in _framework_sources()
        if "studio" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == [], (
        f"studio/ is a fully decoupled unit — the framework must not reference it: {offenders}"
    )


def test_the_spec_unit_stays_layer_neutral() -> None:
    """The spec is consumed from its own repository (pinned in
    ``[tool.uv.sources]``), never re-vendored here — and the installed
    accessor stays dependency-free and framework-import-free."""
    assert not (_REPO_ROOT / "spec").exists(), (
        "the Terp Standard lives in AITT-NL/terp-spec now — bump the pinned tag "
        "instead of re-vendoring spec/ into the framework repository"
    )
    import terp_spec

    accessor = pathlib.Path(terp_spec.__file__).read_text(encoding="utf-8")
    assert "import terp." not in accessor and "from terp." not in accessor, (
        "terp_spec must not import the framework"
    )
    root_pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "terp-spec" not in root_pyproject.split("[tool.uv.sources]", 1)[-1].split(
        "[dependency-groups]", 1
    )[0], (
        "terp-spec is a published distribution (ADR 0086) — it resolves from PyPI, "
        "so it must NOT carry a [tool.uv.sources] override"
    )


def test_studio_is_not_a_workspace_member() -> None:
    assert not (_REPO_ROOT / "studio").exists(), (
        "Terp Studio lives in its own (private) repository — it never returns here"
    )
    root_pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    root_manifest = (_REPO_ROOT / "package.json").read_text(encoding="utf-8")
    assert "studio" not in root_pyproject and "studio" not in root_manifest, (
        "studio stays outside the uv/npm workspaces (its own repository)"
    )


# --------------------------------------------------------------------------- #
# The spec pin: one published release, named identically by both ecosystems
# --------------------------------------------------------------------------- #

_RELEASE = re.compile(r"\d+\.\d+\.\d+")


def _python_spec_pin() -> str:
    """The ``terp-spec`` release from the structured pyproject manifest."""
    pyproject = tomllib.loads(
        (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    requirements = [
        requirement
        for requirement in pyproject["dependency-groups"]["dev"]
        if isinstance(requirement, str) and requirement.startswith("terp-spec")
    ]
    assert len(requirements) == 1, (
        f"the dev group must declare terp-spec exactly once, got {requirements}"
    )
    match = re.fullmatch(r"terp-spec==(\d+\.\d+\.\d+)", requirements[0])
    assert match, (
        "terp-spec must pin one exact published release (terp-spec==X.Y.Z, "
        f"ADR 0086), got {requirements[0]!r}"
    )
    return match.group(1)


def _js_spec_pin() -> str:
    """The ``@terpjs/spec`` release from the eslint-boundaries manifest."""
    manifest = json.loads(
        (
            _REPO_ROOT
            / "packages"
            / "frontend"
            / "eslint-boundaries"
            / "package.json"
        ).read_text(encoding="utf-8")
    )
    declared = {
        section: manifest.get(section, {}).get("@terpjs/spec", "")
        for section in ("dependencies", "devDependencies", "peerDependencies")
    }
    values = {value for value in declared.values() if value}
    assert values, "eslint-boundaries declares no @terpjs/spec dependency"
    assert len(values) == 1, (
        f"@terpjs/spec is declared inconsistently across sections: {declared}"
    )
    (value,) = values
    assert _RELEASE.fullmatch(value), (
        "@terpjs/spec must pin one exact published release (X.Y.Z, ADR 0086), "
        f"got {value!r} — a range would let the two ecosystems drift apart"
    )
    return value


def test_spec_pins_agree_across_both_manifests() -> None:
    """The one rule ADR 0082 leaves to discipline — "bump both pins
    together" — enforced: the Python and npm manifests must name the exact
    same spec release."""
    py_pin, js_pin = _python_spec_pin(), _js_spec_pin()
    assert py_pin == js_pin, (
        f"spec pin skew: pyproject.toml pins terp-spec {py_pin} but "
        f"eslint-boundaries pins @terpjs/spec {js_pin} — bump both pins "
        "together (ADR 0082)"
    )


def test_spec_lockfiles_resolved_the_pinned_release() -> None:
    """Both lockfiles carry the pinned release, resolved from the public
    registry — so a manifest bump without a re-lock, or a lockfile drifting
    to another version, fails here instead of at install time."""
    pin = _python_spec_pin()
    lock = tomllib.loads((_REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    entries = [p for p in lock.get("package", []) if p.get("name") == "terp-spec"]
    assert entries, "uv.lock carries no terp-spec entry — run `uv lock`"
    assert entries[0].get("version") == pin, (
        f"uv.lock resolved terp-spec {entries[0].get('version')!r}, not the "
        f"pinned {pin} — run `uv lock`"
    )
    assert "registry" in entries[0].get("source", {}), (
        "terp-spec must resolve from a package registry (ADR 0086), not a git "
        f"checkout: {entries[0].get('source')!r}"
    )
    npm_lock = json.loads(
        (_REPO_ROOT / "package-lock.json").read_text(encoding="utf-8")
    )
    node = npm_lock.get("packages", {}).get("node_modules/@terpjs/spec")
    assert node is not None, (
        "package-lock.json carries no @terpjs/spec entry — run `npm install`"
    )
    assert node.get("version") == pin, (
        f"package-lock.json resolved @terpjs/spec {node.get('version')!r}, not "
        f"the pinned {pin} — run `npm install` after bumping the pin"
    )
    assert node.get("resolved", "").startswith("https://registry.npmjs.org/"), (
        "@terpjs/spec must resolve from the npm registry (ADR 0086): "
        f"{node.get('resolved')!r}"
    )
    assert node.get("integrity"), (
        "package-lock.json's @terpjs/spec entry records no integrity hash — "
        "a registry install without one cannot be verified"
    )
