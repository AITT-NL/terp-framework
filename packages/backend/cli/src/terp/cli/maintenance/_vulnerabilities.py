"""Known vulnerabilities: each package asked of OSV, each match read whole (ADR 0214).

The batch answer says only which advisories a package version matches. Each advisory is
then read once, for the three things a person acting on it needs: what it is (summary and
aliases), how bad its source says it is (``database_specific.severity``, relayed as data and
never branched on), and which version fixes it.

The fixed version is read from the advisory's own ranges for the package: the first
``fixed`` event above the installed version. It is a best effort over release numbers, the
order both PyPI and npm number their releases in; an advisory with no fixed release says so
in the remedy rather than inventing one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from terp.cli.maintenance._packages import Package
from terp.cli.maintenance._report import Advisory, Finding, Report
from terp.cli.release import _osv
from terp.cli.release._common import ReleaseError
from terp.cli.release._locks import normalise


def version_key(version: str) -> tuple[tuple[int, ...], int, tuple[tuple[int, int | str], ...]]:
    """A sort key for a PyPI or npm release number: the release, then any pre-release below it.

    ``1.2.0`` > ``1.2.0rc1`` > ``1.2.0-beta.1`` > ``1.1.9``; ``1.10`` > ``1.9``. Epochs, local
    versions and build metadata are not compared: an advisory's ranges do not use them.
    """
    text = version.strip().lower().lstrip("v").split("+", 1)[0]
    match = re.match(r"(\d+(?:\.\d+)*)(.*)", text)
    if match is None:
        return (), 0, ((1, text),)
    release = tuple(int(part) for part in match.group(1).split("."))
    while len(release) > 1 and release[-1] == 0:
        release = release[:-1]
    rest = match.group(2).lstrip(".-_")
    if not rest or rest.startswith("post"):
        return release, 1, ()
    # A number and a word never meet in one comparison: each part says which it is first, and
    # a number sorts below a word, as semver orders pre-release identifiers.
    parts = tuple((0, int(part)) if part.isdigit() else (1, part) for part in re.findall(r"[a-z]+|\d+", rest))
    return release, 0, parts


def _same_package(entry: Mapping[str, Any], package: Package) -> bool:
    found = entry.get("package") or {}
    if str(found.get("ecosystem", "")).lower() != package.ecosystem.lower():
        return False
    name = str(found.get("name", ""))
    return normalise(name) == normalise(package.name) if package.ecosystem == "PyPI" else name == package.name


def fixed_version(advisory: Mapping[str, Any], package: Package) -> str | None:
    """The lowest version above *package*'s that the advisory says fixes it, or ``None``."""
    installed = version_key(package.version)
    fixes = [
        str(event["fixed"])
        for entry in advisory.get("affected") or []
        if isinstance(entry, dict) and _same_package(entry, package)
        for found in entry.get("ranges") or []
        if isinstance(found, dict) and found.get("type") in ("ECOSYSTEM", "SEMVER")
        for event in found.get("events") or []
        if isinstance(event, dict) and "fixed" in event and version_key(str(event["fixed"])) > installed
    ]
    return min(fixes, key=version_key) if fixes else None


def _severity(advisory: Mapping[str, Any]) -> str | None:
    found = (advisory.get("database_specific") or {}).get("severity")
    return str(found) if isinstance(found, str) and found else None


def _remedy(package: Package, fixed_in: str | None, unfixed: list[str]) -> str:
    workspace = package.location.rsplit("/", 1)[0] if "/" in package.location else "."
    if package.ecosystem == "PyPI":
        command = f"uv lock --upgrade-package {package.name}"
    elif package.direct is False:
        # Installing it by name would make a package the app never chose one of its own
        # dependencies; updating it keeps it where it is, within its dependents' ranges.
        command = (
            f"npm --prefix {workspace} update {package.name} (it comes in through another package: "
            f"if that one's range keeps it below {fixed_in or 'a fix'}, update that package, or add "
            f"an `overrides` entry for {package.name})"
        )
    else:
        command = f"npm --prefix {workspace} install {package.name}@{fixed_in or 'latest'}"
    if package.location.startswith("image "):
        command += ", then cut a new release"
    if fixed_in is None:
        return (
            f"No release of {package.name} fixes {', '.join(unfixed)} yet. Read the advisory for a "
            "workaround, or replace the package; check again when a fix is published."
        )
    sentence = f"Move {package.name} to {fixed_in} or later: {command}."
    if unfixed:
        sentence += f" {', '.join(unfixed)} {'has' if len(unfixed) == 1 else 'have'} no fixed release yet."
    return sentence


