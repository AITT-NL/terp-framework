"""Jobs rule: enqueued / declared jobs are typed catalog constants, never bare strings.

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
