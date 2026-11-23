"""Release permission over complete audits and authenticated, current acceptances.

This evaluator does not authenticate records. Its caller must verify the issuer and
obtain current revocation state outside the agent's execution boundary. Raw checks
and assurance are never modified. No other failed check can be accepted here.

A check's evidence and each acceptance are documents of the Terp Standard, terp-spec's
``dependency-audit`` and ``dependency-risk-acceptance``, and both are read closed, as
their schemas are: a field neither defines, a string the contract counts as blank or
holds longer than it allows, and a digest, commit or time with anything around it are
refused, never read past. The patterns below are the schemas' own words, and
``tests/architecture/test_dependency_risk.py`` holds them, the fields and the limits to
the pinned release and runs its fixtures through this reader.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from terp.cli.audit_findings import MAX_ITEMS, MAX_TEXT, blocking, digest

AUDITS = {"dependency-audit-npm": "npm", "dependency-audit-python": "pypi"}
MAX_LIFETIME = timedelta(days=30)
MAX_SCAN_AGE = timedelta(hours=24)
IDENTITY = ("advisories", "ecosystem", "package", "version", "lockfile", "dependency_paths")

#: The fields each contract defines: every one is required, and no other is allowed.
AUDIT_FIELDS = frozenset({"version", "complete", "scanned_at", "locks", "findings"})
FINDING_FIELDS = frozenset({*IDENTITY, "fingerprint", "severity", "fixed_versions", "dependency_scope"})
ACCEPTANCE_FIELDS = frozenset({
    "version", "id", "project_id", "commit", "environments", "finding", "locks", "reason", "evidence",
    "approved_by", "approved_at", "expires_at", "revoked_at",
})

#: The contracts' patterns as their schemas write them, applied as JSON Schema applies a
#: pattern: by a search. ``CONTENT`` finds one character the acceptance contract does not count
#: as blank, which each field saying who decided, for what, why and on what evidence must hold.
CONTENT = re.compile(r"[^\u0000-\u0020\u007F-\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF]")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}(?![\s\S])")
COMMIT = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})(?![\s\S])")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$")


class RiskRefused(ValueError):
    """Incomplete evidence or invalid acceptance; permission stays closed."""


def time_value(value: object) -> datetime:
    if not isinstance(value, str):
        raise RiskRefused("an acceptance timestamp is missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RiskRefused("an acceptance timestamp is invalid") from exc
    if result.utcoffset() != timedelta(0):
        raise RiskRefused("acceptance timestamps must be UTC")
    return result


def instant(value: object) -> datetime:
    """A time as both contracts write one, ``2026-11-18T12:00:00Z``, or a refusal.

    Python's matcher lets the pattern's ``\\d`` take a digit of any script and its ``$`` a
    trailing newline, where the contract's takes neither; the parse after it refuses both.
    """
    if not isinstance(value, str) or not INSTANT.search(value):
        raise RiskRefused("a dependency risk time must be UTC, written YYYY-MM-DDThh:mm:ss with at most "
                          "six decimals, then Z or +00:00")
    return time_value(value)


def _said(value: object) -> bool:
    """Whether *value* is a string of 1 to MAX_TEXT characters, one outside the blank class."""
    return isinstance(value, str) and 0 < len(value) <= MAX_TEXT and CONTENT.search(value) is not None


def _texts(value: object, *, said: bool = False, ordered: bool = False, required: bool = True) -> bool:
    """Whether *value* is a list of at most MAX_ITEMS distinct strings of 1 to MAX_TEXT characters.

    Each holds content where *said*; the list is sorted where *ordered* and not empty where *required*.
    """
    if not isinstance(value, list) or len(value) > MAX_ITEMS or (required and not value):
        return False
    if not all(isinstance(item, str) and 0 < len(item) <= MAX_TEXT and (not said or _said(item)) for item in value):
        return False
    return value == sorted(set(value)) if ordered else len(set(value)) == len(value)


def _lock_map(value: object) -> bool:
    """Whether *value* maps each lock's path to its whole sha256 digest."""
    return isinstance(value, dict) and all(
        isinstance(path, str) and path and isinstance(recorded, str) and DIGEST.search(recorded) is not None
        for path, recorded in value.items()
    )


