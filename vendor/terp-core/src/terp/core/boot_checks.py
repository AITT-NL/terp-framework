"""Checks a capability asks the starting process to run before it serves (ADR 0218).

Some things a capability needs are true or false only in the process that serves: whether
the user the image runs as can write a directory, whether a mount is there. No check before
release sees them, because none runs in the real image, as the real user, with the real
mounts. So a capability registers a check here when it is imported, and ``create_app`` runs
every registered check over the app it just composed, beside the comparison of ADR 0212.

A check returns ``None``, or one sentence that says what is wrong, where, and what to do
about it. Outside ``ENVIRONMENT=local`` a sentence is a refused start (a ``BootError``,
which the uncaught-exception hook logs as ``uncaught BootError: ...``); in local it is a
warning and the app starts, so a developer is told without being stopped.

The registry lives in ``terp.core`` and imports nothing above it: a capability fills it at
import, as the realtime capability fills :func:`~terp.core.register_mandatory_store`. A
check is therefore registered whenever its capability is imported in the process, whether
or not the app mounts a router of it, which is right: a service that stores through a
capability without serving its routes needs the same things from the image.

The public surface offers no way to remove a registered check: there is no unregister, and
:func:`boot_checks` returns a copy. The private ``_checks`` mapping can still be emptied by
code that reaches for it, and no rule refuses that (ADR 0218 says why); a test isolates the
registry by replacing that mapping for the length of the test.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

_logger = logging.getLogger("terp.core")

#: A boot check: ``None`` when this process has what the capability needs, otherwise one
#: sentence that names the problem, where it is, and the remedy.
BootCheck = Callable[[], str | None]

#: The ADR a refusal and a local warning point at.
BOOT_CHECK_ADR = "ADR 0218"

_checks: dict[str, BootCheck] = {}


def register_boot_check(name: str, check: BootCheck) -> None:
    """Register *check* under *name*, run by ``create_app`` before the app serves.

    A capability calls this once, at import. Idempotent per name; a second, different
    registration under one name is refused, so two capabilities cannot silently replace
    each other's check.
    """
    existing = _checks.get(name)
    if existing is not None and existing is not check:
        raise ValueError(f"boot check {name!r} is already registered")
    _checks[name] = check


def boot_checks() -> dict[str, BootCheck]:
    """Every registered check, in name order (a stable order for tests and output).

    A copy: changing it changes nothing the starting process runs.
    """
    return {name: _checks[name] for name in sorted(_checks)}


def _run(name: str, check: BootCheck) -> str | None:
    """One check's sentence; a check that cannot run is a problem too, never a pass."""
    try:
        return check()
    except Exception as exc:  # a check that breaks must not read as passed
        return f"the boot check {name!r} could not run ({type(exc).__name__}: {exc})"


def boot_check_refusal(*, local: bool) -> str | None:
    """Why this process may not start, or ``None``: every registered check passed.

    *local* (``ENVIRONMENT=local``) turns the refusal into a warning. Outside local, a
    process whose checks all passed says which ones ran, so a process that was checked
    reads differently from one where nothing was registered.
    """
    checks = boot_checks()
    problems = [
        problem for name, check in checks.items() if (problem := _run(name, check)) is not None
    ]
    if not problems:
        if not local and checks:
            _logger.info("boot checks passed: %s", ", ".join(checks))
        return None
    refusal = "\n".join(problems)
    if local:
        _logger.warning(
            "%s\nOutside ENVIRONMENT=local this app refuses to start on this (%s).",
            refusal,
            BOOT_CHECK_ADR,
        )
        return None
    return refusal


__all__ = [
    "BOOT_CHECK_ADR",
    "BootCheck",
    "boot_check_refusal",
    "boot_checks",
    "register_boot_check",
]
