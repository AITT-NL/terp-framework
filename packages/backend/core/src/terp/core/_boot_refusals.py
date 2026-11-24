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
:class:`BootError` that lists each. A check that cannot run because of
what an earlier one found says so, and the answer stops there.
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any


class BootError(RuntimeError):
    """Raised when a module is misconfigured at composition time (fail closed).

    ``refusals`` is every refusal the composition found, in the order found (ADR 0222): one
    alone is this error's own message, and several are the ones it lists. Defined here, beside
    the collector, and re-exported by :mod:`terp.core.app` and :mod:`terp.core`.
    """

    refusals: tuple[str, ...]

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.refusals = (str(self),)


class Refusals:
    """Collects the refusals of a composition's checks, and raises them as one at the end.

    Used as a context manager around the checks. :meth:`check` runs one and keeps its
    refusal; :meth:`add` keeps one a caller found itself. A refusal raised directly inside
    the block is kept too, and ends it. Leaving the block raises what was kept: one refusal
    is re-raised as it was, several as one :class:`BootError` that lists them, with each on
    ``refusals``. An exception that is no refusal, raised after one was kept, is most likely
    that refusal's consequence: the refusals are raised, chained to it, and say where the
    checks stopped. Raised before any was kept, it propagates untouched.
    """

    def __init__(self) -> None:
        self._found: list[BootError] = []

    def check(self, step: Callable[..., object], *args: Any) -> None:
        """Run *step* with *args*, keeping its refusal instead of stopping at it."""
        try:
            step(*args)
        except BootError as exc:
            self._found.append(exc)

    def add(self, message: str | None) -> None:
        """Keep *message* as a refusal; ``None`` keeps nothing."""
        if message is not None:
            self._found.append(BootError(message))

    def __enter__(self) -> Refusals:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if isinstance(exc, BootError):
            self._found.append(exc)
        elif exc is not None:
            if not self._found or not isinstance(exc, Exception):
                return  # nothing kept, or not an error at all: it propagates untouched
            raise self._combined(stopped=exc) from exc
        if len(self._found) == 1:
            raise self._found[0]
        if self._found:
            raise self._combined(stopped=None) from self._found[0]

    def _combined(self, *, stopped: BaseException | None) -> BootError:
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
        error = BootError(f"{head}\n{listed}{tail}")
        error.refusals = messages
        return error


__all__ = ["BootError", "Refusals"]
