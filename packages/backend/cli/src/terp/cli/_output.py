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

import codecs
import sys

__all__ = ["emit", "use_utf8_output"]


def emit(text: object = "") -> None:
    """Write one line of command output to stdout."""
    print(text)


def use_utf8_output() -> None:
    """Write standard output and error as UTF-8 where the stream would not.

    On Windows a pipe or a file takes the ANSI code page -- cp1252 on a Western install --
    and a pipe is exactly how ``terp`` is read by an agent, an editor task or a workbench,
    none of which is a console. cp1252 has no ``→``, so the line ``terp dev`` prints before
    it starts the servers ended the command with ``UnicodeEncodeError`` instead; and text
    this CLI does not author -- a module's label, a finding quoting a source line -- can do
    the same to any command. UTF-8 encodes every string, and it is the default Python itself
    moves to for these streams (PEP 686).

    Changed only where it is not already UTF-8, so a console (which Python already drives
    through the console API as UTF-8) and every Linux or macOS terminal are left exactly as
    they were. A stream that cannot be reconfigured -- none at all, or a replacement such
    as ``io.StringIO`` -- is left alone. ``backslashreplace`` rather than ``strict``, so the
    one thing UTF-8 cannot encode, a lone surrogate from an undecodable file name, prints
    as an escape rather than ending the command.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None or codecs.lookup(stream.encoding).name == "utf-8":
            continue
        reconfigure(encoding="utf-8", errors="backslashreplace")
