"""Module-shape rule: a module exposes the canonical, predictable surface.

Every ``modules/<name>`` carries the same four files — ``models`` / ``schemas`` /
``service`` / ``router`` — so an agent (or a human) finds the table, the DTOs, the
service, and the routes in the same place in every module, and the other rules have
the surface they assume.
"""

from __future__ import annotations

import pathlib

from terp.arch.rules._support import ArchViolation

# The fixed slots every module carries. ``module.py`` (the manifest) is included so a
# module dir missing its manifest is flagged, not silently skipped.
_CANONICAL_FILES: tuple[str, ...] = (
    "models.py",
    "schemas.py",
    "service.py",
    "router.py",
    "module.py",
)

# The files that mark a directory as a *real, wired* module: a manifest (``module.py``) or
# a mounted ``router.py``. Once a dir ships either, it must carry the full canonical shape
# — so a module dir missing its ``module.py`` (previously invisible to this rule AND to
# ``modules_declare_policy``) is now flagged. A dir with only a stray ``service`` /
# ``models`` file (no manifest, no router — a partial or a shared helper) is left alone.
_MODULE_SIGNAL_FILES: tuple[str, ...] = ("module.py", "router.py")


def check_canonical_module_shape(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every wired ``modules/<name>`` dir carries ``models`` / ``schemas`` / ``service`` / ``router`` / ``module``.

    Terp modules are uniform on purpose: the table lives in ``models``, the DTOs in
    ``schemas``, the logic in ``service``, the routes in ``router``, and the manifest in
    ``module`` — so the shape is predictable to discover and the other rules (response
    models, input caps, audited writes, the declared ``Policy``) have the surface they
    scan. A directory under ``modules/`` is treated as a module once it ships a manifest
    (``module.py``) **or** a mounted ``router.py``; it must then carry **all** of the
    canonical files, and the rule names each missing one. Including ``module.py`` in the
    required set is deliberate: a dir that ships a router with no manifest would otherwise
    be invisible to this rule *and* to ``modules_declare_policy`` (which only scans
    ``module.py``), so it could mount a router with no declared Policy unnoticed. A dir
    with neither signal (a partial or a shared-asset / helper dir) is left alone.
    """
    root = pathlib.Path(app_root)
    modules_dir = root / "modules"
    if not modules_dir.is_dir():
        return []
    violations: list[ArchViolation] = []
    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue
        if not any((module_dir / signal).is_file() for signal in _MODULE_SIGNAL_FILES):
            continue  # not a wired module (no manifest, no router) — left alone
        for filename in _CANONICAL_FILES:
            if not (module_dir / filename).is_file():
                violations.append(
                    ArchViolation(
                        "canonical_module_shape",
                        f"{root.name}/modules/{module_dir.name}",
                        1,
                        f"module {module_dir.name!r} is missing {filename!r}; a module dir must "
                        "carry models/schemas/service/router/module (the canonical shape)",
                    )
                )
    return violations
