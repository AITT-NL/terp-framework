"""Release permission over complete audits and authenticated, current acceptances.

This evaluator does not authenticate records. Its caller must verify the issuer and
obtain current revocation state outside the agent's execution boundary. Raw checks
and assurance are never modified. No other failed check can be accepted here.

A check's evidence and every acceptance an authority returns are documents of the Terp
Standard, terp-spec's ``dependency-audit`` and ``dependency-risk-acceptance``, and both
are read closed, as their schemas are: a field neither defines, a string the contract
counts as blank or holds longer than it allows, and a digest, commit or time with
anything around it are refused, never read past. A superseded acceptance is held to the
contract too; only its lifetime, its revocation and the release it names are left to
the decision that replaces it. The patterns and limits below are the schemas' own, and
``tests/architecture/test_dependency_risk.py`` holds this reader to the pinned release:
it runs the release's fixtures, and breaks the schemas' rules one at a time at every
field, requiring a refusal for each document the pinned schema refuses.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

from terp.cli.audit_findings import MAX_ITEMS, MAX_TEXT, blocking, digest

AUDITS = {"dependency-audit-npm": "npm", "dependency-audit-python": "pypi"}
MAX_LIFETIME = timedelta(days=30)
MAX_SCAN_AGE = timedelta(hours=24)
IDENTITY = ("advisories", "ecosystem", "package", "version", "lockfile", "dependency_paths")

#: The longest ``revoked_at`` an acceptance may hold. The decision a release is read against
#: holds none (""); a superseded one may say when it was revoked.
MAX_REVOCATION = 40

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

#: What ``INSTANT`` means read as JSON Schema reads it, which Python's matcher does not: ASCII
#: digits and nothing after the zone. The hour stops at 23 because Python 3.14 reads 24:00:00 as
#: the next midnight where 3.13 refuses it, and a verdict must not depend on the interpreter.
_UTC_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)")


class RiskRefused(ValueError):
    """Incomplete evidence or invalid acceptance; permission stays closed."""


def time_value(value: object, what: str) -> datetime:
    """A UTC time in any ISO 8601 form Python reads, as a risk authority's own answer may write one.

    *what* names the time in a refusal: the field, and the record it is in.
    """
    if value is None:
        raise RiskRefused(f"{what} is missing")
    if not isinstance(value, str):
        raise RiskRefused(f"{what} is not a string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RiskRefused(f"{what} is not a date and time") from exc
    if result.utcoffset() != timedelta(0):
        raise RiskRefused(f"{what} must be UTC")
    return result


def instant(value: object, what: str) -> datetime:
    """A time as both contracts write one, ``2026-11-18T12:00:00Z``, or a refusal naming *what*."""
    if not isinstance(value, str) or not INSTANT.search(value) or not _UTC_TIME.fullmatch(value):
        raise RiskRefused(f"{what} must be UTC, written YYYY-MM-DDThh:mm:ss with at most six decimals, "
                          "then Z or +00:00")
    return time_value(value, what)


def _names(fields: list[str]) -> str:
    """Field names as a refusal shows them: escaped, the first five, each cut at 64 characters."""
    shown = ", ".join(json.dumps(name[:64]) for name in fields[:5])
    return shown + (f" and {len(fields) - 5} more" if len(fields) > 5 else "")


def _closed(document: dict, fields: frozenset[str], what: str, contract: str) -> None:
    """Refused unless *document* holds exactly the *fields* its *contract* defines."""
    extra, missing = sorted(str(name) for name in set(document) - fields), sorted(fields - set(document))
    if extra or missing:
        said = [f"holds {_names(extra)}, which the {contract} contract does not define"] if extra else []
        said += [f"lacks {_names(missing)}, which the {contract} contract requires"] if missing else []
        raise RiskRefused(f"{what} {' and '.join(said)}: whatever writes it must write the contract's fields")


def _text_problem(value: object, *, said: bool = False) -> str | None:
    """What keeps *value* from being a string of the contracts, or None.

    One of 1 to MAX_TEXT characters, and where *said*, one character outside the blank class.
    """
    if not isinstance(value, str):
        return "is not a string"
    if not value:
        return "is empty"
    if len(value) > MAX_TEXT:
        return f"is longer than {MAX_TEXT} characters"
    if said and CONTENT.search(value) is None:
        return "holds only characters the contract counts as blank"
    return None


def _list_problem(value: object, *, said: bool = False, ordered: bool = False, required: bool = True) -> str | None:
    """What keeps *value* from being a list of the contracts, or None.

    At most MAX_ITEMS distinct strings, each as :func:`_text_problem` reads one: sorted where
    *ordered*, and not empty where *required*.
    """
    if not isinstance(value, list):
        return "is not a list"
    if required and not value:
        return "is empty"
    if len(value) > MAX_ITEMS:
        return f"lists more than {MAX_ITEMS} entries"
    for item in value:
        problem = _text_problem(item, said=said)
        if problem is not None:
            return f"has an entry that {problem}"
    if len(set(value)) != len(value):
        return "lists an entry more than once"
    if ordered and value != sorted(value):
        return "is not sorted"
    return None


def _lock_problem(value: object) -> str | None:
    """What keeps *value* from mapping each lock's path to its whole sha256 digest, or None."""
    if not isinstance(value, dict):
        return "is not an object of lock paths and digests"
    for path, recorded in value.items():
        if not isinstance(path, str) or not path:
            return "names a lock with an empty path"
        if not isinstance(recorded, str) or DIGEST.search(recorded) is None:
            return f"gives {_names([path])} no whole sha256 digest"
    return None


