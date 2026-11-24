"""Jobs rules: enqueued / declared jobs are typed catalog constants, never bare strings; and a
schedule says what a missed tick becomes.

Background work carries the same no-drift guarantee as the event bus (ADR 0043 /
ADR 0008): every job named anywhere — the ``job=`` of an ``enqueue(...)`` call and the
``jobs`` list of a ``ModuleSpec(...)`` — is a typed ``JobDefinition`` from the
control-plane catalog, never a bare string or an inline ``JobDefinition(...)``. A job
referenced by name (so a remote worker can resolve its handler) cannot be a closure or
an ad-hoc literal that drifts past the catalog.
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel


def _job_ref_violation(
    value: ast.expr, rel: str, where: str
) -> ArchViolation | None:
    """Flag a job reference that is a bare string or an inline ``JobDefinition(...)``.

    A typed reference (a ``Name`` / ``Attribute`` pointing at a declared catalog
    constant) is allowed; a bare string or a literal would let a job name drift in
    outside the catalog, and an inline ``JobDefinition(...)`` bypasses it entirely.
    """
    if isinstance(value, ast.Constant):
        what = "a string literal" if isinstance(value.value, str) else "a literal"
    elif isinstance(value, ast.Call):
        what = "an inline JobDefinition(...)"
    else:
        return None
    return ArchViolation(
        "jobs_reference_catalog",
        rel,
        value.lineno,
        f"{where} must reference a typed JobDefinition constant from the "
        f"control-plane jobs catalog, not {what}",
    )


def check_jobs_reference_catalog(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Enqueued / declared jobs are typed catalog constants, never bare strings.

    Background work carries the same no-drift guarantee as the event bus: every job a
    module enqueues or declares is a typed :class:`~terp.core.JobDefinition` from the
    control-plane catalog. This rule forbids a bare string (or an inline
    ``JobDefinition(...)``) wherever a job is named — the ``job=`` of an ``enqueue(...)``
    call and the ``jobs`` list of a ``ModuleSpec(...)`` — so a job name can never drift in
    outside the catalog. Its runtime half is :func:`terp.core.enqueue`, which rejects a
    job not registered in the active catalog.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = base_name(node.func)
            candidates: list[tuple[ast.expr, str]] = []
            if name == "enqueue":
                candidates += [
                    (keyword.value, "enqueue(job=...)")
                    for keyword in node.keywords
                    if keyword.arg == "job"
                ]
            elif name == "ModuleSpec":
                for keyword in node.keywords:
                    if keyword.arg == "jobs" and isinstance(
                        keyword.value, ast.List | ast.Tuple
                    ):
                        candidates += [
                            (element, "ModuleSpec(jobs=...)")
                            for element in keyword.value.elts
                        ]
            for value, where in candidates:
                violation = _job_ref_violation(value, rel, where)
                if violation is not None:
                    violations.append(violation)
    return violations


#: The modules a schedule's definition is imported from, under any name the file gives it.
_SCHEDULE_MODULES = frozenset({"terp.core", "terp.core.scheduling"})


def _schedule_names(tree: ast.AST) -> set[str]:
    """The names this file calls ``ScheduleDefinition`` by: its own, and any alias of it."""
    names = {"ScheduleDefinition"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _SCHEDULE_MODULES:
            names.update(
                alias.asname for alias in node.names if alias.name == "ScheduleDefinition" and alias.asname
            )
    return names


def check_schedules_declare_misfire(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Every ``ScheduleDefinition(...)`` says what a missed tick becomes (ADR 0191, ADR 0222).

    ``misfire`` is a required keyword-only field: a definition without it is a
    ``TypeError`` where it is built, which is where the control plane is imported, before
    ``create_app`` asks anything else. A start therefore named it alone, and only once
    every refusal before it was fixed; the gate names every one with every other finding.
    A call that passes ``**`` keywords may carry it, so it is not read as missing it.
    """
    root = pathlib.Path(app_root)
    violations: list[ArchViolation] = []
    for path in iter_python_files(root):
        tree = parse(path)
        rel = _rel(path, root)
        names = _schedule_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            named = (isinstance(callee, ast.Name) and callee.id in names) or (
                isinstance(callee, ast.Attribute) and callee.attr == "ScheduleDefinition"
            )
            if not named or any(keyword.arg in ("misfire", None) for keyword in node.keywords):
                continue
            violations.append(
                ArchViolation(
                    "schedules_declare_misfire",
                    rel,
                    node.lineno,
                    "ScheduleDefinition(...) declares no misfire=: say what a tick that fell "
                    "due while no scheduler ran becomes, misfire=Misfire.RUN_ONCE or "
                    "misfire=Misfire.SKIP (ADR 0191); without it the control plane does not "
                    "import and the app does not start",
                )
            )
    return violations
