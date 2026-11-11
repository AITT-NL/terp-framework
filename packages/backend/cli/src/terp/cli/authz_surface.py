"""``authz-surface`` — the authority baseline, and the drift check that pins it.

The access graph already replays enforcement rather than describing it: every allowance
in it is :func:`terp.core.module_spec.decide`'s own answer, computed by the same function
the kernel guard runs (ADR 0121 §4). So the platform can already *say* who may reach
what, exactly and truthfully, for any composed app.

What nothing did was **notice when that answer changed**. Widening a module's policy from
a named permission to a role tier, dropping a ``require_permission`` off a route, adding
an endpoint under a mount whose policy is public — each is a one-line edit, each changes
who can reach what, and each left every gate green. The projection was emitted for a pane
and for a CLI, and read by no check.

This is the check. It reduces the graph to the part that is an authority claim, compares
it against a committed baseline, and reports the difference in the vocabulary of the
change rather than as a JSON diff: *this route's requirement moved from X to Y*, *this
module became public*, *this endpoint is new and nothing has reviewed what it requires*.

The reduction, the record's name and the comparison are :mod:`terp.core.authz_surface`'s
and :mod:`terp.core.authz_changes`'s, because the app runs them again when it starts (ADR
0212). What is here is the verdict ``terp verify`` gives.

**Adoption is opt-in and half-adoption is impossible**, the shape ``api-docs-drift``
settled on: with no committed baseline the check skips with a note naming the command
that writes one, because upgrading the framework must not turn an app's gate red for a
feature it never wired. Once the file is tracked, drift is red.

**A widening is never "fixed" by regenerating.** The baseline is a review artifact: the
diff belongs in a pull request where somebody looks at it and says yes. Regenerating to
make a red go away converts the control into a formality, which is why the writer is a
separate, explicit command and never a ``--fix`` on the checker.
"""

from __future__ import annotations

import pathlib
import tomllib
from typing import Any, NamedTuple

from terp.core.authz_changes import authority_changes
from terp.core.authz_surface import (
    ADOPT_HINT,
    SURFACE_ARTIFACT,
    authz_surface,
    read_baseline,
    unseen_routes,
)


