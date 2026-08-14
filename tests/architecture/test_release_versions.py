"""Release versions stay in lockstep (ADR 0063).

Terp ships as one platform released at one version: every backend distribution
(``packages/backend/**/pyproject.toml``) and every publishable frontend package
(``packages/frontend/*/package.json``) must carry the same version, and the npm packages
must be publishable (not ``private``). The release workflow publishes them all from one
tag — a stray version here would ship a partial, inconsistent release, so the gate fails
it at build time instead.
"""

from __future__ import annotations

import json
import pathlib
import re
import tomllib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

_BACKEND_PYPROJECTS = sorted(
    list(pathlib.Path(_REPO_ROOT / "packages" / "backend").glob("*/pyproject.toml"))
    + list(pathlib.Path(_REPO_ROOT / "packages" / "backend").glob("capabilities/*/pyproject.toml"))
)
_FRONTEND_MANIFESTS = sorted(
    pathlib.Path(_REPO_ROOT / "packages" / "frontend").glob("*/package.json")
)
_TEMPLATE_PYPROJECT = _REPO_ROOT / "template" / "project" / "pyproject.toml.jinja"
#: *Every* manifest a generated app ships, not just the frontend's. The conformance
#: suite pins @terpjs/conformance in a second manifest, and a test that named only the
#: frontend one left it outside the ratchet — where it sat four releases stale until an
#: app installed it. A lockstep guarantee is only as wide as the files it reads.
_TEMPLATE_FRONTEND_MANIFESTS = sorted(
    (_REPO_ROOT / "template" / "project").rglob("package.json.jinja")
)

_RELEASE_VERSION = "0.6.0"


