"""``terp verify --only api-contract``: the committed contract held to the composed app (ADR 0194).

A client that is not the app's own frontend — a native app already installed on a phone, a
site built in another repository — is compiled against the API's shape at one moment and runs
against whatever the app serves afterwards. The production profile hides the schema, rightly,
so the shape travels as a committed ``openapi.json``, and this holds that file to the app.

Adoption is opt-in and half-adoption impossible, the shape ``authz-surface`` settled on: an
untracked contract skips with a note naming the command that adopts it. The pin is exact,
because the committed file is what other repositories pin; every difference is reported in the
vocabulary of the change, breaking lines first, and the writer is ``terp openapi``, never a
``--fix`` on this.

Two answers are never read as a skip, because each would pass a comparison never made. git's
silence is not "untracked": only ``git ls-files --error-unmatch`` naming the path it does not
know is, and any other failure (no git, no work tree, a repository git refuses to read because
another user owns it) is red, with git's own words and the remedy. And an app that does not
compose is not an app that is absent: the check skips only when there is no ``app/`` package
at all, the way ``production-readiness`` skips only when there is no ``control_plane/``.
"""

from __future__ import annotations

import contextlib
import pathlib
import sys
from dataclasses import dataclass

from terp.cli.api_contract import ADOPT_HINT, CONTRACT_ARTIFACT, diff_contract, read_contract, render_changes

#: The app reference ``terp openapi`` loads by default. The check composes the same one, so it
#: compares the committed file with exactly what regenerating it would write.
APP_REF = "app.main:app"

#: What git writes, in the C locale it is run in, for a path it does not track.
_UNTRACKED = "did not match any file(s) known to git"

#: Where a check tells the reader to run, when git cannot answer from where it ran.
_REMEDY = (
    "Run the gate inside the app's git work tree; if git refuses the repository because "
    "another user owns it (a checkout mounted into a container), mark it safe as its message "
    "says: git config --global --add safe.directory <the repository>"
)


@dataclass(frozen=True)
class Tracking:
    """git's answer for the contract: ``tracked``, ``untracked``, or ``unknown`` and why."""

    state: str
    exit_code: int = 0
    said: str = ""

    def refusal(self, consequence: str) -> str:
        """The red for a check that cannot go on without git's answer, naming the remedy."""
        from terp.cli.verify import _NOT_FOUND

        if self.exit_code == _NOT_FOUND:
            return (
                f"{self.said} - git is asked whether {CONTRACT_ARTIFACT} is tracked, so "
                f"{consequence}; install git, or run the gate where it is installed"
            )
        return (
            f"git could not say whether {CONTRACT_ARTIFACT} is tracked "
            f"(git ls-files exited {self.exit_code}):\n  {self.said}\n"
            f"so {consequence}. {_REMEDY}"
        )


def contract_tracking(root: pathlib.Path) -> Tracking:
    """Ask git whether the contract is tracked, and keep its answer apart from its silence.

    ``git ls-files --error-unmatch`` exits 1 and names the pathspec for a file git does not
    track, and that is the only "untracked". git runs in the C locale, so the words matched
    are git's own and never a translation of them.
    """
    from terp.cli.verify import _run_argv

    completed = _run_argv(
        ["git", "ls-files", "--error-unmatch", "--", CONTRACT_ARTIFACT], root, env={"LC_ALL": "C"}
    )
    if completed.returncode == 0:
        return Tracking("tracked")
    if completed.returncode == 1 and _UNTRACKED in completed.stderr:
        return Tracking("untracked")
    said = (completed.stderr or completed.stdout).strip() or "git printed nothing"
    return Tracking("unknown", completed.returncode, "\n  ".join(said.splitlines()))


def run_api_contract_check(project_root: pathlib.Path) -> tuple[int, str]:
    """Refuse a change to the app's API that its committed contract does not record."""
    from terp.cli._appref import load_app, push_app_root
    from terp.cli.openapi import openapi_document
    from terp.cli.verify import NOTE_PREFIX

    tracking = contract_tracking(project_root)
    if tracking.state == "unknown":
        return tracking.exit_code, tracking.refusal(
            "whether the API contract is pinned cannot be established, and the check does not guess"
        )
    if tracking.state == "untracked":
        return (
            0,
            f"{NOTE_PREFIX}{CONTRACT_ARTIFACT} is not tracked - the API contract is not "
            f"pinned, drift check skipped (adopt with: {ADOPT_HINT})",
        )
    try:
        committed = read_contract(project_root)
    except (OSError, ValueError, RecursionError) as exc:
        return 1, (
            f"{CONTRACT_ARTIFACT} is tracked but is not a readable JSON document ({exc}), "
            f"so there is no contract to hold the app to; regenerate it with: {ADOPT_HINT}"
        )
    if not (project_root / "app").is_dir():
        return 0, (
            f"{NOTE_PREFIX}no app/ package - {CONTRACT_ARTIFACT} is tracked, but nothing here "
            f"composes {APP_REF} to hold it to; skipped"
        )
    push_app_root(project_root)
    try:
        # Composing imports the app, and an app that prints on import would write into the
        # one channel `terp verify --format json` reports on: its stdout goes to stderr here.
        with contextlib.redirect_stdout(sys.stderr):
            live = openapi_document(load_app(APP_REF))
    except (SystemExit, Exception) as exc:  # noqa: BLE001 - any failure to compose is the app's answer
        return 1, (
            f"{APP_REF} could not be composed, so whether {CONTRACT_ARTIFACT} still describes "
            f"the API this app serves cannot be established: {type(exc).__name__}: {exc}\n"
            "Fix what stops the app from composing: `uv run terp openapi` composes it the same "
            "way and shows the same error."
        )
    try:
        changes = diff_contract(committed, live)
    except RecursionError:
        # A document nested past what the comparison walks is red, with its name, rather than
        # a traceback that ends the run and leaves every later check of the profile unreported.
        return 1, (
            f"{CONTRACT_ARTIFACT} or the API the composed app serves is nested deeper than this "
            f"check compares, so whether the file still describes the API cannot be established. "
            f"Regenerate the contract with: {ADOPT_HINT}, and review the change by hand"
        )
    if not changes:
        return 0, f"{CONTRACT_ARTIFACT} matches the API the composed app serves"
    breaking = sum(1 for change in changes if change.breaking)
    return 1, (
        f"the API changed in {len(changes)} way(s) that {CONTRACT_ARTIFACT} does not "
        f"record, {breaking} of them breaking:\n{render_changes(changes)}\n\n"
        "A BREAKING line is one a client built against the committed contract fails on: "
        "a native app already installed, or a site that builds from the file. If every "
        "line is intended, re-generate the contract IN THE SAME CHANGE so a reviewer sees "
        f"the diff:\n  {ADOPT_HINT}"
    )


__all__ = ["APP_REF", "Tracking", "contract_tracking", "run_api_contract_check"]
