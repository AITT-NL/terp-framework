"""What a scanned root is: an app ``create_app`` mounts, or a companion beside it.

The kinds, and the :class:`ScanRoot` that names a directory with one. Which kinds each rule
is evaluated over stays in the registry (:data:`terp.arch.rules.RULE_ROOT_KINDS`), one row
per rule beside its import.
"""

from __future__ import annotations

import enum
import pathlib
from dataclasses import dataclass


class RootKind(enum.Enum):
    """What a scanned root *is*, which is what decides the rules it is held to.

    ``APP`` is a Terp application package — the thing ``create_app`` mounts, with
    modules, routers, a policy, tables and migrations. Every rule applies to it.

    ``COMPANION`` is a second deployable that ships from the same repository and is
    **not** mounted by ``create_app``: a worker, a publisher, a CLI, a sidecar. It is
    ordinary Python that reaches real credentials, real databases and the real
    network, so the rules about the *code* apply to it in full — and the rules that
    are properties of being a mounted application (a route's response model, a
    module's policy, a table's migration) do not, because there is nothing for them
    to be a property of.

    A root that serves the platform's own HTTP surface is an ``APP``, however it is
    deployed. The kind describes what the code is, not how many processes run it.
    """

    APP = "app"
    COMPANION = "companion"


#: Every root kind — the applicability of a rule whose invariant holds for any
#: Python that ships.
EVERY_ROOT: frozenset[RootKind] = frozenset(RootKind)

#: Application roots only — the applicability of a rule whose invariant is a
#: property of being a mounted Terp application.
APP_ROOT_ONLY: frozenset[RootKind] = frozenset({RootKind.APP})


@dataclass(frozen=True)
class ScanRoot:
    """One directory the harness walks, with the package name and kind it is walked as.

    ``ScanRoot("engine", package="engine", kind=RootKind.COMPANION)`` is the whole
    configuration a second deployable needs; :func:`check_app` and
    :func:`assert_app_clean` take any number of these beside the app root and share
    one escape-hatch budget across them, so a sibling package is a line rather than a
    bespoke test module.

    A bare path passed to those functions is an ``APP`` root taking the call's
    ``package=``, which is what every existing call site means and why it keeps
    meaning it.
    """

    path: pathlib.Path
    package: str = "app"
    kind: RootKind = RootKind.APP

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", pathlib.Path(self.path))


__all__ = ["APP_ROOT_ONLY", "EVERY_ROOT", "RootKind", "ScanRoot"]