def _one_of(value: object, *choices: str) -> bool:
    """Whether *value* is one of the strings *choices*; a value of any other type is none of them."""
    return isinstance(value, str) and value in choices


def fingerprint(item: object, where: str = "a finding", contract: str = "dependency-audit") -> str:
    """The fingerprint of *item*, a finding of *contract*, or a refusal that names it as *where*."""
    if not isinstance(item, dict):
        raise RiskRefused(f"{where} is not an object")
    _closed(item, FINDING_FIELDS, where, contract)
    for key, problem in (
        *((key, _list_problem(item[key], ordered=True)) for key in ("advisories", "dependency_paths")),
        *((key, _text_problem(item[key])) for key in ("package", "version", "lockfile")),
        ("fixed_versions", _list_problem(item["fixed_versions"], ordered=True, required=False)),
    ):
        if problem is not None:
            raise RiskRefused(f"{where}: {key} {problem}")
    if not _one_of(item["ecosystem"], "npm", "pypi"):
        raise RiskRefused(f"{where}: ecosystem is not npm or pypi")
    if not _one_of(item["severity"], "info", "low", "moderate", "high", "critical", "unknown"):
        raise RiskRefused(f"{where}: severity is not info, low, moderate, high, critical or unknown")
    if item["ecosystem"] == "npm" and item["severity"] == "unknown":
        raise RiskRefused(f"{where}: severity is unknown, and npm classifies every advisory it reports")
    if not _one_of(item["dependency_scope"], "runtime", "development", "unknown"):
        raise RiskRefused(f"{where}: dependency_scope is not runtime, development or unknown")
    result = digest({key: item[key] for key in IDENTITY})
    if result != item["fingerprint"]:
        raise RiskRefused(f"{where}: fingerprint is not the one its identity hashes to")
    return result


def audit_evidence(audit: object, *, now: datetime,
                   name: str = "the dependency scan") -> tuple[dict[str, str], dict[str, dict]]:
    """A complete, current ``dependency-audit`` document's locks, and its findings by fingerprint.

    Refused unless the scan finished at most :data:`MAX_SCAN_AGE` before *now*, and each finding
    is whole, belongs to one of the scan's locks and is listed once. *name* says which scan a
    refusal is about.
    """
    if not isinstance(audit, dict) or type(audit.get("version")) is not int or audit["version"] != 1:
        raise RiskRefused(f"{name} is not version 1 of the dependency-audit contract: audit again with the "
                          "toolchain the release pins")
    if audit.get("complete") is not True:
        raise RiskRefused(f"{name} is incomplete")
    _closed(audit, AUDIT_FIELDS, name, "dependency-audit")
    scanned = instant(audit["scanned_at"], f"{name}: scanned_at")
    if not now - MAX_SCAN_AGE <= scanned <= now:
        raise RiskRefused(f"{name} is stale or in the future: audit again")
    locks, items = audit["locks"], audit["findings"]
    problem = _lock_problem(locks)
    if problem is not None:
        raise RiskRefused(f"{name}: locks {problem}")
    if not isinstance(items, list):
        raise RiskRefused(f"{name}: findings is not a list")
    if len(items) > MAX_ITEMS:
        raise RiskRefused(f"{name} lists more than {MAX_ITEMS} findings, more than its contract holds")
    findings: dict[str, dict] = {}
    for index, item in enumerate(items):
        where = f"finding {index} of {name}"
        key = fingerprint(item, where)
        if item["lockfile"] not in locks:
            raise RiskRefused(f"{where}: lockfile {_names([item['lockfile']])} is not one of the scan's locks")
        if key in findings:
            raise RiskRefused(f"{where} repeats an earlier finding of the scan")
        findings[key] = item
    return locks, findings


