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
_TEMPLATE_FRONTEND_MANIFEST = (
    _REPO_ROOT / "template" / "project" / "frontend" / "package.json.jinja"
)

_RELEASE_VERSION = "0.1.0"


def _pyproject_version(path: pathlib.Path) -> str:
    match = re.search(r'^version = "([^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{path} declares no version"
    return match.group(1)


def _pyproject_name(path: pathlib.Path) -> str:
    match = re.search(r'^name = "([^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"{path} declares no name"
    return match.group(1)


def _pyproject_dependencies(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    matches = re.findall(r"^(?:dependencies|dev) = \[(.*?)^\]", text, re.MULTILINE | re.DOTALL)
    return [dependency for match in matches for dependency in re.findall(r'"([^"]+)"', match)]


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


def test_template_backend_dependencies_are_lockstep_pinned() -> None:
    for dependency in _pyproject_dependencies(_TEMPLATE_PYPROJECT):
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


def test_template_frontend_dependencies_are_lockstep_ranged() -> None:
    text = _TEMPLATE_FRONTEND_MANIFEST.read_text(encoding="utf-8")
    for name in _FRONTEND_INTERNAL:
        match = re.search(rf'"{re.escape(name)}": "([^"]+)"', text)
        if match:
            assert match.group(1) == f"^{_RELEASE_VERSION}"


def test_changelog_records_the_release_version() -> None:
    changelog = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {_RELEASE_VERSION}" in changelog
