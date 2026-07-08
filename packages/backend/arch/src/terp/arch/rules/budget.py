"""Escape-hatch budget ratchet: ``# arch-allow-*`` marker counts must match the budget.

A standalone check (not in ``_ALL_RULES``) the orchestrator runs when a
``budget_path`` is supplied — the governed half of the escape-hatch mechanism
(design §8): opt-outs stay visible, greppable, and can only shrink.
"""

from __future__ import annotations

import json
import pathlib

from terp.arch._ast import iter_python_files
from terp.arch.rules._support import ArchViolation, _ALLOW_TOKEN_RE


def check_escape_hatch_budget(
    app_root: str | pathlib.Path,
    *,
    budget_path: str | pathlib.Path,
    package: str = "app",
) -> list[ArchViolation]:
    """``# arch-allow-*`` marker counts must match the checked-in budget (a ratchet).

    The budget is a JSON object ``{marker: count}`` checked into the client repo.
    Actual usage must equal it **exactly**: a marker that *rose* needs a justified
    budget bump in the same change; one that *dropped* must be lowered to lock in
    the win; an unbudgeted marker must be added with a justified count. This keeps
    every secure-by-default opt-out visible, greppable, and governed (design §8).
    """
    root = pathlib.Path(app_root)
    budget_file = pathlib.Path(budget_path)
    where = budget_file.name
    try:
        raw = budget_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [
            ArchViolation(
                "escape_hatch_budget",
                where,
                0,
                f"budget file not found: {budget_file}; create it (e.g. '{{}}') to govern opt-outs",
            )
        ]
    try:
        budget = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [ArchViolation("escape_hatch_budget", where, exc.lineno, f"budget is not valid JSON: {exc.msg}")]
    if not isinstance(budget, dict) or not all(
        isinstance(name, str) and isinstance(count, int) for name, count in budget.items()
    ):
        return [
            ArchViolation(
                "escape_hatch_budget",
                where,
                0,
                "budget must be a JSON object mapping each 'arch-allow-*' marker to an integer count",
            )
        ]

    actual: dict[str, int] = {}
    for path in iter_python_files(root):
        for token in _ALLOW_TOKEN_RE.findall(path.read_text(encoding="utf-8")):
            actual[token] = actual.get(token, 0) + 1

    violations: list[ArchViolation] = []
    for marker in sorted(set(budget) | set(actual)):
        expected = budget.get(marker)
        found = actual.get(marker, 0)
        if expected is None:
            violations.append(
                ArchViolation(
                    "escape_hatch_budget",
                    where,
                    0,
                    f"{marker!r} (x{found}) is not in the budget; add it with a justified count",
                )
            )
        elif found != expected:
            if found > expected:
                detail = "rose", "justify it and raise the budget in the same change"
            else:
                detail = "dropped", "lower the budget to lock in the win"
            violations.append(
                ArchViolation(
                    "escape_hatch_budget",
                    where,
                    0,
                    f"{marker!r} {detail[0]} to {found} (budget {expected}); {detail[1]}",
                )
            )
    return violations