def fingerprint(item: object) -> str:
    if not isinstance(item, dict) or not all(key in item for key in IDENTITY):
        raise RiskRefused("a finding has no complete identity")
    if set(item) != FINDING_FIELDS:
        raise RiskRefused("a finding holds a field the dependency contracts do not define, or lacks one")
    if not all(_texts(item[key], ordered=True) for key in ("advisories", "dependency_paths")):
        raise RiskRefused("finding identities must be nonempty, sorted and unique")
    for key in ("package", "version", "lockfile"):
        if not isinstance(item[key], str) or not 0 < len(item[key]) <= MAX_TEXT:
            raise RiskRefused("a finding has an empty or overlong identity")
    if item["ecosystem"] not in {"npm", "pypi"}:
        raise RiskRefused("unknown dependency ecosystem")
    if item["severity"] not in {"info", "low", "moderate", "high", "critical", "unknown"}:
        raise RiskRefused("unknown dependency severity")
    if item["ecosystem"] == "npm" and item["severity"] == "unknown":
        raise RiskRefused("npm did not classify the advisory")
    if (not _texts(item["fixed_versions"], ordered=True, required=False)
            or item["dependency_scope"] not in {"runtime", "development", "unknown"}):
        raise RiskRefused("finding metadata is incomplete or invalid")
    result = digest({key: item[key] for key in IDENTITY})
    if result != item["fingerprint"]:
        raise RiskRefused("a finding fingerprint does not match its content")
    return result


def audit_evidence(audit: object, *, now: datetime) -> tuple[dict[str, str], dict[str, dict]]:
    """A complete, current ``dependency-audit`` document's locks, and its findings by fingerprint.

    Refused unless the scan finished at most :data:`MAX_SCAN_AGE` before *now*, and each finding
    is whole, belongs to one of the scan's locks and is listed once.
    """
    if (not isinstance(audit, dict) or type(audit.get("version")) is not int or audit["version"] != 1
            or audit.get("complete") is not True):
        raise RiskRefused("dependency scan is incomplete")
    if set(audit) != AUDIT_FIELDS:
        raise RiskRefused("a dependency scan holds a field the dependency-audit contract does not define, or lacks one")
    scanned = instant(audit["scanned_at"])
    if not now - MAX_SCAN_AGE <= scanned <= now:
        raise RiskRefused("dependency scan is stale or in the future")
    locks, items = audit["locks"], audit["findings"]
    if not isinstance(locks, dict) or not isinstance(items, list):
        raise RiskRefused("dependency scan omitted its locks or findings")
    if len(items) > MAX_ITEMS:
        raise RiskRefused(f"dependency scan lists more than {MAX_ITEMS} findings, more than its contract holds")
    if not _lock_map(locks):
        raise RiskRefused("dependency scan has an invalid lock digest")
    findings: dict[str, dict] = {}
    for item in items:
        key = fingerprint(item)
        if item["lockfile"] not in locks:
            raise RiskRefused("finding does not belong to this scan")
        if key in findings:
            raise RiskRefused("dependency scan duplicated a finding")
        findings[key] = item
    return locks, findings


def valid_acceptance(record: object, *, project: str, commit: str, environment: str,
                     locks: dict, now: datetime) -> str:
    if not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1:
        raise RiskRefused("unsupported acceptance document")
    if set(record) != ACCEPTANCE_FIELDS:
        raise RiskRefused("an acceptance holds a field the dependency-risk-acceptance contract does not define, "
                          "or lacks one")
    if not all(_said(record[key]) for key in ("id", "project_id", "reason", "approved_by")):
        raise RiskRefused("acceptance has no identity, human approver or justification")
    if not _texts(record["environments"], said=True):
        raise RiskRefused("acceptance names no environment it covers")
    if not _texts(record["evidence"], said=True):
        raise RiskRefused("acceptance has no supporting evidence")
    if not isinstance(record["commit"], str) or not COMMIT.search(record["commit"]):
        raise RiskRefused("acceptance names no exact commit")
    if not record["locks"] or not _lock_map(record["locks"]):
        raise RiskRefused("acceptance names no dependency lock with its whole sha256 digest")
    if record["project_id"] != project or record["commit"] != commit:
        raise RiskRefused("acceptance belongs to another project or commit")
    if environment not in record["environments"]:
        raise RiskRefused("acceptance does not cover this environment")
    if record["locks"] != locks:
        raise RiskRefused("acceptance covers another dependency lock set")
    if record["revoked_at"] != "":
        raise RiskRefused("acceptance was revoked or has no revocation state")
    start, end = instant(record["approved_at"]), instant(record["expires_at"])
    if not start <= now < end or end - start > MAX_LIFETIME:
        raise RiskRefused("acceptance is expired, not yet valid, or longer than 30 days")
    return fingerprint(record["finding"])


