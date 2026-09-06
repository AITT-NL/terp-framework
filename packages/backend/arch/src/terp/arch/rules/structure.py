"""Module-shape rules: a module exposes the canonical surface, and it is tested.

Every ``modules/<name>`` carries the same four files — ``models`` / ``schemas`` /
``service`` / ``router`` — so an agent (or a human) finds the table, the DTOs, the
service, and the routes in the same place in every module, and the other rules have
the surface they assume.

:func:`check_modules_ship_tests` adds the part the shape never had. The canonical five
are all production files, so a module could satisfy every structural rule in the
Standard, mount routes, own a table, and ship with no tests at all — and
``terp scaffold`` emitted exactly those five, so that module was the *default*. The
tests are not in the module directory, though (ADR 0119): they live in the project's
``tests/``, which is where this platform's own tests live and where a test that drives
the composed app has to live.
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


# Where a project keeps its tests. ``app_root`` is the app *package* (``<project>/app``),
# so the tests tree is its sibling — the same reach ``_coverage_is_strict`` makes for the
# control plane, and for the same reason: the thing being checked is a property of the
# project, not of the package. The Standard's corpus cannot create a true sibling of the
# root it scans, so an in-root ``tests/`` is accepted too and a corpus case uses that.
_TESTS_DIR_NAME = "tests"


def _tests_roots(app_root: pathlib.Path) -> list[pathlib.Path]:
    """The project's ``tests/`` tree, and the in-root fallback the corpus needs."""
    return [
        candidate
        for candidate in (
            app_root.parent / _TESTS_DIR_NAME,
            app_root / _TESTS_DIR_NAME,
        )
        if candidate.is_dir()
    ]


def _module_is_tested(module: str, tests_roots: list[pathlib.Path]) -> bool:
    """Whether *module* has at least one test file the project associates with it.

    Two shapes count, and the asymmetry between them is the decision ADR 0119 records.
    ``tests/<module>/test_*.py`` is the canonical one: it is what ``terp scaffold``
    emits and what the guide teaches, because a module accumulates several test files
    and a directory holds them without anyone inventing a naming convention. A flat
    ``tests/test_<module>.py`` or ``tests/test_<module>_*.py`` is *recognised* rather
    than taught — the separator is required, so one module is never credited with a
    differently-named sibling's file. Refusing the flat form outright would
    fail an application whose modules are, in fact, tested, and whose only way out
    would be an escape-hatch marker reading "this module has no tests", which is
    false. A gate satisfiable only by a false statement is worse than a gate that
    accepts the same claim written two ways.
    """
    for tests_root in tests_roots:
        module_dir = tests_root / module
        if module_dir.is_dir() and any(module_dir.rglob("test_*.py")):
            return True
        # `test_<module>.py` or `test_<module>_<something>.py` — the separator is
        # required, so module `note` is not satisfied by `test_notes_api.py`, which
        # belongs to a different module and would be a silent false negative.
        if any(tests_root.glob(f"test_{module}.py")) or any(
            tests_root.glob(f"test_{module}_*.py")
        ):
            return True
    return False


def check_modules_ship_tests(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every wired ``modules/<name>`` has at least one test in the project's ``tests/``.

    The canonical shape is five production files, so until now a module could satisfy
    every structural rule in the Standard — mount routes, own a table, declare a policy
    — with no test of any kind, and ``terp scaffold`` emitted precisely those five. An
    untested module was not an oversight an application had to make; it was the shape
    the platform handed out.

    This rule asks only that the tests **exist and are attributable to the module**.
    Whether they are any good is a different question, already asked by
    ``no_empty_tests`` (which refuses a body that cannot fail) and by the app's own
    coverage gate. Two layouts satisfy it — the scaffolded ``tests/<name>/`` package,
    and a flat ``tests/test_<name>.py`` / ``tests/test_<name>_*.py`` — for the reason
    given on :func:`_module_is_tested`.

    A module that genuinely has no tests takes
    ``# arch-allow-modules-ship-tests: <reason>`` in its manifest, which spends the
    app's escape-hatch budget. That budget is already a shrink-only ratchet, so the
    adoption posture needs no new mechanism: the debt is counted, visible, and cannot
    grow silently.
    """
    root = pathlib.Path(app_root)
    modules_dir = root / "modules"
    if not modules_dir.is_dir():
        return []
    tests_roots = _tests_roots(root)
    violations: list[ArchViolation] = []
    for module_dir in sorted(modules_dir.iterdir()):
        if not module_dir.is_dir():
            continue
        if not any((module_dir / signal).is_file() for signal in _MODULE_SIGNAL_FILES):
            continue  # not a wired module — the same signal the canonical shape uses
        if _module_is_tested(module_dir.name, tests_roots):
            continue
        violations.append(
            ArchViolation(
                "modules_ship_tests",
                f"{root.name}/modules/{module_dir.name}",
                1,
                f"module {module_dir.name!r} ships no tests; add "
                f"tests/{module_dir.name}/test_*.py (the shape `terp scaffold` emits) "
                f"or a flat tests/test_{module_dir.name}_*.py",
            )
        )
    return violations
