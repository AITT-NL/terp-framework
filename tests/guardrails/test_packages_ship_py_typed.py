"""Guardrail: every shipped Terp distribution carries a PEP 561 ``py.typed`` marker.

Without the marker a downstream type-checker silently **ignores** a package's inline
types (PEP 561), so the framework's carefully-typed public surface would be invisible
to consumers. This walks each package's hatch ``only-include`` target and asserts the
marker file exists, so a new package can never ship untyped by omission.
"""

from __future__ import annotations

import pathlib
import tomllib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "packages" / "backend"


def _owned_package_dirs() -> list[pathlib.Path]:
    """The distribution-owned package dir for every backend ``pyproject.toml``."""
    dirs: list[pathlib.Path] = []
    for pyproject in _BACKEND.glob("**/pyproject.toml"):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        wheel = (
            data.get("tool", {})
            .get("hatch", {})
            .get("build", {})
            .get("targets", {})
            .get("wheel", {})
        )
        for rel in wheel.get("only-include", []):
            dirs.append(pyproject.parent / rel)
    return dirs


def test_every_distribution_ships_py_typed() -> None:
    package_dirs = _owned_package_dirs()
    assert package_dirs, "no hatch packages were discovered under packages/backend"
    missing = [
        str(directory.relative_to(_REPO_ROOT))
        for directory in package_dirs
        if not (directory / "py.typed").is_file()
    ]
    assert not missing, (
        "every shipped distribution must carry a PEP 561 py.typed marker so its "
        f"inline types are exported; missing in: {sorted(missing)}"
    )
