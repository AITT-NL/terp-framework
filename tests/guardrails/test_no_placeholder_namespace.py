"""Guardrail: the placeholder ``agentic_platform`` namespace must not reappear.

The design was authored against a placeholder import namespace; ``terp.*`` is now
authoritative everywhere (see ``docs/decisions/0001-terp-namespace-and-kernel-scope.md``).

This is the **build-time layer** that keeps the rename from regressing in the
canonical + code artifacts: the design doc, the README, and all package / app /
template source. It deliberately does **not** scan ``docs/decisions/``, which
legitimately discusses the historical placeholder.

Pairs with the runtime/build layer (design §5, two-layer enforcement): the
identifiers actually shipped by every ``terp*`` distribution are ``terp.*``.
"""

from __future__ import annotations

import pathlib
import re

# tests/guardrails/test_no_placeholder_namespace.py → parents[2] == repo root
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Canonical + code locations that must use the authoritative `terp.*` identifiers.
_SCANNED_DIRS = ("packages", "apps", "template")
_SCANNED_ROOT_FILES = ("AGENTIC_PLATFORM_DESIGN.md", "README.md")
_SCANNED_SUFFIXES = {".py", ".md", ".toml", ".json", ".cfg", ".ini", ".txt", ".js", ".ts", ".tsx"}

# Lowercase placeholder identifier forms (`agentic_platform`, `agentic-platform`).
# Matched case-sensitively so the design doc's own *filename*
# (AGENTIC_PLATFORM_DESIGN.md, uppercase) is never a false positive.
_FORBIDDEN = re.compile(r"agentic[_-]platform")


def _iter_scanned_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for name in _SCANNED_ROOT_FILES:
        path = _REPO_ROOT / name
        if path.is_file():
            files.append(path)
    for dir_name in _SCANNED_DIRS:
        root = _REPO_ROOT / dir_name
        if root.is_dir():
            files.extend(
                p for p in root.rglob("*")
                if p.is_file() and p.suffix in _SCANNED_SUFFIXES
            )
    return files


def test_no_placeholder_namespace_in_canonical_artifacts() -> None:
    """`agentic_platform` must not appear in the design doc, README, or any source."""
    violations: list[str] = []
    for path in _iter_scanned_files():
        text = path.read_text(encoding="utf-8")
        for match in _FORBIDDEN.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(_REPO_ROOT)}:{line}: {match.group()!r}")

    assert not violations, (
        "The placeholder `agentic_platform` namespace must not appear in the design "
        "doc, README, or any package/app/template source — use `terp.*` (see "
        "docs/decisions/0001):\n" + "\n".join(f"  - {v}" for v in violations)
    )


def test_design_doc_pins_authoritative_namespace() -> None:
    """Positive check: the canonical design doc states the authoritative `terp.*` form."""
    design = (_REPO_ROOT / "AGENTIC_PLATFORM_DESIGN.md").read_text(encoding="utf-8")
    assert "from terp.core import ModuleSpec" in design, (
        "design doc must show the authoritative `from terp.core import ModuleSpec`"
    )
    assert "`terp.*`" in design, "design doc must pin the `terp.*` namespace"
