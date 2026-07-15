"""Escape-hatch budget ratchet: ``# arch-allow-*`` marker counts must match the budget.

A standalone check (not in ``_ALL_RULES``) the orchestrator runs when a
``budget_path`` is supplied — the governed half of the escape-hatch mechanism
(design §8): opt-outs stay visible, greppable, and can only shrink.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re

from terp.arch._ast import _SECURITY_SKIP_DIRS, iter_python_files
from terp.arch.rules._support import (
    _ALLOW_MARKER_RE,
    _ALLOW_TOKEN_RE,
    ArchViolation,
    _file_comments,
    _rel,
)

#: The ``review-by:<YYYY-MM-DD>`` metadata token in a marker's reason (the Terp
#: Standard's escape-hatch contract): when the exception must be re-justified.
#: The tokens are a convention, not a gate — a reason without one is never
#: rejected — but the spec says a toolchain SHOULD surface *expired* dates.
_REVIEW_BY_RE = re.compile(r"review-by:\s*(\d{4}-\d{2}-\d{2})")


def _governed_tokens() -> set[str]:
    """Every marker token that names a rule with a governed opt-out.

    Derived from the live registry (imported lazily — the registry package
    imports this module). The escape-hatch governance rules themselves are
    excluded: governance cannot be waived by the mechanism it governs, so
    their tokens are invalid budget keys and invalid markers.
    """
    from terp.arch.rules import GUIDE_TOPIC_BY_RULE
    from terp.arch.rules._support import _rule_token

    ungoverned = {"escape_hatch_budget", "ungoverned_escape_hatch"}
    return {_rule_token(rule) for rule in GUIDE_TOPIC_BY_RULE if rule not in ungoverned}


def check_escape_hatch_budget(
    app_root: str | pathlib.Path,
    *,
    budget_path: str | pathlib.Path,
    package: str = "app",
    today: datetime.date | None = None,
) -> list[ArchViolation]:
    """``# arch-allow-*`` marker counts must match the checked-in budget (a ratchet).

    The budget is a JSON object ``{marker: count}`` checked into the client repo.
    Actual usage must equal it **exactly**: a marker that *rose* needs a justified
    budget bump in the same change; one that *dropped* must be lowered to lock in
    the win; an unbudgeted marker must be added with a justified count. A marker
    (or budget key) that names no rule with a governed opt-out — a typo, a stale
    name, or a governance rule's own token — is refused outright: an unknown
    marker can never be budgeted into legitimacy. Markers are counted from real
    comment tokens only. This keeps every secure-by-default opt-out visible,
    greppable, and governed (design §8).

    A marker reason MAY carry the spec's ``review-by:<YYYY-MM-DD>`` metadata
    token; one whose date has passed is surfaced as a violation on the marker's
    own line (re-justify the exception or remove it — a long-lived opt-out is
    never silently eternal). Reasons without the token are never rejected, and
    a malformed date is not a well-formed token (the convention is not a gate).
    *today* is injectable for tests; ``None`` means the real current date.
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
    expired: list[ArchViolation] = []
    review_deadline = today if today is not None else datetime.date.today()  # noqa: DTZ011 — date-only convention
    for path in iter_python_files(root, skip_dirs=_SECURITY_SKIP_DIRS):
        for lineno, comment in _file_comments(path.read_text(encoding="utf-8")):
            for token in _ALLOW_TOKEN_RE.findall(comment):
                actual[token] = actual.get(token, 0) + 1
            marker = _ALLOW_MARKER_RE.search(comment)
            if marker is None or not marker.group("why"):
                continue
            for value in _REVIEW_BY_RE.findall(marker.group("why")):
                try:
                    review_by = datetime.date.fromisoformat(value)
                except ValueError:
                    continue  # not a well-formed token; the convention is not a gate
                if review_by < review_deadline:
                    expired.append(
                        ArchViolation(
                            "escape_hatch_budget",
                            _rel(path, root),
                            lineno,
                            f"{marker.group('token')!r} opt-out review date passed "
                            f"(review-by:{value}); re-justify the exception with a "
                            "new review-by date or remove the marker",
                        )
                    )

    governed = _governed_tokens()
    violations: list[ArchViolation] = []
    for marker in sorted(set(budget) | set(actual)):
        if marker not in governed:
            violations.append(
                ArchViolation(
                    "escape_hatch_budget",
                    where,
                    0,
                    f"{marker!r} names no rule with a governed opt-out; remove the "
                    "marker/budget entry (opt-out markers name the catalog rule)",
                )
            )
            continue
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
    return violations + expired
