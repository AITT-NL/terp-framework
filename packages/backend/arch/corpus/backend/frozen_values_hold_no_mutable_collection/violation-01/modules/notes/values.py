from dataclasses import dataclass


@dataclass(frozen=True)
class ImportPlan:
    """Immutable one level deep, which is the level nobody checks.

    `plan.columns.append("x")` succeeds on a frozen object. Callers share this
    between requests and skip defensive copies because the type says they can,
    so the mutation arrives somewhere else entirely as state that changed with
    no assignment anywhere near it.
    """

    name: str
    columns: list[str]
