"""Repo-split integrity: the three repositories stay decoupled (ADR 0082).

The split is DONE: this repository is the framework (``packages/`` +
``tests/`` + ``apps/`` + ``template/``); the Terp Standard lives in
`AITT-NL/terp-spec <https://github.com/AITT-NL/terp-spec>`_ (consumed as the
``terp-spec`` / ``@terp/spec`` packages, pinned by release tag) and Terp
Studio in its own private repository. This guard fails the build the moment
code re-couples them:

* nothing in the framework locates the spec by repo-relative path — the only
  seam is the ``terp_spec`` accessor / ``@terp/spec`` package resolution;
* nothing in the framework references ``studio/`` at all;
* the split units never silently return as directories or workspace members.
"""

from __future__ import annotations

import pathlib
import re

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
        "the spec is a dependency (terp-spec / @terp/spec), never a repo-relative path "
        f"(ADR 0082) — construct it via terp_spec.spec_dir() or @terp/spec: {offenders}"
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
    assert 'git = "https://github.com/AITT-NL/terp-spec"' in root_pyproject, (
        "terp-spec resolves from its own repository (git/registry pin, ADR 0082)"
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
