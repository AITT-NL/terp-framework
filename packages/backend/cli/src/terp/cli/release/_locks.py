"""The two locks a release is built from, read as data (ADR 0187 decision 6).

``uv.lock`` and ``frontend/package-lock.json`` say exactly what the images install, so the
release jobs read them instead of asking a package manager: no resolver runs, no index is
contacted, and nothing the app configured (an index URL, a ``uv.toml``) can steer what is read.
They answer five questions: which terp versions the commit pins, whether a lock names a package
by a path (a path a pristine context of the commit does not hold), which sources the build
fetches from, which distributions the backend image must hold, and which packages the web
bundle was built from.
"""

from __future__ import annotations

import json
import re
import tomllib
import urllib.parse
from collections.abc import Mapping
from typing import Any

from terp.cli.release._common import ReleaseError

UV_LOCK = "uv.lock"
NPM_LOCK = "frontend/package-lock.json"

#: The keys a uv source uses to name a package by where it lies on disk.
_PATH_KEYS = ("path", "directory", "editable", "virtual")


def normalise(name: str) -> str:
    """A distribution name as PEP 503 compares it."""
    return re.sub(r"[-_.]+", "-", name).lower()


def read_uv_lock(text: str) -> dict[str, Any]:
    """``uv.lock`` parsed, refused when it is not one."""
    try:
        lock = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ReleaseError(f"{UV_LOCK} is not TOML", cause=str(exc)) from exc
    if not isinstance(lock.get("package"), list):
        raise ReleaseError(f"{UV_LOCK} holds no [[package]] table")
    return lock


def _packages(lock: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in lock["package"] if isinstance(entry, dict) and "name" in entry]


def _is_root(entry: Mapping[str, Any]) -> bool:
    source = entry.get("source", {})
    return any(source.get(key) == "." for key in ("editable", "virtual"))


def pinned(lock: Mapping[str, Any], name: str) -> str | None:
    """The version the lock pins *name* at, or ``None`` when it does not lock it."""
    found = {
        str(entry.get("version")) for entry in _packages(lock) if normalise(entry["name"]) == name
    }
    return found.pop() if len(found) == 1 else None


def path_sources(lock: Mapping[str, Any]) -> list[str]:
    """Every package the lock names by a path, but the project itself (``.``)."""
    found: list[str] = []
    for entry in _packages(lock):
        source = entry.get("source", {})
        for key in _PATH_KEYS:
            if key in source and not (_is_root(entry) and source[key] == "."):
                found.append(f"{entry['name']} ({key} = {source[key]!r})")
    return found


def python_sources(lock: Mapping[str, Any]) -> list[str]:
    """Where the build fetches each locked distribution from: registries, git, URLs."""
    found: set[str] = set()
    for entry in _packages(lock):
        source = entry.get("source", {})
        for key in ("registry", "git", "url"):
            if isinstance(source.get(key), str):
                found.add(source[key] if key == "registry" else f"{key}+{source[key]}")
    return sorted(found)


def marker_environment(python: str, machine: str) -> dict[str, str]:
    """The PEP 508 environment of a CPython *python* (``3.14.8``) on Linux *machine*."""
    parts = python.split(".")
    return {
        "implementation_name": "cpython",
        "implementation_version": python,
        "os_name": "posix",
        "platform_machine": machine,
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": "Linux",
        "platform_version": "",
        "python_full_version": python,
        "python_version": ".".join(parts[:2]),
        "sys_platform": "linux",
        "extra": "",
    }


def _applies(edge: Mapping[str, Any], environment: Mapping[str, str]) -> bool:
    marker = edge.get("marker")
    if not marker:
        return True
    try:
        from packaging.markers import InvalidMarker, Marker
    except ImportError as exc:
        raise ReleaseError("evaluating a lock's markers needs terp-cli[release]") from exc
    try:
        return Marker(marker).evaluate(dict(environment))
    except InvalidMarker as exc:
        raise ReleaseError(f"{UV_LOCK} carries a marker this signer cannot read", cause=str(exc)) from exc