def _pyproject_version(path: pathlib.Path) -> str:
    match = re.search(r'^version = "([^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{path} declares no version"
    return match.group(1)


def _pyproject_name(path: pathlib.Path) -> str:
    match = re.search(r'^name = "([^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{path} declares no name"
    return match.group(1)


def _pyproject_dependencies(path: pathlib.Path) -> list[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data["project"]
    dependencies = list(project.get("dependencies", ()))
    for extra_dependencies in project.get("optional-dependencies", {}).values():
        dependencies.extend(extra_dependencies)
    return dependencies


def _template_dependencies(path: pathlib.Path) -> list[str]:
    """Read quoted requirements from the Jinja template, which is not valid TOML."""
    text = path.read_text(encoding="utf-8")
    return re.findall(r'^\s*"([^"]+)"', text, re.MULTILINE)


_BACKEND_INTERNAL = {_pyproject_name(path) for path in _BACKEND_PYPROJECTS}
_FRONTEND_INTERNAL = {
    json.loads(path.read_text(encoding="utf-8"))["name"] for path in _FRONTEND_MANIFESTS
}


def test_release_scope_is_nonempty() -> None:
    assert len(_BACKEND_PYPROJECTS) >= 15
    assert len(_FRONTEND_MANIFESTS) == 4


@pytest.mark.parametrize("path", _BACKEND_PYPROJECTS, ids=lambda p: p.parent.name)
def test_backend_distributions_share_the_release_version(path: pathlib.Path) -> None:
    assert _pyproject_version(path) == _RELEASE_VERSION


@pytest.mark.parametrize("path", _BACKEND_PYPROJECTS, ids=lambda p: p.parent.name)
def test_backend_internal_dependencies_are_lockstep_pinned(path: pathlib.Path) -> None:
    for dependency in _pyproject_dependencies(path):
        name = re.split(r"[<>=!~;\\[]", dependency, maxsplit=1)[0]
        if name in _BACKEND_INTERNAL:
            assert dependency == f"{name}=={_RELEASE_VERSION}"


@pytest.mark.parametrize("path", _BACKEND_PYPROJECTS, ids=lambda p: p.parent.name)
def test_backend_distributions_say_where_they_come_from(path: pathlib.Path) -> None:
    """Every wheel names its repository and changelog in ``[project.urls]``.

    The release notes ship inside the terp-core wheel, so they end at the
    *installed* version — the notes for a release an app does not have yet are
    only reachable through the repository. Before these URLs existed, installed
    metadata was silent about where the packages come from, and "read what
    changed before upgrading" started with a search instead of ``pip show``.
    """
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    urls = data["project"].get("urls", {})
    assert urls.get("Repository") == "https://github.com/AITT-NL/terp-framework"
    assert (
        urls.get("Changelog")
        == "https://github.com/AITT-NL/terp-framework/blob/main/CHANGELOG.md"
    )


@pytest.mark.parametrize("path", _FRONTEND_MANIFESTS, ids=lambda p: p.parent.name)
def test_frontend_packages_say_where_they_come_from(path: pathlib.Path) -> None:
    """The npm packages carry the same provenance pointer as the wheels."""
    data = json.loads(path.read_text(encoding="utf-8"))
    repository = data.get("repository") or {}
    assert repository.get("url") == "git+https://github.com/AITT-NL/terp-framework.git"


def test_template_backend_dependencies_are_lockstep_pinned() -> None:
    for dependency in _template_dependencies(_TEMPLATE_PYPROJECT):
        name = re.split(r"[<>=!~;\\[]", dependency, maxsplit=1)[0]
        if name in _BACKEND_INTERNAL:
            assert dependency == f"{name}=={_RELEASE_VERSION}"


@pytest.mark.parametrize("path", _FRONTEND_MANIFESTS, ids=lambda p: p.parent.name)
def test_frontend_packages_share_the_release_version_and_are_publishable(
    path: pathlib.Path,
) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == _RELEASE_VERSION
    assert data.get("private") is not True, f"{data['name']} must be publishable"
    assert data.get("publishConfig", {}).get("access") == "public"


@pytest.mark.parametrize("path", _FRONTEND_MANIFESTS, ids=lambda p: p.parent.name)
def test_frontend_internal_dependencies_are_lockstep_ranged(path: pathlib.Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for dependencies_key in ("dependencies", "devDependencies", "peerDependencies"):
        for name, range_ in data.get(dependencies_key, {}).items():
            if name in _FRONTEND_INTERNAL:
                assert range_ == f"^{_RELEASE_VERSION}"


@pytest.mark.parametrize(
    "path", _TEMPLATE_FRONTEND_MANIFESTS, ids=lambda p: p.parent.name
)
def test_template_frontend_dependencies_are_lockstep_ranged(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    for name in _FRONTEND_INTERNAL:
        match = re.search(rf'"{re.escape(name)}": "([^"]+)"', text)
        if match:
            assert match.group(1) == f"^{_RELEASE_VERSION}"


def test_every_template_manifest_is_covered() -> None:
    """The parametrisation above must actually reach every manifest.

    Named paths are how the conformance manifest went stale unnoticed. Discovery closes
    that, but discovery that quietly finds nothing is the same hole with fewer symptoms,
    so the count is asserted: a new manifest joins the ratchet or this fails.
    """
    names = {path.parent.name for path in _TEMPLATE_FRONTEND_MANIFESTS}
    assert {"frontend", "conformance"} <= names, names


def test_the_conformance_package_publishes_runnable_javascript() -> None:
    """@terpjs/conformance ships compiled JS, unlike its source-publishing siblings.

    react-core and contract are imported by an app's Vite build, which compiles
    TypeScript, so exporting ``./src/index.ts`` costs them nothing. This package is
    imported by Playwright's runner from inside ``node_modules``, where Node refuses to
    strip types outright — a raw-TypeScript export is not merely unidiomatic there, it
    is unloadable, and the failure lands in a consuming app's CI ("No tests found")
    rather than in this repo, whose own suite imports ``../src`` and never notices.
    """
    path = _REPO_ROOT / "packages" / "frontend" / "conformance" / "package.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    entry = data["exports"]["."]
    assert entry["default"].endswith(".js"), entry
    assert entry["types"].endswith(".d.ts"), entry
    assert data["main"].endswith(".js"), data["main"]
    assert data["types"].endswith(".d.ts"), data["types"]

    # The build is what makes those paths exist, and ``prepack`` is what makes a publish
    # run it — without the hook the manifest would promise a dist that a hand-rolled
    # ``npm publish`` never produced, which is a worse failure than the one being fixed.
    assert data["scripts"]["prepack"] == "npm run build"
    assert "dist" in data["files"]


def test_changelog_records_the_release_version() -> None:
    changelog = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {_RELEASE_VERSION}" in changelog
