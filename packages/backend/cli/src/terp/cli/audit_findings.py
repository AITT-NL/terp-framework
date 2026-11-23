"""Normalize scanner evidence without interpreting a scanner error as a clean audit.

Dependency metadata describes installation scope, never exploitability. Findings keep
every installed occurrence; accepting one occurrence cannot cover another lock or version.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

#: The longest string and the longest list terp-spec's ``dependency-audit`` contract holds. A
#: finding past either is never written, so every document a scan writes is the contract's.
MAX_TEXT = 4096
MAX_ITEMS = 10_000


class AuditUnreadable(ValueError):
    """The scanner or lock did not provide complete evidence."""


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _object(value: object) -> dict:
    if not isinstance(value, dict):
        raise AuditUnreadable("expected an object in the dependency audit")
    return value


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise AuditUnreadable("expected a list of nonempty strings in the dependency audit")
    return sorted(set(value))


def finding(*, advisory: str, aliases: list[str], ecosystem: str, package: str,
            version: str, lockfile: str, paths: list[str], severity: str,
            fixed: list[str], scope: str) -> dict[str, Any]:
    identity = {
        "advisories": sorted(set([advisory, *aliases])), "ecosystem": ecosystem,
        "package": package, "version": version, "lockfile": lockfile,
        "dependency_paths": sorted(set(paths)),
    }
    if not all(isinstance(v, str) and v for v in (advisory, package, version, lockfile)):
        raise AuditUnreadable("a dependency finding has no identity")
    fixed_versions = sorted(set(fixed))
    lists = (identity["advisories"], identity["dependency_paths"], fixed_versions)
    if any(len(values) > MAX_ITEMS for values in lists) or any(
        len(text) > MAX_TEXT for text in (package, version, lockfile, *(text for values in lists for text in values))
    ):
        raise AuditUnreadable(
            f"a dependency finding is longer than the dependency-audit contract holds: {MAX_TEXT} "
            f"characters to a string and {MAX_ITEMS} entries to a list"
        )
    return {**identity, "fingerprint": digest(identity), "severity": severity,
            "fixed_versions": fixed_versions, "dependency_scope": scope}


def npm_findings(report: object, lock: object, lockfile: str) -> list[dict]:
    report, lock = _object(report), _object(lock)
    if "error" in report or report.get("auditReportVersion") != 2:
        raise AuditUnreadable("npm audit did not complete with a version 2 report")
    vulnerabilities = _object(report.get("vulnerabilities"))
    packages = _object(lock.get("packages"))
    counts = _object(_object(report.get("metadata")).get("vulnerabilities"))
    if type(counts.get("total")) is not int or counts["total"] != len(vulnerabilities):
        raise AuditUnreadable("npm audit vulnerability counts contradict its findings")
    found: dict[str, dict] = {}

    def advisories(name: str, visiting: frozenset[str] = frozenset()) -> list[dict]:
        if name in visiting:
            raise AuditUnreadable("npm audit contains cyclic vulnerability references")
        entry = _object(vulnerabilities.get(name))
        via = entry.get("via")
        if not isinstance(via, list) or not via:
            raise AuditUnreadable("npm audit contains a vulnerability with no advisory")
        result = []
        for source in via:
            if isinstance(source, str):
                result.extend(advisories(source, visiting | {name}))
            else:
                result.append(_object(source))
        return result

    for name, value in vulnerabilities.items():
        entry = _object(value)
        nodes = _strings(entry.get("nodes"))
        if not nodes:
            raise AuditUnreadable("npm audit contains a vulnerability with no installed path")
        for advisory in advisories(name):
            url = advisory.get("url", "")
            match = re.fullmatch(r"https://github.com/advisories/(GHSA-[a-z0-9-]+)", str(url))
            if match is None or advisory.get("severity") not in {"info", "low", "moderate", "high", "critical"}:
                raise AuditUnreadable("npm audit contains an unrecognized advisory identity or severity")
            for node in nodes:
                installed = _object(packages.get(node))
                item = finding(
                    advisory=match[1], aliases=[], ecosystem="npm", package=name,
                    version=installed.get("version", ""), lockfile=lockfile, paths=[node],
                    severity=advisory["severity"], fixed=[],
                    scope="development" if installed.get("dev") is True else "runtime",
                )
                if item["fingerprint"] in found and found[item["fingerprint"]] != item:
                    raise AuditUnreadable("npm audit contradicts itself about an advisory")
                found[item["fingerprint"]] = item
    return sorted(found.values(), key=lambda item: item["fingerprint"])


def python_findings(report: object, lockfile: str = "uv.lock", *, project_names: frozenset[str] = frozenset()) -> list[dict]:
    report = _object(report)
    if report.get("fixes"):
        raise AuditUnreadable("an audit must not modify dependencies")
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        raise AuditUnreadable("pip-audit did not return dependencies")
    result = []
    for dependency in dependencies:
        dependency = _object(dependency)
        if "skip_reason" in dependency:
            # The application's own code has no registry advisory identity. Its lock
            # explicitly marks it as the root; skipping any third-party package fails.
            name = dependency.get("name", "")
            if isinstance(name, str) and re.sub(r"[-_.]+", "-", name).lower() in project_names:
                continue
            raise AuditUnreadable("pip-audit skipped a dependency")
        if not all(isinstance(dependency.get(key), str) and dependency[key] for key in ("name", "version")):
            raise AuditUnreadable("pip-audit omitted a dependency's identity")
        vulns = dependency.get("vulns")
        if not isinstance(vulns, list):
            raise AuditUnreadable("pip-audit omitted a dependency's findings")
        for vuln in vulns:
            vuln = _object(vuln)
            aliases = _strings(vuln.get("aliases", []))
            result.append(finding(
                advisory=vuln.get("id", ""), aliases=aliases, ecosystem="pypi",
                package=dependency.get("name", ""), version=dependency.get("version", ""),
                lockfile=lockfile, paths=[dependency.get("name", "")], severity="unknown",
                fixed=_strings(vuln.get("fix_versions", [])), scope="unknown",
            ))
    found = {}
    for item in result:
        if item["fingerprint"] in found and found[item["fingerprint"]] != item:
            raise AuditUnreadable("pip-audit contradicts itself about an advisory")
        found[item["fingerprint"]] = item
    return sorted(found.values(), key=lambda item: item["fingerprint"])


def blocking(item: dict) -> bool:
    """npm retains its high threshold; pip-audit retains its all-findings threshold."""
    return item["ecosystem"] == "pypi" or item["severity"] in {"high", "critical"}
