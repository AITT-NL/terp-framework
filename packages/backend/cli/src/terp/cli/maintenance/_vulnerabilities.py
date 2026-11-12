"""Known vulnerabilities: each package asked of OSV, each match read whole (ADR 0214).

The batch answer says only which advisories a package version matches. Each advisory is
then read once, for the three things a person acting on it needs: what it is (summary and
aliases), how bad its source says it is (``database_specific.severity``, relayed as data and
never branched on), and which version fixes it.

The version that fixes a package is read from the advisories' own ranges for it: of every
``fixed`` event above the installed version, the lowest one that no matched advisory still
covers, so a fix on one release line is never offered while another advisory still holds
there. Versions compare in their ecosystem's own order: PEP 440's for PyPI (as ``packaging``
keys it), semver's for npm. An advisory with no fixed release is named in the remedy rather
than given an invented one.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from terp.cli.maintenance._packages import Package
from terp.cli.maintenance._report import Advisory, Finding, Report
from terp.cli.release import _osv
from terp.cli.release._common import ReleaseError
from terp.cli.release._locks import normalise

#: An infinity of each sign for the comparison keys below, as tuples that compare with values.
_HIGH, _LOW = (1,), (-1,)

#: PEP 440's version pattern (the one ``packaging`` compiles), with the local part ignored.
_PEP440 = re.compile(
    r"v?(?:(?P<epoch>[0-9]+)!)?(?P<release>[0-9]+(?:\.[0-9]+)*)"
    r"(?:[-_.]?(?P<pre_l>alpha|a|beta|b|preview|pre|c|rc)[-_.]?(?P<pre_n>[0-9]+)?)?"
    r"(?:-(?P<post_n1>[0-9]+)|[-_.]?(?P<post_l>post|rev|r)[-_.]?(?P<post_n2>[0-9]+)?)?"
    r"(?:[-_.]?(?P<dev_l>dev)[-_.]?(?P<dev_n>[0-9]+)?)?"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?"
)
_PRE = {"a": "a", "alpha": "a", "b": "b", "beta": "b", "c": "rc", "rc": "rc", "pre": "rc", "preview": "rc"}
_SEMVER = re.compile(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?")

Key = tuple[Any, ...]


def _pep440(version: str) -> Key | None:
    """PEP 440's order, as ``packaging`` keys it: epoch, release (trailing zeros dropped), then a
    development release of a final below its pre-releases, pre < final < post, and a development
    release below the release it leads to (``1.0a1.dev1`` < ``1.0a1``)."""
    found = _PEP440.fullmatch(version.strip().lower())
    if found is None:
        return None
    release = tuple(int(part) for part in found["release"].split("."))
    while len(release) > 1 and release[-1] == 0:
        release = release[:-1]
    pre = (_PRE[found["pre_l"]], int(found["pre_n"] or 0)) if found["pre_l"] else None
    post = int(found["post_n1"] or found["post_n2"] or 0) if (found["post_n1"] or found["post_l"]) else None
    dev = int(found["dev_n"] or 0) if found["dev_l"] else None
    if pre is None and post is None and dev is not None:
        pre_key: tuple[Any, ...] = _LOW
    else:
        pre_key = _HIGH if pre is None else (0, *pre)
    return (
        int(found["epoch"] or 0),
        release,
        pre_key,
        _LOW if post is None else (0, post),
        _HIGH if dev is None else (0, dev),
    )


def _semver(version: str) -> Key | None:
    """Semver's order: the core, then a release above its pre-releases, whose identifiers
    compare one by one (numbers below words, numbers by value), the shorter list first."""
    found = _SEMVER.fullmatch(version.strip())
    if found is None:
        return None
    core = tuple(int(part or 0) for part in found.groups()[:3])
    pre = found.group(4)
    if pre is None:
        return (core, _HIGH, ())
    identifiers = tuple((0, int(part)) if part.isdigit() else (1, part) for part in pre.split("."))
    return (core, _LOW, identifiers)


def version_key(version: str, ecosystem: str = "PyPI") -> Key:
    """A sort key for a release of *ecosystem*: PEP 440's order for PyPI, semver's for npm.

    A version neither reads sorts below every one that does, by its text, so a malformed
    version in an advisory can never be offered as the one that fixes a package.
    """
    key = _semver(version) if ecosystem == "npm" else _pep440(version)
    return (1, key) if key is not None else (0, version)


def _same_package(entry: Mapping[str, Any], package: Package) -> bool:
    found = entry.get("package")
    found = found if isinstance(found, dict) else {}
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


def _covers(events: list[dict[str, Any]], version: str, ecosystem: str) -> bool:
    """Whether one range's events cover *version*, as OSV's schema evaluates them.

    The events are read in version order, whatever order the advisory lists them in (the
    schema recommends sorting and does not require it): ``introduced`` opens, ``fixed`` closes
    at its version, ``last_affected`` closes after its version. A ``limit`` caps the whole range:
    a version at or above every limit is not covered.
    """
    key = version_key(version, ecosystem)

    def at(event: dict[str, Any]) -> Key:
        value = str(next(iter(event.values())))
        return (-1, value) if value == "0" else version_key(value, ecosystem)

    limits = [at(event) for event in events if "limit" in event]
    if limits and not any(key < limit for limit in limits):
        return False
    covered = False
    for event in sorted((event for event in events if "limit" not in event and event), key=at):
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
        version in listed or _covers(events, version, package.ecosystem) for listed, events in _ranges(advisory, package)
    )


def fixes(advisory: Mapping[str, Any], package: Package) -> list[str]:
    """Every ``fixed`` event the advisory gives *package* above its installed version."""
    installed = version_key(package.version, package.ecosystem)
    return [
        str(event["fixed"])
        for _listed, events in _ranges(advisory, package)
        for event in events
        if "fixed" in event and version_key(str(event["fixed"]), package.ecosystem) > installed
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
        {fix for group in fixable for member in group for fix in fixes(records[member], package)},
        key=lambda version: version_key(version, package.ecosystem),
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


def _egress_missing() -> bool:
    """Whether this environment lacks the one client the database is asked through."""
    try:
        return importlib.util.find_spec("terp.capabilities.egress") is None
    except ModuleNotFoundError:
        return True


def _held_back(packages: list[Package]) -> str:
    hosts = sorted({package.registry for package in packages if package.registry})
    named = ", ".join(hosts) if hosts else "an index the lock does not name"
    count = f"{len(packages)} package{'s' if len(packages) != 1 else ''}"
    return (
        f"known-vulnerability: {count} from an index that is not public ({named}) "
        f"{'were' if len(packages) != 1 else 'was'} not sent to the vulnerability database, so "
        "their names stay on this machine: point --osv at a mirror inside your network, or pass "
        "--send-private-names if those names may leave it"
    )


def vulnerability_findings(
    report: Report,
    packages: Iterable[Package],
    osv: str,
    *,
    recorded: Mapping[str, frozenset[str]] | None = None,
    only_public: bool = True,
    client_for: _osv.ClientFor | None = None,
) -> None:
    """Ask the database about *packages* and add a finding per vulnerable one to *report*.

    With *only_public*, a package a public registry does not serve is not sent: its name may be
    the app's own, and it is named in ``not_checked`` instead. *recorded* is a signed release's
    own list (purl -> advisory ids): a finding then says whether any of its advisories is new
    since the release was signed. A database that cannot be asked leaves an unreachable source
    and a ``source-unavailable`` finding, and no finding about any package: a partial answer is
    not offered as a whole one. An environment without the egress client says so as a check
    it could not make, because nothing was asked, not because nothing answered.
    """
    wanted = sorted(set(packages), key=lambda p: (p.ecosystem, p.name, p.version, p.location))
    if only_public:
        private = [package for package in wanted if not package.public]
        if private:
            report.not_made(_held_back(private))
        wanted = [package for package in wanted if package.public]
    if not wanted:
        return
    if client_for is None and _egress_missing():
        from terp.cli.version import installed_terp_versions

        pin = installed_terp_versions().get("terp-cli")
        spec = f"terp-cap-egress=={pin}" if pin else "terp-cap-egress"
        report.not_made(
            "known-vulnerability: terp-cap-egress is not installed in this environment, so the "
            f"vulnerability database was not asked: add it to the development group (`uv add --dev {spec}`)"
        )
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
            "(or pass --osv with a mirror), then run it again.",
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