def acceptance_form(record: object) -> tuple[dict, str, datetime]:
    """*record*, the fingerprint of the finding it accepts and when it was approved, or a refusal.

    Refused unless *record* is a ``dependency-risk-acceptance`` document: version 1, the fields
    the contract defines, content in each field that says who decided, for what, why and on what
    evidence, an exact commit, at least one lock with its whole digest, and both times in the
    contract's form. Nothing here depends on the release the record is read for, so every record
    an authority returns is held to it, a superseded one included.
    """
    if not isinstance(record, dict):
        raise RiskRefused("an acceptance record is malformed: it is not an object")
    if type(record.get("version")) is not int or record["version"] != 1:
        raise RiskRefused(f"{_label(record)} is not version 1 of the dependency-risk-acceptance contract")
    _closed(record, ACCEPTANCE_FIELDS, _label(record), "dependency-risk-acceptance")
    problem = _text_problem(record["id"], said=True)
    if problem is not None:
        raise RiskRefused(f"an acceptance's id {problem}")
    label = _label(record)
    for key, problem in (
        *((key, _text_problem(record[key], said=True)) for key in ("project_id", "reason", "approved_by")),
        *((key, _list_problem(record[key], said=True)) for key in ("environments", "evidence")),
    ):
        if problem is not None:
            raise RiskRefused(f"{label}: {key} {problem}")
    if not isinstance(record["commit"], str) or not COMMIT.search(record["commit"]):
        raise RiskRefused(f"{label}: commit is not a whole commit id, 40 or 64 lowercase hex characters")
    problem = "names no lock" if record["locks"] == {} else _lock_problem(record["locks"])
    if problem is not None:
        raise RiskRefused(f"{label}: locks {problem}")
    if not isinstance(record["revoked_at"], str) or len(record["revoked_at"]) > MAX_REVOCATION:
        raise RiskRefused(f"{label}: revoked_at is not a string of at most {MAX_REVOCATION} characters")
    approved = instant(record["approved_at"], f"{label}: approved_at")
    instant(record["expires_at"], f"{label}: expires_at")
    return record, fingerprint(record["finding"], f"the finding of {label}", "dependency-risk-acceptance"), approved


def _label(record: dict) -> str:
    """An acceptance as a refusal names it: by its id, where it has one that says something."""
    named = record.get("id")
    return f"acceptance {_names([named])}" if _text_problem(named, said=True) is None else "an acceptance"


def valid_acceptance(record: object, *, project: str, commit: str, environment: str,
                     locks: dict, now: datetime) -> str:
    """The fingerprint *record* accepts, if it is the contract's and covers this release *now*."""
    document, key, start = acceptance_form(record)
    label = _label(document)
    if document["project_id"] != project or document["commit"] != commit:
        raise RiskRefused(f"{label} belongs to another project or commit")
    if environment not in document["environments"]:
        raise RiskRefused(f"{label} does not cover this environment")
    if document["locks"] != locks:
        raise RiskRefused(f"{label} covers another dependency lock set")
    if document["revoked_at"] != "":
        raise RiskRefused(f"{label} was revoked")
    end = instant(document["expires_at"], f"{label}: expires_at")
    if not start <= now < end or end - start > MAX_LIFETIME:
        raise RiskRefused(f"{label} is expired, not yet valid, or longer than 30 days")
    return key


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
        name = f"the {check['id']} scan"
        scan_locks, scanned = audit_evidence(check.get("dependency_audit"), now=now, name=name)
        for path, value in scan_locks.items():
            if path in locks and locks[path] != value:
                raise RiskRefused(f"{name} gives {_names([path])} another digest than the other scan does")
            locks[path] = value
        if check["applicable"] != bool(scan_locks) or (not check["applicable"] and scanned):
            raise RiskRefused(f"{name} contradicts its applicability")
        blocked = []
        for key, item in scanned.items():
            # A fingerprint covers the ecosystem, and each audit holds only its own, so the
            # two audits can never list one finding between them: no repeat to refuse here.
            if item["ecosystem"] != AUDITS[check["id"]]:
                raise RiskRefused(f"{name} lists a {item['ecosystem']} finding, and it audits {AUDITS[check['id']]} alone")
            findings[key] = item
            if blocking(item):
                blocked.append(key)
        if check["ok"] != (not blocked):
            raise RiskRefused(f"{name} contradicts its verdict")
    # Every record is the contract's, a superseded one too. Then select the current
    # decision before validating its lifetime or revocation: an expired older record must
    # not defeat a renewal, and withdrawing the renewal must never bring an older approval
    # back into force.
    latest: dict[str, tuple[dict, datetime]] = {}
    for record in acceptances:
        document, key, approved = acceptance_form(record)
        if key in latest:
            previous = latest[key][1]
            if approved == previous:
                raise RiskRefused(f"{_label(document)} and {_label(latest[key][0])} decide one finding at the same time")
            if approved < previous:
                continue
        latest[key] = (document, approved)
    covered = {}
    for record, _approved in latest.values():
        key = valid_acceptance(record, project=project, commit=commit, environment=environment, locks=locks, now=now)
        if key not in findings or record["finding"] != findings[key]:
            raise RiskRefused(f"{_label(record)} is stale or describes another finding")
        covered[key] = record["id"]
    unaccepted = sorted(key for key, item in findings.items() if blocking(item) and key not in covered)
    used = sorted(covered[key] for key, item in findings.items() if blocking(item) and key in covered)
    return {"version": 1, "allowed": not failures and not unaccepted,
            "status": "blocked" if failures or unaccepted else "accepted" if used else "passed",
            "failed_checks": failures, "unaccepted_findings": unaccepted, "acceptance_ids": used}
