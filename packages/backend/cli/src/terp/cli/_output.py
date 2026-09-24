"""The one place ``terp``'s command dispatch writes to standard output.

A CLI's job is to print, so ``no_print`` is not a defect report against this package --
it is the reason ``packages/backend/cli`` is recorded in
``packages/backend/UNSCANNED.json`` rather than scanned. What the record is for is the
direction of travel: a count there may fall and never rise, so the dispatcher acquiring
one more bare ``print`` per command added is the shape that makes it rise forever.

One seam fixes that and is worth having on its own terms. Everything the dispatcher
says to an operator goes through here, which is where a ``--quiet``, a machine-readable
envelope, or a decision to route diagnostics to stderr would go. Thirty-eight call sites
answering that question independently is thirty-eight places such a change has to find.

Deliberately not a logger. This is a command's ANSWER, not a diagnostic about producing
it: it belongs on stdout unconditionally, it is what a shell pipes into the next thing,
and a log level that could suppress it would make the tool lie about having run.
"""

from __future__ import annotations

__all__ = ["emit"]


def emit(text: object = "") -> None:
    """Write one line of command output to stdout."""
    print(text)
