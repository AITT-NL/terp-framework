"""Where this repository keeps its rules (ADR 0203).

The rule catalog and its corpus are this framework's own, split by surface under one id
namespace: the backend half ships with ``terp-arch``, the frontend half with
``@terpjs/eslint-boundaries``. A catalog entry ships with the checker that enforces it, so
a toolchain carries the description of every rule it reports. The corpus is test data
beside its package, and ships with neither.

Every test that reads a rule's entry, its corpus or the refused surface finds them through
these names, so the layout is stated once.
"""

from __future__ import annotations

import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

_ARCH = REPO_ROOT / "packages" / "backend" / "arch"
_BOUNDARIES = REPO_ROOT / "packages" / "frontend" / "eslint-boundaries"

SURFACES = ("backend", "frontend")

#: The one schema every entry of both surfaces is held to.
CATALOG_SCHEMA = _ARCH / "src" / "terp" / "arch" / "catalog" / "schema.json"

_CATALOGS = {
    "backend": _ARCH / "src" / "terp" / "arch" / "catalog" / "backend",
    "frontend": _BOUNDARIES / "catalog" / "frontend",
}

#: Each corpus root holds that surface's cases under ``<surface>/<rule>/`` and its two
#: shrink-only ratchets, ``PENDING.json`` and ``RESIDUALS.json``.
_CORPUS_ROOTS = {
    "backend": _ARCH / "corpus",
    "frontend": _BOUNDARIES / "corpus",
}

#: The raw browser primitives app code must not author, which the frontend prohibition
#: rules cite and the ESLint adapter's ``BOUNDARY_SPEC`` is held to.
RESTRICTED_SURFACE = _BOUNDARIES / "restricted-surface.json"

#: The runtime security scenarios, beside the tests that run them.
RUNTIME_SECURITY = REPO_ROOT / "tests" / "runtime_security"


def catalog_dir(surface: str) -> pathlib.Path:
    return _CATALOGS[surface]


def corpus_root(surface: str) -> pathlib.Path:
    return _CORPUS_ROOTS[surface]


def corpus_dir(surface: str) -> pathlib.Path:
    return _CORPUS_ROOTS[surface] / surface


def entries(surface: str) -> dict[str, dict]:
    """Every catalog entry of *surface*, by rule name, each held to its path."""
    found: dict[str, dict] = {}
    for path in sorted(catalog_dir(surface).glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        assert entry["id"] == f"{surface}/{path.stem}", (
            f"{path}: id {entry['id']!r} must match its path ({surface}/{path.stem})"
        )
        found[path.stem] = entry
    # Guards every caller against a directory this stopped being able to see: an empty
    # mapping would make each test that iterates it pass while checking nothing.
    assert found, f"no catalog entries found under {catalog_dir(surface)}"
    return found


def blank_strings(value: object, where: str) -> list[str]:
    """Every string in *value* that is empty or only whitespace, by where it sits.

    The schema's ``minLength: 1`` counts characters, so ``"   "`` satisfies it. A blank
    title, intent or runtime rationale is still a statement of nothing, and the catalog's
    own suite refused it before the move by measuring length after stripping; this keeps
    that refusal without changing what the shared schema reader means by ``minLength``.
    """
    if isinstance(value, str):
        return [] if value.strip() else [where]
    if isinstance(value, dict):
        return [blank for key, item in value.items() for blank in blank_strings(item, f"{where}.{key}")]
    if isinstance(value, list):
        return [blank for index, item in enumerate(value) for blank in blank_strings(item, f"{where}[{index}]")]
    return []
