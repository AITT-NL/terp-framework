"""The maintenance report as data: what was asked, who answered, and what was found (ADR 0214).

One document, ``terp_maintenance: 1``. Every finding carries every key, so a reader never
has to tell a missing key from an unknown value: unknown is ``null``, and no advisories is
``[]``. A source that could not be asked is recorded twice on purpose, as an unreachable
source and as a ``source-unavailable`` finding, because a report that only listed what it
found would read the same whether a package was clean or the database never answered. A
check that could not be made for any other reason is named in ``not_checked``: a report is
clean only when both lists are empty.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from importlib import metadata

#: The kinds of finding, in the order a report lists them.
KINDS = ("platform-behind", "template-behind", "known-vulnerability", "base-image-behind", "source-unavailable")

#: The sources a report may consult, in the order it lists them.
SOURCES = ("python-index", "npm-registry", "osv", "registry")

#: The report's own schema version: a reader refuses a document it does not know.
VERSION = 1


@dataclass(frozen=True)
class Advisory:
    """One published advisory a package matched, as the database records it."""

    id: str
    aliases: tuple[str, ...] = ()
    summary: str | None = None
    severity: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "aliases": list(self.aliases),
            "summary": self.summary,
            "severity": self.severity,
            "url": f"https://osv.dev/vulnerability/{self.id}",
        }


@dataclass(frozen=True)
class Finding:
    """One thing that wants maintaining, and the sentence that says what to do about it."""

    kind: str
    subject: str
    remedy: str
    ecosystem: str | None = None
    location: str | None = None
    installed: str | None = None
    latest: str | None = None
    fixed_in: str | None = None
    advisories: tuple[Advisory, ...] = ()
    new_since_release: bool | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.kind!r} is not a kind of finding")

    def sort_key(self) -> tuple[int, str, str]:
        return KINDS.index(self.kind), self.subject, self.location or ""

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "ecosystem": self.ecosystem,
            "location": self.location,
            "installed": self.installed,
            "latest": self.latest,
            "fixed_in": self.fixed_in,
            "advisories": [advisory.as_dict() for advisory in self.advisories],
            "new_since_release": self.new_since_release,
            "remedy": self.remedy,
        }


@dataclass(frozen=True)
class Source:
    """One source the report asked, and whether it answered."""

    name: str
    reachable: bool
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.name not in SOURCES:
            raise ValueError(f"{self.name!r} is not a source")

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "reachable": self.reachable, "detail": self.detail}


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _terp_cli() -> str | None:
    try:
        return metadata.version("terp-cli")
    except metadata.PackageNotFoundError:
        return None


@dataclass
class Report:
    """A report on one target: the app, another tree's locks, or a signed release."""

    kind: str
    path: str
    release: str | None = None
    sources: list[Source] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    #: Each check that could not be made for a reason other than an unreachable source, in a
    #: sentence: no lock to read, a scaffolding ref that is not a release, a base with no tag.
    not_checked: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=_now)
    terp_cli: str | None = field(default_factory=_terp_cli)

    def answered(self, name: str) -> None:
        """*name* was asked and answered."""
        self.sources.append(Source(name, True))

    def unreachable(self, name: str, detail: str, remedy: str) -> None:
        """*name* could not be asked: an unreachable source, and a finding that says so."""
        self.sources.append(Source(name, False, detail))
        self.findings.append(Finding("source-unavailable", name, f"{detail.rstrip('.')}. {remedy}"))

    def as_dict(self) -> dict[str, object]:
        return {
            "terp_maintenance": VERSION,
            "checked_at": self.checked_at,
            "terp_cli": self.terp_cli,
            "target": {"kind": self.kind, "path": self.path, "release": self.release},
            "sources": [source.as_dict() for source in sorted(self.sources, key=lambda s: SOURCES.index(s.name))],
            "not_checked": list(self.not_checked),
            "findings": [finding.as_dict() for finding in sorted(self.findings, key=Finding.sort_key)],
        }

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)

    def as_text(self) -> str:
        """The report for a person: one block per finding, the remedy under it."""
        target = f"release {self.release}" if self.release else self.kind
        lines = [f"Maintenance report for {self.path} ({target}), {self.checked_at}"]
        if self.sources:
            asked = sorted(self.sources, key=lambda s: SOURCES.index(s.name))
            lines.append(
                "Asked: " + ", ".join(f"{s.name}{'' if s.reachable else ' (NOT reachable)'}" for s in asked)
            )
        findings = sorted(self.findings, key=Finding.sort_key)
        if findings:
            lines += ["", f"{len(findings)} finding{'s' if len(findings) != 1 else ''}:"]
            for finding in findings:
                lines += ["", f"  {finding.kind}: {_headline(finding)}", f"    {finding.remedy}"]
        elif self.not_checked:
            lines += ["", "Nothing found by the checks that ran. Not every check could run:"]
        else:
            lines += ["", "Nothing to maintain: every check ran and found nothing."]
        if self.not_checked:
            if findings:
                lines += ["", "Not checked:"]
            lines += [f"  - {item}" for item in self.not_checked]
        lines += ["", "A report, not a gate: it changes nothing and exits 0 whatever it finds."]
        return "\n".join(lines)


def _headline(finding: Finding) -> str:
    """One line that names what was found."""
    where = f" in {finding.location}" if finding.location else ""
    if finding.kind == "known-vulnerability":
        ids = ", ".join(
            f"{a.id}{f' ({a.severity})' if a.severity else ''}" for a in finding.advisories
        )
        new = " - new since the release was signed" if finding.new_since_release else ""
        return f"{finding.subject} {finding.installed}{where}: {ids}{new}"
    if finding.kind == "source-unavailable":
        return f"{finding.subject} could not be asked"
    return f"{finding.subject}{where}: {finding.installed} -> {finding.latest}"


__all__ = ["KINDS", "SOURCES", "VERSION", "Advisory", "Finding", "Report", "Source"]