def vulnerability_findings(
    report: Report,
    packages: Iterable[Package],
    osv: str,
    *,
    recorded: Mapping[str, frozenset[str]] | None = None,
    client_for: _osv.ClientFor | None = None,
) -> None:
    """Ask the database about *packages* and add a finding per vulnerable one to *report*.

    *recorded* is a signed release's own list (purl -> advisory ids): a finding then says
    whether any of its advisories is new since the release was signed. A database that
    cannot be asked leaves an unreachable source and a ``source-unavailable`` finding, and no
    finding about any package: a partial answer is not offered as a whole one.
    """
    wanted = sorted(set(packages), key=lambda p: (p.ecosystem, p.name, p.version, p.location))
    if not wanted:
        return
    try:
        matched = _osv.query_batch(osv, sorted({package.purl for package in wanted}), client_for=client_for)
        records: dict[str, dict[str, Any]] = {}
        for advisory_id in sorted({found for ids in matched.values() for found in ids}):
            records[advisory_id] = _osv.advisory(osv, advisory_id, client_for=client_for)
    except ReleaseError as exc:
        detail = f"{exc.message}: {exc.cause}" if exc.cause else exc.message
        report.unreachable(
            "osv",
            detail,
            f"Nothing was learned about any package. Check that {osv} is reachable from here "
            "(or pass --osv with a mirror), and that terp-cap-egress is installed, then run it again.",
        )
        return
    report.answered("osv")
    for package in wanted:
        ids = [found for found in matched.get(package.purl, []) if not records[found].get("withdrawn")]
        groups = _grouped(ids, records)
        if not groups:
            continue
        fixes = {group[0]: _group_fix(group, records, package) for group in groups}
        fixed = [version for version in fixes.values() if version is not None]
        newest_fix = max(fixed, key=version_key) if fixed else None
        known = recorded.get(package.purl, frozenset()) if recorded is not None else frozenset()
        report.findings.append(
            Finding(
                "known-vulnerability",
                package.name,
                _remedy(package, newest_fix, [found for found, version in fixes.items() if version is None]),
                ecosystem=package.ecosystem,
                location=package.location,
                installed=package.version,
                fixed_in=newest_fix,
                advisories=tuple(_advisory(group, records) for group in groups),
                new_since_release=None if recorded is None else any(not set(group) & known for group in groups),
            )
        )


def _grouped(ids: list[str], records: Mapping[str, Mapping[str, Any]]) -> list[list[str]]:
    """*ids* gathered into one group per vulnerability: ids that alias each other or share an alias.

    OSV answers one vulnerability under every database's id for it (a GHSA and a PYSEC, say),
    each listing the others or the same CVE as aliases; a report that listed them all would
    count one flaw several times. Each group leads with the id a reader acts on: one that
    carries a severity, then the first by name.
    """
    parent = {found: found for found in ids}

    def root(found: str) -> str:
        while parent[found] != found:
            found = parent[found]
        return found

    owner: dict[str, str] = {}
    for found in ids:
        for name in [found, *(str(alias) for alias in records[found].get("aliases") or [])]:
            if name in owner:
                parent[root(owner[name])] = root(found)
            else:
                owner[name] = found
    groups: dict[str, list[str]] = {}
    for found in sorted(ids):
        groups.setdefault(root(found), []).append(found)
    return sorted(
        (sorted(group, key=lambda found: (_severity(records[found]) is None, found)) for group in groups.values()),
        key=lambda group: group[0],
    )


def _group_fix(group: list[str], records: Mapping[str, Mapping[str, Any]], package: Package) -> str | None:
    found = [version for member in group if (version := fixed_version(records[member], package)) is not None]
    return max(found, key=version_key) if found else None


def _advisory(group: list[str], records: Mapping[str, Mapping[str, Any]]) -> Advisory:
    lead = records[group[0]]
    aliases = {str(alias) for member in group for alias in records[member].get("aliases") or []} | set(group)
    summary = next((str(records[m]["summary"]) for m in group if records[m].get("summary")), None)
    return Advisory(group[0], tuple(sorted(aliases - {group[0]})), summary, _severity(lead))


__all__ = ["fixed_version", "version_key", "vulnerability_findings"]
