"""Every refusal a composition finds, in one answer (ADR 0222).

``create_app`` checks what an app declares before it configures anything: that every
public route says so, that every module's routes are guarded, that every operation and
permission is declared, that the stores a deployment requires are the shared kind, the
production-only refusals, and more. Each check raised at its first finding, so an app
behind on several of them learned of one per start: fix it, start again, meet the next.
An app upgraded across many releases met them that way one after another, each visible
only once the one before it was fixed.

They are independent questions about the same declarations, so they are asked together
and answered together: one refusal reads exactly as it always did, and several are one
:class:`~terp.core.app.BootError` that lists each. A check that cannot run because of
what an earlier one found says so, and the answer stops there.
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any


class Refusals:
    """Collects the refusals of a composition's checks, and raises them as one at the end.

    Used as a context manager around the checks. :meth:`check` runs one and keeps its
    refusal; :meth:`add` keeps one a caller found itself. A refusal raised directly inside
    the block is kept too, and ends it. Leaving the block raises what was kept: one refusal
    is re-raised as it was, several as one *error* that lists them, with each on
    ``refusals``. An exception that is no refusal, raised after one was kept, is most likely
    that refusal's consequence: the refusals are raised, chained to it, and say where the
    checks stopped. Raised before any was kept, it propagates untouched.
    """

    def __init__(self, error: type[Exception]) -> None:
        self._error = error
        self._found: list[Exception] = []

    def check(self, step: Callable[..., object], *args: Any) -> None:
        """Run *step* with *args*, keeping its refusal instead of stopping at it."""
        try:
            step(*args)
        except self._error as exc:
            self._found.append(exc)

    def add(self, message: str | None) -> None:
        """Keep *message* as a refusal; ``None`` keeps nothing."""
        if message is not None:
            self._found.append(self._error(message))

    def __enter__(self) -> Refusals:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if isinstance(exc, self._error):
            self._found.append(exc)
        elif exc is not None:
            if not self._found or not isinstance(exc, Exception):
                return  # nothing kept, or not an error at all: it propagates untouched
            raise self._combined(stopped=exc) from exc
        if len(self._found) == 1:
            only = self._found[0]
            only.refusals = (str(only),)  # type: ignore[attr-defined]
            raise only
        if self._found:
            raise self._combined(stopped=None) from self._found[0]

    def _combined(self, *, stopped: BaseException | None) -> Exception:
        messages = tuple(str(found) for found in self._found)
        listed = "\n".join(
            f"{number}. " + message.replace("\n", "\n   ")
            for number, message in enumerate(messages, start=1)
        )
        tail = (
            f"\nThe checks after these stopped at {type(stopped).__name__}: {stopped}, most "
            "likely because of one of them; fix these and start again to see the rest."
            if stopped is not None
            else ""
        )
        count = len(messages)
        head = (
            f"{count} things stop this app from starting, each reported at once rather than "
            "one per start:"
            if count > 1
            else "1 thing stops this app from starting:"
        )
        error = self._error(f"{head}\n{listed}{tail}")
        error.refusals = messages  # type: ignore[attr-defined]
        return error


__all__ = ["Refusals"]