def diff_authz_surface(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Every authority difference, each phrased as the change a reviewer has to approve.

    The sentences of :func:`terp.core.authz_changes.authority_changes`, which also says of
    each whether it widens who can reach what (ADR 0209).
    """
    return [entry["change"] for entry in authority_changes(baseline, current)]


#: The checks an app may pin (``[tool.terp.verify] pinned``): with the line, a missing
#: artifact is red instead of a skip (ADR 0209).
PINNABLE = frozenset({"authz-surface"})


def pinned_problem(value: object) -> str:
    """Why a ``[tool.terp.verify] pinned`` value is refused, or ``""`` when it is not."""
    if value is None:
        return ""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return "[tool.terp.verify] `pinned` must be a list of check ids"
    unknown = sorted(set(value) - PINNABLE)
    if unknown:
        return (
            f"[tool.terp.verify] `pinned` names {', '.join(unknown)}; only "
            f"{', '.join(sorted(PINNABLE))} can be pinned"
        )
    return ""


def is_pinned(root: pathlib.Path) -> bool:
    """Whether the app's ``pyproject.toml`` pins ``authz-surface``.

    `terp verify` has already refused an unreadable file or a bad value before any check
    runs, so this only reads the answer.
    """
    try:
        declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    table = ((declared.get("tool") or {}).get("terp") or {}).get("verify") or {}
    pinned = table.get("pinned") if isinstance(table, dict) else None
    return isinstance(pinned, list) and "authz-surface" in pinned


class Verdict(NamedTuple):
    """The check's answer: its exit code and output, and the fields `--format json` adds.

    ``authority_state`` is one of ``not_pinned`` (no baseline and no pin: skipped),
    ``missing`` (pinned, no baseline), ``unseen`` (something the check cannot see),
    ``changed`` and ``matches``. ``authority_changes`` lists what changed, each entry
    labelled ``widens``; ``authority_unseen`` lists what the check cannot see. The two are
    kept apart because the second is code to fix and never a change to approve.
    """

    exit_code: int
    output: str
    fields: dict[str, Any]


def _fields(state: str, changes=(), unseen=()) -> dict[str, Any]:
    return {
        "authority_state": state,
        "authority_changes": list(changes),
        "authority_unseen": list(unseen),
    }


def verdict(project_root: pathlib.Path, app_ref: str, note_prefix: str) -> Verdict:
    """The ``authz-surface`` verify check over one tree.

    The access graph already replays enforcement — every allowance in it is `decide`'s
    own answer, from the function the kernel guard runs — so the platform could always
    *say* who may reach what. What nothing did was notice when the answer changed.
    Widening a module policy from a named permission to a role tier, dropping a
    `require_permission`, adding an endpoint under a public mount: each is a one-line
    edit that changes the authorization surface and left every gate green.

    Adoption is opt-in for an app made before ADR 0209, the shape `api-docs-drift` settled
    on: with no committed baseline and no `pinned` line this skips with a note naming the
    command that writes one, because upgrading the framework must not turn an app's gate
    red for a feature it never wired. The template pins every new app.

    A widening is never *fixed* by regenerating. The baseline is a review artifact, and
    the diff belongs in a pull request where somebody says yes — which is why the writer
    is a separate, explicit command and never a `--fix` on this.

    Once a tree pins its surface, what the check cannot see is red, never a pass: an app
    that cannot be composed, a route the access graph cannot place, a method and path two
    routes serve, and a difference no line of the diff names.
    """
    from terp.cli._appref import load_app, push_app_root
    from terp.cli.access import build_access_graph_for_app

    try:
        baseline = read_baseline(project_root)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        # An unreadable baseline is not an absent one: writing a fresh file over it would
        # accept whatever the app serves now, unseen. It is restored, not replaced.
        detail = (
            f"{SURFACE_ARTIFACT} cannot be read ({exc}), so nothing was checked. Restore the "
            "committed file from version control: writing it again would accept whatever the "
            f"app serves now. Only a file never committed is written again:\n  {ADOPT_HINT}"
        )
        unseen = [{"kind": "unreadable_baseline", "detail": detail}]
        return Verdict(1, detail, _fields("unseen", unseen=unseen))
    if baseline is None:
        if is_pinned(project_root):
            return Verdict(
                1,
                f"this app pins its authorization surface ([tool.terp.verify] pinned) and "
                f"has no {SURFACE_ARTIFACT}. Write it from the composed app and commit it:"
                f"\n  {ADOPT_HINT}",
                _fields("missing"),
            )
        return Verdict(
            0,
            f"{note_prefix}no {SURFACE_ARTIFACT} - the authorization surface is not "
            f"pinned, drift check skipped (adopt with: {ADOPT_HINT})",
            _fields("not_pinned"),
        )
    if not isinstance(baseline, dict):
        detail = f"{SURFACE_ARTIFACT} is not a surface (a JSON object); restore it."
        unseen = [{"kind": "unreadable_baseline", "detail": detail}]
        return Verdict(1, detail, _fields("unseen", unseen=unseen))
    push_app_root(project_root)
    try:
        app = load_app(app_ref)
        graph = build_access_graph_for_app(app)
    except (SystemExit, Exception) as exc:
        # The tree pins its surface, so an app that cannot be composed is an unchecked
        # surface, not an absent one. Skipping here passed every change for as long as
        # the app failed to import, which is the one moment nobody is looking. Whatever
        # stopped it is this answer: a factory that refuses to boot, or an app that
        # create_app did not compose, is as unchecked as a module that does not import,
        # and a traceback names no state a tool can read.
        detail = (
            f"{SURFACE_ARTIFACT} pins this app's authorization surface, but {app_ref} "
            f"could not be composed ({type(exc).__name__}: {exc}), so nothing was "
            "checked. Fix what stops the app composing, or remove the baseline in a "
            "change a reviewer sees."
        )
        unseen = [{"kind": "not_composed", "detail": detail}]
        return Verdict(1, detail, _fields("unseen", unseen=unseen))
    current = authz_surface(graph)
    # What the surface cannot see is refused before it is compared: a route the graph
    # could not place (a router included inside a module's router, served under a path
    # the graph cannot recover) and a method and path two routes serve. Either one makes
    # "no difference" an answer about a surface that is not the one being served.
    unseen = unseen_routes(graph.get("omitted_routes") or (), current)
    if unseen:
        listing = "\n".join(f"  - {item['detail']}" for item in unseen)
        return Verdict(
            1,
            f"the authorization surface cannot be checked: {len(unseen)} route(s) are "
            f"served in a way {SURFACE_ARTIFACT} cannot record:\n{listing}",
            _fields("unseen", unseen=unseen),
        )
    changes = authority_changes(baseline, current, graph)
    if not changes:
        matches = f"{SURFACE_ARTIFACT} matches the composed authorization surface"
        return Verdict(0, matches, _fields("matches"))
    ordered = [entry for entry in changes if entry["widens"]] + [
        entry for entry in changes if not entry["widens"]
    ]
    listing = "\n".join(
        f"  - {'widens' if entry['widens'] else 'narrows'}: {entry['change']}"
        for entry in ordered
    )
    return Verdict(
        1,
        f"the authorization surface changed in {len(changes)} way(s) that "
        f"{SURFACE_ARTIFACT} does not record:\n{listing}\n\n"
        "If every line above is intended, re-generate the baseline IN THE SAME CHANGE "
        f"so a reviewer sees the diff:\n  {ADOPT_HINT}",
        _fields("changed", changes=changes),
    )


def check(project_root: pathlib.Path, app_ref: str, *, note_prefix: str) -> tuple[int, str]:
    """:func:`verdict` without its JSON fields: ``(exit code, output)``."""
    result = verdict(project_root, app_ref, note_prefix)
    return result.exit_code, result.output
