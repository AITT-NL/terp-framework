"""Where a declared variable must have a value — ``"requiredIn"`` (ADR 0180).

``required`` at the top of ``environment.schema.json`` means every environment. A
declaration's ``"requiredIn"`` names only the environments it is needed in, in the words
the platform already uses for where an app runs: the ``ENVIRONMENT`` setting
(``terp.core.config.Settings``). The framework itself draws this line — a production boot
is refused over what the development loop only warns about (``JOB_SYSTEM_ACTOR_ID``,
ADR 0129) — and the manifest had no way to say it, so a value only a deployment needs was
demanded in the development loop from whoever could not produce it.

A module of its own because :mod:`terp.cli.envschema` is the dialect's checker and was at
the package's size limit; the checker calls :func:`required_in_problem` and
:func:`required_twice`, and the inner loop's ``terp env`` asks :func:`required_in`.
Terp Studio's reader mirrors every rule here, in the same words.
"""

from __future__ import annotations

#: The values ``Settings.ENVIRONMENT`` can take, held equal to it by
#: ``tests/architecture/test_cli_env_seams.py``.
REQUIRED_IN_VALUES = ("local", "staging", "production")


def required_in_problem(value: object) -> str | None:
    """Why a declaration's ``requiredIn`` is unusable, or ``None`` when it is fine.

    A near miss (``"prod"``) would make the value required nowhere, and a deployment
    would go out without it — so it is refused, as ``resolvedBy`` and ``format`` are.
    """
    if value is None:
        return None
    if (
        isinstance(value, list)
        and value
        and all(entry in REQUIRED_IN_VALUES for entry in value)
        and len(set(value)) == len(value)
    ):
        return None
    return (
        "must be a non-empty list of distinct values from "
        f"{', '.join(REQUIRED_IN_VALUES)} (the ENVIRONMENT a stack runs with: the "
        "development loop is local, a deployment production)"
    )


def required_twice(required: list[str], properties: dict) -> list[str]:
    """The names in ``required`` whose declaration also carries ``requiredIn``.

    ``required`` already means every environment, so the two answers to "where" cannot
    both be meant.
    """
    return [
        name
        for name in required
        if isinstance(properties.get(name), dict) and "requiredIn" in properties[name]
    ]


def required_in(document: object, environment: str) -> list[str]:
    """The names a manifest needs a value for where a stack runs as *environment*.

    Everything in ``required``, which is every environment, and every declaration whose
    ``requiredIn`` names *environment* — in the manifest's own order. Tolerant like
    :func:`terp.cli.envschema.declared_variables`: the verdict on a malformed manifest
    belongs to the checker, so an unusable entry here reads as requiring nothing.
    """
    if not isinstance(document, dict):
        return []
    raw_required = document.get("required")
    always = (
        [name for name in raw_required if isinstance(name, str)]
        if isinstance(raw_required, list)
        else []
    )
    properties = document.get("properties")
    if not isinstance(properties, dict):
        return always
    scoped = [
        name
        for name, prop in properties.items()
        if isinstance(prop, dict)
        and name not in always
        and isinstance(prop.get("requiredIn"), list)
        and environment in prop["requiredIn"]
    ]
    return always + scoped