def evaluate(checks: list[dict], acceptances: list[dict], *, project: str,
             commit: str, environment: str, now: datetime | None = None) -> dict:
    """Compute permission; inputs are authenticated by the trusted caller, not this function."""
    now = now or datetime.now(UTC)
    if (not project or not environment or not isinstance(commit, str) or not COMMIT.search(commit)
            or now.utcoffset() != timedelta(0)):
        raise RiskRefused("release permission requires an exact project, commit, environment and UTC time")
    if not isinstance(checks, list) or not checks:
        raise RiskRefused("release permission requires every release check")
    ids = [c.get("id") for c in checks if isinstance(c, dict)]
    if len(ids) != len(checks) or any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise RiskRefused("release checks are malformed or duplicated")
    if not AUDITS.keys() <= set(ids):
        raise RiskRefused("release checks omit a dependency audit")
    locks, findings, failures = {}, {}, []
    for check in checks:
        if type(check.get("ok")) is not bool or type(check.get("applicable")) is not bool:
            raise RiskRefused("a release check has no verdict")
        if check["id"] not in AUDITS:
            if not check["ok"]:
                failures.append(check["id"])
            continue
        scan_locks, scanned = audit_evidence(check.get("dependency_audit"), now=now)
        for path, value in scan_locks.items():
            if path in locks and locks[path] != value:
                raise RiskRefused("dependency scans disagree about the locks")
            locks[path] = value
        if check["applicable"] != bool(scan_locks) or (not check["applicable"] and scanned):
            raise RiskRefused("dependency scan contradicts its applicability")
        blocked = []
        for key, item in scanned.items():
            if item["ecosystem"] != AUDITS[check["id"]]:
                raise RiskRefused("finding does not belong to this scan")
            if key in findings:
                raise RiskRefused("dependency scan duplicated a finding")
            findings[key] = item
            if blocking(item):
                blocked.append(key)
        if check["ok"] != (not blocked):
            raise RiskRefused("dependency scan contradicts its verdict")
    # Select the current decision before validating its lifetime or revocation. An
    # expired older record must not defeat a renewal, and withdrawing the renewal
    # must never bring an older approval back into force.
    latest = {}
    for record in acceptances:
        if not isinstance(record, dict):
            raise RiskRefused("an acceptance record is malformed")
        key = fingerprint(record.get("finding"))
        approved = instant(record.get("approved_at"))
        if key in latest:
            previous = instant(latest[key]["approved_at"])
            if approved == previous:
                raise RiskRefused("ambiguous acceptance decisions for a finding")
            if approved < previous:
                continue
        latest[key] = record
    covered = {}
    for record in latest.values():
        key = valid_acceptance(record, project=project, commit=commit, environment=environment, locks=locks, now=now)
        if key not in findings or record["finding"] != findings[key]:
            raise RiskRefused("acceptance is stale or describes another finding")
        covered[key] = record["id"]
    unaccepted = sorted(key for key, item in findings.items() if blocking(item) and key not in covered)
    used = sorted(covered[key] for key, item in findings.items() if blocking(item) and key in covered)
    return {"version": 1, "allowed": not failures and not unaccepted,
            "status": "blocked" if failures or unaccepted else "accepted" if used else "passed",
            "failed_checks": failures, "unaccepted_findings": unaccepted, "acceptance_ids": used}
