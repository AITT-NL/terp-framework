"""What one ``terp secrets reseal`` run found, and the report an operator reads (ADR 0189).

:mod:`terp.cli.reseal` walks the database and counts each sealed value here, by the key it
opens under and by what the run did with it; :func:`render` turns the counts into the
operator's report and its verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["ColumnTally", "ResealReport", "render"]

#: What a run counts, in the order the report shows it, each with its column heading.
_COUNTS = {
    "current": "current",
    "resealed": "re-sealed",
    "fallback": "fallback",
    "unreadable": "unreadable",
    "changed": "changed",
    "held": "held",
}


@dataclass
class ColumnTally:
    """One column's sealed values, by the key each opens under."""

    table: str
    column: str
    current: int = 0  # opens under SECRET_KEY
    resealed: int = 0  # rewritten under SECRET_KEY by this run
    fallback: int = 0  # still opens only under a SECRET_KEY_DECRYPT_FALLBACKS entry
    unreadable: int = 0  # opens under no configured key, in no registered domain
    changed: int = 0  # rewritten by someone else between this run's read and its write
    held: int = 0  # under a fallback, in a row another transaction held locked

    @property
    def found(self) -> int:
        return sum(getattr(self, name) for name in _COUNTS)

    def add(self, other: ColumnTally) -> None:
        """Count *other*'s values here too: a batch's counts, once its transaction committed."""
        for name in _COUNTS:
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass
class ResealReport:
    """What one run found, wrote and could not reach."""

    wrote: bool
    columns: list[ColumnTally]
    failed: dict[str, str]  # table -> why it stopped there
    skipped: dict[str, str] = field(default_factory=dict)  # table -> why nothing was re-sealed

    def total(self, name: str) -> int:
        return sum(getattr(tally, name) for tally in self.columns)

    @property
    def clean(self) -> bool:
        """Every sealed value found opens under ``SECRET_KEY``, and every table was read.

        A skipped table was read, so its values are in the totals: one that still needs a
        fallback keeps the report from being clean, and one that opens under ``SECRET_KEY``
        needs nothing.
        """
        return not self.failed and not any(
            self.total(name) for name in ("fallback", "unreadable", "changed", "held")
        )


def render(report: ResealReport) -> str:
    """The operator's report: one line per column that holds sealed values, then a verdict."""
    headings = ("column", *_COUNTS.values())
    lines = [(f"{tally.table}.{tally.column}", *(getattr(tally, name) for name in _COUNTS))
             for tally in report.columns]
    lines.append(("total", *(report.total(name) for name in _COUNTS)))
    width = max(len(str(line[0])) for line in [headings, *lines])
    out = ["Re-sealed under SECRET_KEY:" if report.wrote else "Checked; nothing was written:", ""]
    for line in [headings, *lines]:
        out.append(f"  {line[0]:<{width}}" + "".join(f"  {cell:>10}" for cell in line[1:]))
    out.append("")
    for table, reason in report.failed.items():
        out.append(
            f"Could not re-seal {table} ({reason}); the transaction that failed was rolled "
            "back, and nothing after it was read."
        )
    for table, reason in report.skipped.items():
        out.append(
            f"Read {table} but re-sealed nothing in it: {reason}. Its values are counted "
            "above; re-seal any that need a fallback through the code that owns it."
        )
    if report.total("fallback"):
        out.append(
            f"{report.total('fallback')} value(s) still open only under "
            "SECRET_KEY_DECRYPT_FALLBACKS. Run `terp secrets reseal` without --check, and "
            "keep the fallbacks until it reports none."
        )
    if report.total("unreadable"):
        out.append(
            f"{report.total('unreadable')} value(s) open under no configured key: sealed "
            "under a key no longer listed, or damaged. Add the key they were sealed under "
            "to SECRET_KEY_DECRYPT_FALLBACKS and run again, or enter them anew."
        )
    if report.total("changed"):
        out.append(
            f"{report.total('changed')} value(s) changed while being re-sealed; run again "
            "to judge them."
        )
    if report.total("held"):
        out.append(
            f"{report.total('held')} value(s) under a fallback were in rows another "
            "transaction held, a worker's or the running app's, and were not waited for; "
            "run again to re-seal them."
        )
    if report.clean:
        out.append(
            "Every sealed value opens under SECRET_KEY: SECRET_KEY_DECRYPT_FALLBACKS can "
            "come out of the environment. Keep each key it held for as long as a backup "
            "sealed under it may still be restored."
        )
    out.append(
        "SECRET_KEY_FALLBACKS only verifies signatures and is not judged here; drop it once "
        "the longest signature lifetime has passed (`terp guide secrets`)."
    )
    return "\n".join(out)