def runtime_set(
    lock: Mapping[str, Any], project: str, environment: Mapping[str, str]
) -> list[tuple[str, str]]:
    """``(name, version)`` of every distribution ``uv sync --locked --no-dev`` installs, sorted.

    The project's own dependencies and what they need, with every edge's marker evaluated for
    *environment* and every extra an edge asks for; never a development group.
    """
    index: dict[str, list[dict[str, Any]]] = {}
    for entry in _packages(lock):
        index.setdefault(normalise(entry["name"]), []).append(entry)
    roots = [entry for entry in index.get(normalise(project), []) if _is_root(entry)]
    if len(roots) != 1:
        raise ReleaseError(f"{UV_LOCK} does not lock the project {project} itself")

    def resolve(edge: Mapping[str, Any]) -> dict[str, Any]:
        candidates = [
            entry
            for entry in index.get(normalise(str(edge.get("name", ""))), [])
            if "version" not in edge or str(entry.get("version")) == str(edge["version"])
        ]
        if len(candidates) != 1:
            raise ReleaseError(f"{UV_LOCK} names {edge.get('name')!r} ambiguously or not at all")
        return candidates[0]

    found: dict[str, str] = {}
    seen: set[tuple[str, str, frozenset[str]]] = set()
    pending: list[tuple[dict[str, Any], frozenset[str]]] = [
        (resolve(edge), frozenset(edge.get("extra", ())))
        for edge in roots[0].get("dependencies", [])
        if _applies(edge, environment)
    ]
    while pending:
        entry, extras = pending.pop()
        key = (normalise(entry["name"]), str(entry.get("version")), extras)
        if key in seen:
            continue
        seen.add(key)
        found[key[0]] = key[1]
        edges = list(entry.get("dependencies", []))
        for extra in sorted(extras):
            edges.extend(entry.get("optional-dependencies", {}).get(extra, []))
        pending.extend(
            (resolve(edge), frozenset(edge.get("extra", ())))
            for edge in edges
            if _applies(edge, environment)
        )
    return sorted(found.items())


def read_npm_lock(text: str) -> dict[str, Any]:
    """``frontend/package-lock.json`` parsed, refused when it is not a v2 or v3 lock."""
    try:
        lock = json.loads(text)
    except ValueError as exc:
        raise ReleaseError(f"{NPM_LOCK} is not JSON", cause=str(exc)) from exc
    if not isinstance(lock, dict) or not isinstance(lock.get("packages"), dict):
        raise ReleaseError(f"{NPM_LOCK} is not a lockfile npm ci reads (no packages object)")
    return lock


def _npm_entries(lock: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (key, entry)
        for key, entry in sorted(lock["packages"].items())
        if key and isinstance(entry, dict)
    ]


def npm_path_sources(lock: Mapping[str, Any]) -> list[str]:
    """Every package the frontend lock takes from a path or links in from one."""
    return [
        key
        for key, entry in _npm_entries(lock)
        if entry.get("link") is True or str(entry.get("resolved", "")).startswith("file:")
    ]


def npm_hosts(lock: Mapping[str, Any]) -> list[str]:
    """The hosts ``npm ci`` fetches the frontend's packages from."""
    hosts = {
        urllib.parse.urlsplit(str(entry["resolved"])).hostname or ""
        for _key, entry in _npm_entries(lock)
        if str(entry.get("resolved", "")).startswith(("https://", "http://"))
    }
    return sorted(host for host in hosts if host)


def npm_packages(lock: Mapping[str, Any]) -> list[tuple[str, str]]:
    """``(name, version)`` of every package ``npm ci`` installs to build the bundle, sorted."""
    found = {
        (str(entry.get("name") or key.rsplit("node_modules/", 1)[-1]), str(entry["version"]))
        for key, entry in _npm_entries(lock)
        if "version" in entry and "node_modules/" in key
    }
    return sorted(found)


__all__ = [
    "NPM_LOCK",
    "UV_LOCK",
    "marker_environment",
    "normalise",
    "npm_hosts",
    "npm_packages",
    "npm_path_sources",
    "path_sources",
    "pinned",
    "python_sources",
    "read_npm_lock",
    "read_uv_lock",
    "runtime_set",
]
