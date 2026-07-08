"""Event-bus rule: emitted / subscribed events are typed catalog constants.

The bus carries the same no-drift guarantee as the permission model — every event
named anywhere (``emit`` / ``subscribe`` / ``ModuleSpec`` / ``LifecycleEventMap``)
is a typed ``EventDefinition`` from the control-plane catalog, never a bare string.
"""

from __future__ import annotations

import ast
import pathlib

from terp.arch._ast import base_name, iter_python_files, parse
from terp.arch.rules._support import ArchViolation, _rel


def _event_ref_violation(
    value: ast.expr, rel: str, where: str
) -> ArchViolation | None:
    """Flag an event reference that is a bare string or an inline ``EventDefinition(...)``.

    A typed reference (a ``Name`` / ``Attribute`` pointing at a declared catalog
    constant) is allowed; ``None`` is allowed (the explicit "no event" sentinel a
    ``LifecycleEventMap`` uses); anything else — a bare string or an inline
    ``EventDefinition(...)`` — would let an event name drift in as a literal.
    """
    if isinstance(value, ast.Constant):
        if value.value is None:
            return None
        what = "a string literal" if isinstance(value.value, str) else "a literal"
    elif isinstance(value, ast.Call):
        what = "an inline EventDefinition(...)"
    else:
        return None
    return ArchViolation(
        "events_reference_catalog",
        rel,
        value.lineno,
        f"{where} must reference a typed EventDefinition constant from the "
        f"control-plane events catalog, not {what}",
    )


def check_events_reference_catalog(
    app_root: str | pathlib.Path, *, package: str = "app"
) -> list[ArchViolation]:
    """Emitted / subscribed events are typed catalog constants, never bare strings.

    The event bus carries the same no-drift guarantee as the permission model:
    every event a module emits or subscribes to is a typed
    :class:`~terp.core.EventDefinition` from the control-plane catalog. This rule
    forbids a bare string (or an inline ``EventDefinition(...)``) wherever an event
    is named — the ``event=`` of an ``emit(...)`` call, the argument of a
    ``subscribe(...)`` decorator, the ``emits`` / ``subscribes`` lists of a
    ``ModuleSpec(...)``, and the ``created`` / ``updated`` / ``deleted`` of a
    ``LifecycleEventMap(...)`` — so an event name can never drift in outside the
    catalog.
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
            if name == "emit":
                candidates += [
                    (keyword.value, "emit(event=...)")
                    for keyword in node.keywords
                    if keyword.arg == "event"
                ]
            elif name == "subscribe" and node.args:
                candidates.append((node.args[0], "subscribe(...)"))
            elif name == "ModuleSpec":
                for keyword in node.keywords:
                    if keyword.arg in {"emits", "subscribes"} and isinstance(
                        keyword.value, ast.List | ast.Tuple
                    ):
                        candidates += [
                            (element, f"ModuleSpec({keyword.arg}=...)")
                            for element in keyword.value.elts
                        ]
            elif name == "LifecycleEventMap":
                candidates += [
                    (keyword.value, f"LifecycleEventMap({keyword.arg}=...)")
                    for keyword in node.keywords
                    if keyword.arg in {"created", "updated", "deleted"}
                ]
            for value, where in candidates:
                violation = _event_ref_violation(value, rel, where)
                if violation is not None:
                    violations.append(violation)
    return violations
