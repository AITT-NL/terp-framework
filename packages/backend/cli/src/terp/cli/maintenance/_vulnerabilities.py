"""Known vulnerabilities: each package asked of OSV, each match read whole (ADR 0214).

The batch answer says only which advisories a package version matches. Each advisory is
then read once, for the three things a person acting on it needs: what it is (summary and
aliases), how bad its source says it is (``database_specific.severity``, relayed as data and
never branched on), and which version fixes it.

The version that fixes a package is read from the advisories' own ranges for it: of every
``fixed`` event above the installed version, the lowest one that no matched advisory still
covers, so a fix on one release line is never offered while another advisory still holds
there. The ranges are compared over release numbers, the order both PyPI and npm number
their releases in. An advisory with no fixed release is named in the remedy rather than
given an invented one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from terp.cli.maintenance._packages import Package
from terp.cli.maintenance._report import Advisory, Finding, Report
from terp.cli.release import _osv
from terp.cli.release._common import ReleaseError
from terp.cli.release._locks import normalise

#: Where a suffix puts a version: a development release below every pre-release, a
#: pre-release below the release, a post-release above it (PEP 440; semver has no dev or post).
_DEV, _PRE, _FINAL, _POST = range(4)
_PRE_NAMES = {"alpha": "a", "beta": "b", "c": "rc", "pre": "rc", "preview": "rc"}

Key = tuple[tuple[int, ...], int, tuple[tuple[int, int | str], ...]]


def version_key(version: str) -> Key:
    """A sort key for a PyPI or npm release number.

    ``1.0.dev1`` < ``1.0a1`` < ``1.0b2`` < ``1.0rc1`` < ``1.0`` < ``1.0.post1``; ``1.0.0-beta.1``
    < ``1.0.0-rc.1`` < ``1.0.0``; ``1.10`` > ``1.9``; ``1.2`` == ``1.2.0``. Epochs, local versions
    and build metadata are not compared: an advisory's ranges do not use them. A suffix of
    numbers alone (``1.0.0-1``) is a pre-release, as semver reads it.
    """
    text = version.strip().lower().lstrip("v").split("+", 1)[0]
    match = re.match(r"(\d+(?:\.\d+)*)(.*)", text)
    if match is None:
        return (), _PRE, ((1, text),)
    release = tuple(int(part) for part in match.group(1).split("."))
    while len(release) > 1 and release[-1] == 0:
        release = release[:-1]
    tokens = re.findall(r"[a-z]+|\d+", match.group(2))
    if not tokens:
        return release, _FINAL, ()
    phase = {"dev": _DEV, "post": _POST, "rev": _POST, "r": _POST}.get(tokens[0], _PRE)
    # A number and a word never meet in one comparison: each part says which it is first, and
    # a number sorts below a word, as semver orders pre-release identifiers.
    parts = tuple(
        (0, int(token)) if token.isdigit() else (1, _PRE_NAMES.get(token, token))
        for token in (tokens[1:] if phase != _PRE else tokens)
    )
    return release, phase, parts


def _same_package(entry: Mapping[str, Any], package: Package) -> bool:
    found = entry.get("package") or {}
    if str(found.get("ecosystem", "")).lower() != package.ecosystem.lower():
        return False
    name = str(found.get("name", ""))
    return normalise(name) == normalise(package.name) if package.ecosystem == "PyPI" else name == package.name


def _ranges(advisory: Mapping[str, Any], package: Package) -> Iterator[tuple[list[str], list[dict[str, Any]]]]:
    """``(versions listed, events of one range)`` for each range the advisory gives *package*."""
    for entry in advisory.get("affected") or []:
        if not isinstance(entry, dict) or not _same_package(entry, package):
            continue
        listed = [str(version) for version in entry.get("versions") or []]
        ranges = [r for r in entry.get("ranges") or [] if isinstance(r, dict) and r.get("type") in ("ECOSYSTEM", "SEMVER")]
        if not ranges:
            yield listed, []
        for found in ranges:
            yield listed, [event for event in found.get("events") or [] if isinstance(event, dict)]


def _covers(events: list[dict[str, Any]], version: str) -> bool:
    """Whether one range's events cover *version*: OSV's own reading, in version order."""
    key = version_key(version)

    def at(event: dict[str, Any]) -> Key:
        value = str(next(iter(event.values())))
        return ((-1,), _DEV, ()) if value == "0" else version_key(value)

    covered = False
    for event in sorted(events, key=at):
        if "introduced" in event and at(event) <= key:
            covered = True
        elif "fixed" in event and at(event) <= key:
            covered = False
        elif "last_affected" in event and at(event) < key:
            covered = False
    return covered


def affects(advisory: Mapping[str, Any], package: Package, version: str) -> bool:
    """Whether *advisory* says *package* at *version* is affected."""
    return any(
        version in listed or _covers(events, version) for listed, events in _ranges(advisory, package)
    )


def fixes(advisory: Mapping[str, Any], package: Package) -> list[str]:
    """Every ``fixed`` event the advisory gives *package* above its installed version."""
    installed = version_key(package.version)
    return [
        str(event["fixed"])
        for _listed, events in _ranges(advisory, package)
        for event in events
        if "fixed" in event and version_key(str(event["fixed"])) > installed
    ]


def _severity(advisory: Mapping[str, Any]) -> str | None:
    found = (advisory.get("database_specific") or {}).get("severity")
    return str(found) if isinstance(found, str) and found else None


def _command(package: Package, fixed_in: str) -> str:
    if package.ecosystem == "PyPI":
        command = f"uv lock --upgrade-package {package.name}"
    elif package.location.startswith("image "):
        # A bundle records the image, not the workspace it was built from.
        command = f"in the npm workspace {package.location} is built from, npm install {package.name}@{fixed_in}"
    else:
        workspace = package.location.rsplit("/", 1)[0] if "/" in package.location else "."
        command = f"npm --prefix {workspace} install {package.name}@{fixed_in}"
        if package.direct is False:
            # Installing it by name would make a package the app never chose one of its own
            # dependencies; updating it keeps it where it is, within its dependents' ranges.
            command = (
                f"npm --prefix {workspace} update {package.name} (it comes in through another package: "
                f"if that one's range keeps it below {fixed_in}, update that package, or add an "
                f"`overrides` entry for {package.name})"
            )
    if package.location.startswith("image "):
        command += ", then cut a new release"
    return command


def _remedy(package: Package, fixed_in: str | None, fixable: list[str], unfixed: list[str]) -> str:
    sentences = []
    if fixed_in is not None:
        sentences.append(f"Move {package.name} to {fixed_in} or later: {_command(package, fixed_in)}.")
    elif fixable:
        sentences.append(
            f"No one release of {package.name} clears {', '.join(fixable)}: each is fixed on another "
            "release line. Read the advisories' fixed versions and choose the line to move to."
        )
    if unfixed:
        sentences.append(
            f"No release of {package.name} fixes {', '.join(unfixed)} yet. Read the advisory for a "
            "workaround, or replace the package; check again when a fix is published."
        )
    return " ".join(sentences)


def _finding(
    package: Package, groups: list[list[str]], records: Mapping[str, Mapping[str, Any]], known: frozenset[str] | None
) -> Finding:
    """One package's finding: its flaws, and the lowest version that clears every fixable one."""
    fixable = [group for group in groups if any(fixes(records[member], package) for member in group)]
    unfixed = [group[0] for group in groups if group not in fixable]
    candidates = sorted(
        {fix for group in fixable for member in group for fix in fixes(records[member], package)}, key=version_key
    )
    fixed_in = next(
        (
            candidate
            for candidate in candidates
            if not any(affects(records[member], package, candidate) for group in fixable for member in group)
        ),
        None,
    )
    return Finding(
        "known-vulnerability",
        package.name,
        _remedy(package, fixed_in, [group[0] for group in fixable], unfixed),
        ecosystem=package.ecosystem,
        location=package.location,
        installed=package.version,
        fixed_in=fixed_in,
        advisories=tuple(_advisory(group, records) for group in groups),
        new_since_release=None if known is None else any(not set(group) & known for group in groups),
    )


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
        if groups:
            known = recorded.get(package.purl, frozenset()) if recorded is not None else None
            report.findings.append(_finding(package, groups, records, known))


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


def _advisory(group: list[str], records: Mapping[str, Mapping[str, Any]]) -> Advisory:
    lead = records[group[0]]
    aliases = {str(alias) for member in group for alias in records[member].get("aliases") or []} | set(group)
    summary = next((str(records[m]["summary"]) for m in group if records[m].get("summary")), None)
    return Advisory(group[0], tuple(sorted(aliases - {group[0]})), summary, _severity(lead))


__all__ = ["affects", "fixes", "version_key", "vulnerability_findings"]
