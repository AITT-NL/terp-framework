"""Phase 6 gate (agent-visibility, §10): the vendored core mirror is unmodified.

"Packaged" must not mean "invisible". `vendor/terp-core/` is a **read-only,
byte-exact mirror** of the packaged `terp.core` source, present and indexed in the
workspace so an agent has monorepo-level visibility while the maintenance boundary
holds. This is the build-time half of the agent-visibility layer (design §10, item
3: ``test_vendored_core_unmodified``): if anyone edits core, the mirror drifts and
the gate fails closed — the agent reads the mirror but cannot fork it. The runtime
half is that the *packaged* `terp.core` (not the mirror) is what's installed and
imported; the mirror is never on the path.

Refresh after an intentional core change with::

    python -c "import shutil,pathlib; s=pathlib.Path('packages/backend/core/src/terp/core'); d=pathlib.Path('vendor/terp-core/src/terp/core'); shutil.rmtree(d); shutil.copytree(s,d,ignore=shutil.ignore_patterns('__pycache__'))"
"""

from __future__ import annotations

import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PACKAGED = _REPO_ROOT / "packages" / "backend" / "core" / "src" / "terp" / "core"
_VENDORED = _REPO_ROOT / "vendor" / "terp-core" / "src" / "terp" / "core"


def _snapshot(root: pathlib.Path) -> dict[str, bytes]:
    """Relative-path -> file bytes for every tracked file under ``root`` (no caches)."""
    return {
        str(p.relative_to(root).as_posix()): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def test_vendored_core_present() -> None:
    """Fail closed if the mirror is missing/empty (guards against false greens)."""
    assert _VENDORED.is_dir(), f"vendored core mirror missing: {_VENDORED}"
    files = {p.name for p in _VENDORED.rglob("*.py")}
    assert {"__init__.py", "base_models.py", "errors.py", "module_spec.py"} <= files


def test_vendored_core_unmodified() -> None:
    """`vendor/terp-core/` must byte-match the packaged `terp.core` (no edits, no drift)."""
    packaged = _snapshot(_PACKAGED)
    vendored = _snapshot(_VENDORED)

    missing = sorted(set(packaged) - set(vendored))
    extra = sorted(set(vendored) - set(packaged))
    changed = sorted(k for k in packaged.keys() & vendored.keys() if packaged[k] != vendored[k])

    assert not (missing or extra or changed), (
        "vendor/terp-core/ has drifted from the packaged terp.core source — it is a "
        "read-only mirror, edit packaged core then refresh the mirror (see module docstring):\n"
        + "".join(f"  - missing from mirror: {p}\n" for p in missing)
        + "".join(f"  - not in core: {p}\n" for p in extra)
        + "".join(f"  - modified: {p}\n" for p in changed)
    )
