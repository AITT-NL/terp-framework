"""The near-misses for a rule whose subject is one specific builtin.

A checker matching the bare token `print` flags every one of these and still passes
the minimal pair, which is the false-positive class this case contracts: `print` as
a method on an object, as an attribute, as a keyword argument, as a local name and
as text.
"""

import logging

log = logging.getLogger(__name__)


class Printer:
    def print(self, message: str) -> None:
        log.info(message)


def run(printer: Printer, report) -> None:
    # A member call, not the builtin: the receiver is an object the app owns.
    printer.print("rendered")
    report.print(copies=1)
    # An attribute holding a callable is still not a call to the builtin.
    emit = log.info
    emit("print() is refused; this line only names it")
