"""Release permission over complete audits and authenticated, current acceptances.

This evaluator does not authenticate records. Its caller must verify the issuer and
obtain current revocation state outside the agent's execution boundary. Raw checks
and assurance are never modified. No other failed check can be accepted here.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from terp.cli.audit_findings import blocking, digest

AUDITS = {"dependency-audit-npm": "npm", "dependency-audit-python": "pypi"}
MAX_LIFETIME = timedelta(days=30)
MAX_SCAN_AGE = timedelta(hours=24)
IDENTITY = ("advisories", "ecosystem", "package", "version", "lockfile", "dependency_paths")


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


def fingerprint(item: object) -> str:
    if not isinstance(item, dict) or not all(key in item for key in IDENTITY):
        raise RiskRefused("a finding has no complete identity")
    for key in ("advisories", "dependency_paths"):
        values = item[key]
        if (not isinstance(values, list) or not values
                or not all(isinstance(v, str) and v for v in values)
                or values != sorted(set(values))):
            raise RiskRefused("finding identities must be nonempty, sorted and unique")
    for key in ("package", "version", "lockfile"):
        if not isinstance(item[key], str) or not item[key]:
            raise RiskRefused("a finding has an empty identity")
    if item["ecosystem"] not in {"npm", "pypi"}:
        raise RiskRefused("unknown dependency ecosystem")
    if item.get("severity") not in {"info", "low", "moderate", "high", "critical", "unknown"}:
        raise RiskRefused("unknown dependency severity")
    if item["ecosystem"] == "npm" and item["severity"] == "unknown":
        raise RiskRefused("npm did not classify the advisory")
    fixed = item.get("fixed_versions")
    if (not isinstance(fixed, list) or not all(isinstance(value, str) and value for value in fixed)
            or fixed != sorted(set(fixed)) or item.get("dependency_scope") not in {"runtime", "development", "unknown"}):
        raise RiskRefused("finding metadata is incomplete or invalid")
    result = digest({key: item[key] for key in IDENTITY})
    if result != item.get("fingerprint"):
        raise RiskRefused("a finding fingerprint does not match its content")
    return result


def valid_acceptance(record: object, *, project: str, commit: str, environment: str,
                     locks: dict, now: datetime) -> str:
    if not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1:
        raise RiskRefused("unsupported acceptance document")
    if record.get("project_id") != project or record.get("commit") != commit:
        raise RiskRefused("acceptance belongs to another project or commit")
    if not isinstance(record.get("environments"), list) or environment not in record["environments"]:
        raise RiskRefused("acceptance does not cover this environment")
    if record.get("locks") != locks:
        raise RiskRefused("acceptance covers another dependency lock set")
    if record.get("revoked_at") != "":
        raise RiskRefused("acceptance was revoked or has no revocation state")
    for key in ("id", "reason", "approved_by"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise RiskRefused("acceptance has no identity, human approver or justification")
    if (not isinstance(record.get("evidence"), list) or not record["evidence"]
            or not all(isinstance(v, str) and v.strip() for v in record["evidence"])):
        raise RiskRefused("acceptance has no supporting evidence")
    start, end = time_value(record.get("approved_at")), time_value(record.get("expires_at"))
    if not start <= now < end or end - start > MAX_LIFETIME:
        raise RiskRefused("acceptance is expired, not yet valid, or longer than 30 days")
    return fingerprint(record.get("finding"))


def evaluate(checks: list[dict], acceptances: list[dict], *, project: str,
             commit: str, environment: str, now: datetime | None = None) -> dict:
    """Compute permission; inputs are authenticated by the trusted caller, not this function."""
    now = now or datetime.now(UTC)
    if (not project or not environment or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit)
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
        audit = check.get("dependency_audit")
        if (not isinstance(audit, dict) or type(audit.get("version")) is not int or audit["version"] != 1
                or audit.get("complete") is not True):
            raise RiskRefused("dependency scan is incomplete")
        scanned = time_value(audit.get("scanned_at"))
        if not now - MAX_SCAN_AGE <= scanned <= now:
            raise RiskRefused("dependency scan is stale or in the future")
        scan_locks, items = audit.get("locks"), audit.get("findings")
        if not isinstance(scan_locks, dict) or not isinstance(items, list):
            raise RiskRefused("dependency scan omitted its locks or findings")
        for path, value in scan_locks.items():
            if not isinstance(path, str) or not path or not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                raise RiskRefused("dependency scan has an invalid lock digest")
            if path in locks and locks[path] != value:
                raise RiskRefused("dependency scans disagree about the locks")
            locks[path] = value
        if check["applicable"] != bool(scan_locks) or (not check["applicable"] and items):
            raise RiskRefused("dependency scan contradicts its applicability")
        blocked = []
        for item in items:
            key = fingerprint(item)
            if item["ecosystem"] != AUDITS[check["id"]] or item["lockfile"] not in scan_locks:
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
        approved = time_value(record.get("approved_at"))
        if key in latest:
            previous = time_value(latest[key]["approved_at"])
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
