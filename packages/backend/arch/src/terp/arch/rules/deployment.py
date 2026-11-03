"""Deployment-declaration rules: ``deployment.json`` is readable, and tells the truth.

Two rules over the declaration an app checks in at its project root (ADR 0184), both
read from files alone and never by importing the app:

* :func:`check_deployment_declaration_is_readable` — the file is one object the
  Terp Standard's schema admits, in exactly one state, agreeing with itself and with
  the datastore table, and leading a reader only to paths inside the checkout;
* :func:`check_deployment_declaration_tells_the_truth` — what it states, its profile
  does not contradict.

Unlike every other rule in this package they take the **project root**, because that
is where the declaration and the profile live; :func:`terp.arch.check_app` hands them
the parent of the app root it scans. A JSON file cannot carry an ``# arch-allow-*``
marker, so neither has one: the way out is the declaration's own opted-out state,
``{"unmanaged": true, "reason": "..."}``, which turns both off and is reported by any
tool that would have driven the deploy.
"""

from __future__ import annotations

import pathlib

from terp.arch.deployment import (
    DatastoreTable,
    Finding,
    SystemPackageTable,
    generated,
    load_system_packages,
    load_table,
    readable,
    untrue,
)
from terp.arch.rules._support import ArchViolation


def _table(datastore_table: str | pathlib.Path | DatastoreTable | None) -> DatastoreTable:
    if isinstance(datastore_table, DatastoreTable):
        return datastore_table
    return load_table(datastore_table)


def _packages(
    system_package_table: str | pathlib.Path | SystemPackageTable | None,
) -> SystemPackageTable:
    if isinstance(system_package_table, SystemPackageTable):
        return system_package_table
    return load_system_packages(system_package_table)


def _violations(rule: str, findings: list[Finding]) -> list[ArchViolation]:
    return [
        ArchViolation(
            rule=rule,
            path=finding.file,
            line=0,
            message=f"{finding.message}. {finding.remedy}" if finding.remedy else finding.message,
        )
        for finding in findings
    ]


def check_deployment_declaration_is_readable(
    project_root: str | pathlib.Path,
    *,
    package: str = "app",
    datastore_table: str | pathlib.Path | DatastoreTable | None = None,
    system_package_table: str | pathlib.Path | SystemPackageTable | None = None,
) -> list[ArchViolation]:
    """``deployment.json`` must be a declaration every reader reads the same way.

    One JSON object that ``deployment-declaration.schema.json`` admits: no key the
    vocabulary lacks (a ``$`` key is an annotation), no ``image`` key, no deploy-policy
    key, no control character, no string past its cap, a command as an argument list.
    In exactly one state: units with a ``build``, or ``{"unmanaged": true, "reason":
    "..."}`` and nothing beside it. Agreeing with itself and with the datastore table:
    unique ids, a ``size`` that is a key of ``sizes``, a backup only on a unit declared
    stateful, ``client`` only on ``externalDatabase``, a ``kind`` and ``version`` the
    table carries. Leading a reader only inside the checkout, never to the development
    compose file. The generator's words stand only beside ``build: generated``, a
    system package is one the table carries, and a mount names declared units. An
    absent file is undeclared and passes. Fix the field the message names.
    """
    del package  # the declaration is the project's, whatever the package is called
    _declared, findings = readable(
        pathlib.Path(project_root), _table(datastore_table), _packages(system_package_table)
    )
    return _violations("deployment_declaration_is_readable", findings)


def check_deployment_declaration_tells_the_truth(
    project_root: str | pathlib.Path,
    *,
    package: str = "app",
    datastore_table: str | pathlib.Path | DatastoreTable | None = None,
    system_package_table: str | pathlib.Path | SystemPackageTable | None = None,
) -> list[ArchViolation]:
    """What ``deployment.json`` states, its deployment profile must not contradict.

    Partial, never a gate: a service no unit names, no frontend, three APIs, a role
    nobody has heard of, a stateful unit with no backup are all fine. What it does say
    must be true of the resolved profile (the file and its overrides, merged as compose
    merges them): a unit is a service of it; a volume is a named volume some service
    mounts, and not one a stateful unit's policy already covers; an ``env`` name reaches
    the unit's service, directly or through the env file the variable manifest routes
    it to; a restated ``command`` or ``dependsOn`` is the profile's; a ``kind`` unit runs
    exactly the datastore table's image and every other unit an image the checkout
    builds; ``externalDatabase`` never stands beside a profile that still runs a
    database; and a field read by role is never declared under a role nothing reads.
    The two facts only the composed app can settle -- migration labels and served
    health paths -- are ``terp verify --only deployment``'s. Correct the declaration,
    or the profile, until they agree.
    """
    del package
    findings = untrue(
        pathlib.Path(project_root), _table(datastore_table), _packages(system_package_table)
    )
    return _violations("deployment_declaration_tells_the_truth", findings)


def check_deployment_generated_files_match_their_render(
    project_root: str | pathlib.Path,
    *,
    package: str = "app",
    datastore_table: str | pathlib.Path | DatastoreTable | None = None,
    system_package_table: str | pathlib.Path | SystemPackageTable | None = None,
) -> list[ArchViolation]:
    """Where ``deployment.json`` says ``build: generated``, its build files are the render.

    Every generator-owned file (``Dockerfile.prod``, ``frontend/Dockerfile.prod``,
    ``docker-compose.prod.yml``) is byte for byte what ``terp.arch.deployment.generate``
    renders from the declaration, ``[project].name`` and this release's tables, and a
    generator-owned path the render does not produce is absent; a declaration the generator
    cannot render is refused with its own words. The environment files a unit loads are
    ignored by git and left out of the build context, and the template's recorded
    ``deploy_build`` agrees. Silent for an undeclared app, ``own``, ``unmanaged`` and a
    declaration that cannot be read. Fix it with ``terp deployment render``, never by
    editing the files; the only escape is the whole app, ``build: own``.
    """
    del package
    result = generated(
        pathlib.Path(project_root), _table(datastore_table), _packages(system_package_table)
    )
    return _violations("deployment_generated_files_match_their_render", result.drift.findings)


__all__ = [
    "check_deployment_declaration_is_readable",
    "check_deployment_declaration_tells_the_truth",
    "check_deployment_generated_files_match_their_render",
]
