"""Risk acceptance cannot hide scan errors or unrelated release failures."""

import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from terp_spec import spec_dir

from terp.cli import dependency_risk
from terp.cli.audit_findings import MAX_ITEMS, MAX_TEXT, AuditUnreadable, finding, npm_findings, python_findings
from terp.cli.dependency_risk import RiskRefused, audit_evidence, evaluate, valid_acceptance

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
COMMIT = "a" * 40


def evidence():
    item = finding(advisory="GHSA-aaaa-bbbb-cccc", aliases=[], ecosystem="npm", package="example-package",
                   version="1.0.0", lockfile="frontend/package-lock.json", paths=["node_modules/example-package"],
                   severity="high", fixed=[], scope="development")
    npm_locks = {"frontend/package-lock.json": "sha256:" + "b" * 64}
    py_locks = {"uv.lock": "sha256:" + "c" * 64}
    def scan(locks, findings):
        return {"version": 1, "complete": True, "scanned_at": NOW.isoformat(), "locks": locks, "findings": findings}
    checks = [
        {"id": "dependency-audit-npm", "ok": False, "applicable": True, "dependency_audit": scan(npm_locks, [item])},
        {"id": "dependency-audit-python", "ok": True, "applicable": True, "dependency_audit": scan(py_locks, [])},
        {"id": "backend-tests", "ok": True, "applicable": True},
    ]
    approval = {"version": 1, "id": "acceptance-1", "project_id": "example-project", "commit": COMMIT,
                "environments": ["production"], "finding": item, "locks": {**npm_locks, **py_locks},
                "reason": "Reviewed build exposure", "evidence": ["review-1"], "approved_by": "owner-1",
                "approved_at": NOW.isoformat(), "expires_at": "2026-11-25T12:00:00Z", "revoked_at": ""}
    return checks, approval


def decide(checks, acceptances):
    return evaluate(checks, acceptances, project="example-project", commit=COMMIT, environment="production", now=NOW)


def test_acceptance_permits_only_the_reviewed_finding_without_changing_raw_results():
    checks, approval = evidence()
    original = deepcopy(checks)
    assert decide(checks, [])['status'] == "blocked"
    decision = decide(checks, [approval])
    assert decision["allowed"] and decision["status"] == "accepted"
    assert checks == original and checks[0]["ok"] is False
    checks[2]["ok"] = False
    assert decide(checks, [approval])["allowed"] is False


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("state", ["current", "revoked", "expired"])
def test_latest_renewal_supersedes_older_decisions_before_validation(reverse, state):
    checks, renewal = evidence()
    older = deepcopy(renewal)
    older.update(id="older-approval", approved_at="2026-11-16T12:00:00Z")
    if state == "current":
        older["expires_at"] = "2026-11-17T12:00:00Z"
    elif state == "revoked":
        renewal["revoked_at"] = NOW.isoformat()
    else:
        renewal["expires_at"] = NOW.isoformat()
    records = [older, renewal]
    if reverse:
        records.reverse()
    if state == "current":
        assert decide(checks, records)["acceptance_ids"] == [renewal["id"]]
    else:
        with pytest.raises(RiskRefused):
            decide(checks, records)


def test_malformed_acceptance_records_fail_closed():
    checks, _ = evidence()
    with pytest.raises(RiskRefused, match="malformed"):
        decide(checks, [None])


@pytest.mark.parametrize(("field", "value"), [
    ("project_id", "other-project"), ("commit", "d" * 40), ("environments", ["test"]),
    ("locks", {}), ("locks", {"frontend/package-lock.json": "sha256:" + "d" * 64, "uv.lock": "sha256:" + "c" * 64}),
    ("approved_by", ""), ("reason", " "), ("evidence", []),
    ("revoked_at", "2026-11-18T11:00:00Z"), ("expires_at", NOW.isoformat()),
    ("approved_at", "2026-11-19T12:00:00Z"), ("expires_at", "2027-01-01T12:00:00Z"),
    ("approved_at", "2026-11-18T12:00:00"), ("approved_at", None), ("approved_at", "invalid"), ("version", True),
])
def test_invalid_acceptance_never_permits_release(field, value):
    checks, approval = evidence()
    approval[field] = value
    with pytest.raises(RiskRefused):
        decide(checks, [approval])


@pytest.mark.parametrize("damage", ["incomplete", "missing-audit", "duplicate-check", "stale", "future", "tampered", "false-green"])
def test_invalid_evidence_is_not_waivable(damage):
    checks, approval = evidence()
    audit = checks[0]["dependency_audit"]
    if damage == "incomplete":
        audit["complete"] = False
    elif damage == "missing-audit":
        checks.pop(1)
    elif damage == "duplicate-check":
        checks.append(deepcopy(checks[1]))
    elif damage == "stale":
        audit["scanned_at"] = "2026-11-01T12:00:00Z"
    elif damage == "future":
        audit["scanned_at"] = "2026-11-19T12:00:00Z"
    elif damage == "tampered":
        audit["findings"][0]["version"] = "2.0.0"
    else:
        checks[0]["ok"] = True
    with pytest.raises(RiskRefused):
        decide(checks, [approval])


def npm_report():
    advisory = {"url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc", "severity": "high"}
    report = {"auditReportVersion": 2, "metadata": {"vulnerabilities": {"total": 2}},
              "vulnerabilities": {"example-package": {"via": [advisory], "nodes": ["node_modules/example-package"]},
                                  "example-tool": {"via": ["example-package"], "nodes": ["node_modules/example-tool"]}}}
    lock = {"packages": {"node_modules/example-package": {"version": "1.0.0", "dev": True},
                         "node_modules/example-tool": {"version": "2.0.0", "dev": True}}}
    return report, lock


def test_npm_transitive_references_retain_every_affected_occurrence():
    report, lock = npm_report()
    findings = npm_findings(report, lock, "frontend/package-lock.json")
    assert len(findings) == 2
    assert {f["package"] for f in findings} == {"example-package", "example-tool"}
    assert all(f["advisories"] == ["GHSA-aaaa-bbbb-cccc"] for f in findings)


@pytest.mark.parametrize("damage", ["error", "missing-path", "cycle", "unknown-advisory", "counts"])
def test_npm_incomplete_reports_are_errors(damage):
    report, lock = npm_report()
    if damage == "error":
        report["error"] = {"code": "EAUDIT"}
    elif damage == "missing-path":
        lock["packages"] = {}
    elif damage == "cycle":
        report["vulnerabilities"]["example-package"]["via"] = ["example-tool"]
    elif damage == "unknown-advisory":
        report["vulnerabilities"]["example-package"]["via"] = [{"url": "unexpected"}]
    else:
        report["metadata"]["vulnerabilities"]["total"] = 0
    with pytest.raises(AuditUnreadable):
        npm_findings(report, lock, "frontend/package-lock.json")


def test_python_skipped_dependencies_are_not_clean():
    with pytest.raises(AuditUnreadable):
        python_findings({"dependencies": [{"name": "example-package", "skip_reason": "not found"}]})


def test_python_skips_only_explicitly_declared_project_roots():
    report = {"dependencies": [{"name": "Example_App", "skip_reason": "local project"}]}
    assert python_findings(report, project_names=frozenset({"example-app"})) == []
    with pytest.raises(AuditUnreadable, match="skipped"):
        python_findings(report, project_names=frozenset({"another-app"}))


def test_python_dependencies_must_report_their_findings():
    with pytest.raises(AuditUnreadable, match="findings"):
        python_findings({"dependencies": [{"name": "example-package", "version": "1.0.0"}]})


def test_python_aliases_and_fixes_are_retained():
    report = {"dependencies": [{"name": "example-package", "version": "1.0.0", "vulns": [
        {"id": "GHSA-aaaa-bbbb-cccc", "aliases": ["CVE-2026-0001"], "fix_versions": ["1.0.1"]}]}]}
    item, = python_findings(report)
    assert item["advisories"] == ["CVE-2026-0001", "GHSA-aaaa-bbbb-cccc"]
    assert item["fixed_versions"] == ["1.0.1"]


def test_python_conflicting_advisories_or_missing_identity_are_errors():
    dependency = {"name": "example-package", "version": "1.0.0", "vulns": [
        {"id": "GHSA-aaaa-bbbb-cccc", "fix_versions": []},
        {"id": "GHSA-aaaa-bbbb-cccc", "fix_versions": ["2.0.0"]}]}
    with pytest.raises(AuditUnreadable, match="contradicts"):
        python_findings({"dependencies": [dependency]})
    with pytest.raises(AuditUnreadable, match="identity"):
        python_findings({"dependencies": [{"name": "example-package", "vulns": []}]})


@pytest.mark.parametrize(("target", "value"), [
    ("advisories", []), ("advisories", ["same", "same"]), ("dependency_paths", [42]),
    ("dependency_paths", ["node_modules/z", "node_modules/a"]),
    ("package", ""), ("version", None), ("ecosystem", "unknown"), ("severity", "unknown"), ("severity", "invalid"),
    ("fingerprint", "sha256:" + "f" * 64),
    ("fixed_versions", None), ("dependency_scope", "unreachable"),
])
def test_finding_identity_cannot_be_forged(target, value):
    checks, approval = evidence()
    checks[0]["dependency_audit"]["findings"][0][target] = value
    with pytest.raises(RiskRefused):
        decide(checks, [approval])


@pytest.mark.parametrize("damage", ["empty", "duplicate-finding", "foreign-lock", "foreign-ecosystem", "bad-lock", "missing-locks", "missing-findings", "applicability", "duplicate-acceptance", "stale-acceptance"])
def test_incomplete_or_ambiguous_evidence_never_grants_permission(damage):
    checks, approval = evidence()
    audit = checks[0]["dependency_audit"]
    acceptances = [approval]
    if damage == "empty":
        checks = []
    elif damage == "duplicate-finding":
        audit["findings"].append(deepcopy(audit["findings"][0]))
    elif damage == "foreign-lock":
        audit["locks"] = {"other.lock": "sha256:" + "b" * 64}
    elif damage == "foreign-ecosystem":
        checks[0]["id"], checks[1]["id"] = checks[1]["id"], checks[0]["id"]
    elif damage == "bad-lock":
        audit["locks"]["frontend/package-lock.json"] = "invalid"
    elif damage == "missing-locks":
        del audit["locks"]
    elif damage == "missing-findings":
        del audit["findings"]
    elif damage == "applicability":
        checks[0]["applicable"] = False
    elif damage == "duplicate-acceptance":
        acceptances.append(deepcopy(approval))
    else:
        approval = deepcopy(approval)
        approval["finding"]["dependency_scope"] = "runtime"
        acceptances = [approval]
    with pytest.raises(RiskRefused):
        decide(checks, acceptances)


@pytest.mark.parametrize("damage", [None, "signature", "nonce", "expired", "revoked", "wrong-purpose", "unavailable", "no-records",
                                    "no-acceptance", "no-issue-time", "local-time", "undefined-field"])
def test_authority_verifies_fresh_signed_evidence(tmp_path, monkeypatch, damage):
    import json
    import subprocess
    import sys
    from datetime import timedelta, timezone

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from terp.cli import risk_authority
    from terp.cli.release import dsse

    key = Ed25519PrivateKey.generate()
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    policy = tmp_path / "protected.json"
    policy.write_text(json.dumps({"project_id": "example-project", "environment": "production",
                                  "provider": [sys.executable, "provider.py"], "public_keys": [pem]}))
    checks, approval = evidence()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(risk_authority, "datetime", Clock)

    def provider(argv, **kwargs):
        request = json.loads(kwargs["input"])
        record = deepcopy(approval)
        if damage == "revoked":
            record["revoked_at"] = NOW.isoformat()
        if damage == "undefined-field":
            record["scope"] = "every environment"
        response = {**request, "issued_at": NOW.isoformat(), "expires_at": (NOW + timedelta(minutes=5)).isoformat(),
                    "acceptances": [record]}
        if damage == "nonce":
            response["nonce"] = "wrong"
        if damage == "expired":
            response["expires_at"] = NOW.isoformat()
        if damage == "no-records":
            response.pop("acceptances")
        if damage == "no-acceptance":
            response["acceptances"] = []
        if damage == "no-issue-time":
            response.pop("issued_at")
        if damage == "local-time":
            response["issued_at"] = NOW.astimezone(timezone(timedelta(hours=1))).isoformat()
        purpose = dsse.PAYLOAD_TYPE if damage == "wrong-purpose" else risk_authority.PAYLOAD_TYPE
        payload = json.dumps(response).encode()
        signer = Ed25519PrivateKey.generate() if damage == "signature" else key
        envelope = dsse.envelope(payload, [dsse.sign_with_key(signer, payload, payload_type=purpose)], payload_type=purpose)
        return subprocess.CompletedProcess(argv, 1 if damage == "unavailable" else 0, json.dumps(envelope).encode(), b"")

    monkeypatch.setattr(risk_authority.subprocess, "run", provider)
    # A refusal of the reader reaches the caller in the reader's own words, which name the fix.
    said = {"revoked": "was revoked", "no-issue-time": "is missing", "local-time": "must be UTC",
            "undefined-field": '"scope", which the dependency-risk-acceptance contract does not define'}
    if damage:
        with pytest.raises(RiskRefused, match=said.get(damage)):
            risk_authority.authorize(checks, policy_file=str(policy), commit=COMMIT, checkout=tmp_path / "app")
    else:
        result = risk_authority.authorize(checks, policy_file=str(policy), commit=COMMIT, checkout=tmp_path / "app")
        assert result["decision"]["allowed"] and result["decision"]["status"] == "accepted"


@pytest.mark.parametrize("damage", [None, "unknown-project", "relative-policy", "wrong-project", "wrong-environment"])
def test_protected_verifier_selects_policy_from_its_own_map(tmp_path, monkeypatch, capsys, damage):
    import io
    import json
    import sys

    from terp.cli import risk_authority

    policy = tmp_path / "policy.json"
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"example-project": {"production": "relative.json" if damage == "relative-policy" else str(policy)}}))
    request = {"project_id": "unknown" if damage == "unknown-project" else "example-project", "environment": "production", "commit": COMMIT, "checks": []}
    monkeypatch.setattr(sys, "argv", ["verifier", "--policy-map", str(mapping)])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(request).encode())))
    result = {"project_id": "other" if damage == "wrong-project" else "example-project",
              "environment": "other" if damage == "wrong-environment" else "production"}
    monkeypatch.setattr(risk_authority, "authorize", lambda *args, **kwargs: result)
    assert risk_authority.main() == (1 if damage else 0)
    output = capsys.readouterr()
    assert ("refused" in output.err) == bool(damage)


@pytest.mark.parametrize("damage", ["in-checkout", "unknown-field", "relative-provider", "empty-keys"])
def test_untrusted_authority_configuration_is_refused_before_execution(tmp_path, damage):
    import json
    import sys

    from terp.cli.risk_authority import authorize

    policy = tmp_path / "policy.json"
    config = {"project_id": "example-project", "environment": "production", "provider": [sys.executable], "public_keys": ["unused"]}
    if damage == "unknown-field":
        config["ignore"] = True
    elif damage == "relative-provider":
        config["provider"] = ["python"]
    elif damage == "empty-keys":
        config["public_keys"] = []
    policy.write_text(json.dumps(config))
    with pytest.raises(RiskRefused):
        authorize([], policy_file=str(policy), commit=COMMIT, checkout=tmp_path if damage == "in-checkout" else tmp_path / "app")


@pytest.mark.parametrize("damage", ["identity", "check-verdict", "conflicting-locks", "commit"])
def test_missing_identity_and_conflicting_evidence_are_refused(damage):
    checks, approval = evidence()
    if damage == "identity":
        del checks[0]["dependency_audit"]["findings"][0]["package"]
    elif damage == "check-verdict":
        checks[2]["ok"] = 1
    elif damage == "conflicting-locks":
        checks[1]["dependency_audit"]["locks"]["frontend/package-lock.json"] = "sha256:" + "d" * 64
    with pytest.raises(RiskRefused):
        evaluate(checks, [approval], project="example-project", commit="branch" if damage == "commit" else COMMIT,
                 environment="production", now=NOW)


@pytest.mark.parametrize("damage", ["via", "empty-nodes", "bad-nodes", "version", "contradictory"])
def test_npm_ambiguous_or_missing_identity_blocks_the_entire_scan(damage):
    report, lock = npm_report()
    item = report["vulnerabilities"]["example-package"]
    if damage == "via":
        item["via"] = []
    elif damage == "empty-nodes":
        item["nodes"] = []
    elif damage == "bad-nodes":
        item["nodes"] = [None]
    elif damage == "version":
        lock["packages"]["node_modules/example-package"] = {}
    else:
        item["via"].append({**item["via"][0], "severity": "critical"})
    with pytest.raises(AuditUnreadable):
        npm_findings(report, lock, "frontend/package-lock.json")


@pytest.mark.parametrize("report", [{"fixes": ["modified"]}, {}, {"dependencies": [{"name": "example"}]}])
def test_python_audit_must_be_complete_and_read_only(report):
    with pytest.raises(AuditUnreadable):
        python_findings(report)


def test_verifier_module_entry_refuses_invalid_input(tmp_path, monkeypatch):
    import io
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["verifier", "--policy-map", str(tmp_path / "absent.json")])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"{}")))
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("terp.cli.risk_authority", run_name="__main__")
    assert exc.value.code == 1


# --------------------------------------------------------------------------- #
# the two contracts, as the pinned terp-spec states them
# --------------------------------------------------------------------------- #
def _contract(name):
    root = spec_dir()
    return (json.loads((root / f"{name}.schema.json").read_text(encoding="utf-8")),
            json.loads((root / f"{name}.fixtures.json").read_text(encoding="utf-8")))


AUDIT_SCHEMA, AUDIT_CASES = _contract("dependency-audit")
ACCEPTANCE_SCHEMA, ACCEPTANCE_CASES = _contract("dependency-risk-acceptance")
VALID_AUDIT = next(case["document"] for case in AUDIT_CASES if case["valid"])
VALID_ACCEPTANCE = next(case["document"] for case in ACCEPTANCE_CASES if case["valid"])
SCANNED = datetime.fromisoformat(VALID_AUDIT["scanned_at"])
APPROVED = datetime.fromisoformat(VALID_ACCEPTANCE["approved_at"])


def _read_alone(record):
    """``valid_acceptance`` over *record* in the context the record names itself: its project,
    commit, first environment and locks, at the valid fixture's approval time. Nothing in that
    context can refuse the record, so a refusal is the contract's."""
    named = record if isinstance(record, dict) else {}
    environments = named.get("environments")
    environment = environments[0] if isinstance(environments, list) and environments else "production"
    return valid_acceptance(record, project=named.get("project_id"), commit=named.get("commit"),
                            environment=environment, locks=named.get("locks"), now=APPROVED)


def _release_with(acceptance):
    """The release whose audit found the finding the valid fixture accepts, decided with *acceptance*."""
    def scan(locks, findings):
        return {"version": 1, "complete": True, "scanned_at": VALID_ACCEPTANCE["approved_at"],
                "locks": locks, "findings": findings}
    checks = [
        {"id": "dependency-audit-npm", "ok": False, "applicable": True,
         "dependency_audit": scan(dict(VALID_ACCEPTANCE["locks"]), [deepcopy(VALID_ACCEPTANCE["finding"])])},
        {"id": "dependency-audit-python", "ok": True, "applicable": False, "dependency_audit": scan({}, [])},
    ]
    return evaluate(checks, [acceptance], project=VALID_ACCEPTANCE["project_id"], commit=VALID_ACCEPTANCE["commit"],
                    environment=VALID_ACCEPTANCE["environments"][0], now=APPROVED)


@pytest.mark.parametrize("case", ACCEPTANCE_CASES, ids=[case["name"] for case in ACCEPTANCE_CASES])
def test_every_acceptance_the_contract_refuses_is_refused_on_its_own(case):
    record = deepcopy(case["document"])
    if case["valid"]:
        assert _read_alone(record) == record["finding"]["fingerprint"]
    else:
        with pytest.raises(RiskRefused):
            _read_alone(record)


@pytest.mark.parametrize("case", ACCEPTANCE_CASES, ids=[case["name"] for case in ACCEPTANCE_CASES])
def test_only_the_contract_s_valid_acceptance_admits_the_release_it_names(case):
    if case["valid"]:
        decision = _release_with(deepcopy(case["document"]))
        assert decision["status"] == "accepted" and decision["acceptance_ids"] == [case["document"]["id"]]
    else:
        with pytest.raises(RiskRefused):
            _release_with(deepcopy(case["document"]))


@pytest.mark.parametrize("case", AUDIT_CASES, ids=[case["name"] for case in AUDIT_CASES])
def test_every_audit_the_contract_refuses_is_refused(case):
    document = deepcopy(case["document"])
    if case["valid"]:
        locks, findings = audit_evidence(document, now=SCANNED)
        assert locks == document["locks"]
        assert findings == {item["fingerprint"]: item for item in document["findings"]}
    else:
        with pytest.raises(RiskRefused):
            audit_evidence(document, now=SCANNED)


@pytest.mark.parametrize("field", ["id", "project_id", "reason", "approved_by", "environments", "evidence"])
@pytest.mark.parametrize("blank", [" ", "\t", "\x00", "\x7f", "\u00a0", "\u2007", "\u3000", "\ufeff", " \ufeff\u00a0"])
def test_an_authority_field_the_contract_calls_blank_is_refused(field, blank):
    """terp-spec 0.50.0 asks for one character outside its blank class in every field that
    says who decided, for what, why and on what evidence. A byte order mark or a NUL is no
    whitespace to ``str.strip``, and no more an approver for that."""
    record = deepcopy(VALID_ACCEPTANCE)
    record[field] = [blank] if isinstance(record[field], list) else blank
    with pytest.raises(RiskRefused):
        _read_alone(record)


@pytest.mark.parametrize(("field", "value"), [
    ("approved_by", "o"), ("reason", " Reviewed. "), ("evidence", ["\ufeffreview-1"]),
])
def test_a_field_with_one_character_of_content_is_not_blank(field, value):
    record = deepcopy(VALID_ACCEPTANCE)
    record[field] = value
    assert _read_alone(record) == record["finding"]["fingerprint"]


_ODD_INSTANTS = ["2026-11-18T24:00:00Z", "2026-11-17T24:00:00Z", "2026-02-30T12:00:00Z", "2026-11-18T12:61:00Z",
                 "2026-11-18T12:00Z", "2026-11-18 12:00:00Z", "2026-11-18T12:00:00.1234567Z", "2026-11-18T12:00:00-00:00",
                 "20261118T120000Z", "2026-11-18T12Z", "2026-11-18T12:00:00Z\n", "2026-11-18T12:00:00+0000",
                 "\u0662\u0660\u0662\u0666-11-18T12:00:00Z"]


@pytest.mark.parametrize("damage", ["lock-newline", "commit-newline", "no-lock", "lock-not-a-digest", "unknown-field",
                                    "finding-field", "no-revocation-state", "revocation-too-long", "revocation-not-text",
                                    *_ODD_INSTANTS])
def test_an_acceptance_is_read_only_in_the_contract_s_own_form(damage):
    record = deepcopy(VALID_ACCEPTANCE)
    lock = next(iter(record["locks"]))
    if damage == "lock-newline":
        record["locks"][lock] += "\n"
    elif damage == "commit-newline":
        record["commit"] += "\n"
    elif damage == "no-lock":
        record["locks"] = {}
    elif damage == "lock-not-a-digest":
        record["locks"][lock] = record["locks"][lock].upper()
    elif damage == "unknown-field":
        record["scope"] = "all"
    elif damage == "finding-field":
        record["finding"]["note"] = "ignore"
    elif damage == "no-revocation-state":
        del record["revoked_at"]
    elif damage == "revocation-too-long":
        record["revoked_at"] = "r" * (dependency_risk.MAX_REVOCATION + 1)
    elif damage == "revocation-not-text":
        record["revoked_at"] = None
    else:
        record["approved_at"] = damage
    with pytest.raises(RiskRefused):
        _read_alone(record)


@pytest.mark.parametrize("damage", ["lock-newline", "unknown-field", "finding-field", "no-scan-time", "locks-not-a-map",
                                    "findings-not-a-list", "too-many-findings", *_ODD_INSTANTS])
def test_an_audit_is_read_only_in_the_contract_s_own_form(damage):
    document = deepcopy(VALID_AUDIT)
    if damage == "lock-newline":
        document["locks"][next(iter(document["locks"]))] += "\n"
    elif damage == "unknown-field":
        document["tool"] = "npm"
    elif damage == "finding-field":
        document["findings"][0]["exploitable"] = False
    elif damage == "no-scan-time":
        del document["scanned_at"]
    elif damage == "locks-not-a-map":
        document["locks"] = list(document["locks"].items())
    elif damage == "findings-not-a-list":
        document["findings"] = {"0": document["findings"][0]}
    elif damage == "too-many-findings":
        document["findings"] = [None] * (MAX_ITEMS + 1)
    else:
        document["scanned_at"] = damage
    with pytest.raises(RiskRefused):
        audit_evidence(document, now=SCANNED)


@pytest.mark.parametrize("damage", ["undefined-field", "blank-approver", "version-2", "no-lock", "odd-time",
                                    "revocation-too-long", "revocation-not-text"])
def test_a_superseded_acceptance_is_held_to_the_contract_too(damage):
    """The release reads the latest decision for each finding, and the authority returns the
    ones before it as well: each of those is a document of the contract too, or the answer is
    refused whole. Only its lifetime, its revocation and the release it names are left to the
    decision that replaces it."""
    checks, renewal = evidence()
    older = deepcopy(renewal)
    older.update(id="older-approval", approved_at="2026-11-16T12:00:00Z", expires_at="2026-11-17T12:00:00Z")
    assert decide(checks, [older, renewal])["acceptance_ids"] == [renewal["id"]]
    if damage == "undefined-field":
        older["scope"] = "all"
    elif damage == "blank-approver":
        older["approved_by"] = chr(0xFEFF)
    elif damage == "version-2":
        older["version"] = 2
    elif damage == "no-lock":
        older["locks"] = {}
    elif damage == "revocation-too-long":
        older["revoked_at"] = "r" * (dependency_risk.MAX_REVOCATION + 1)
    elif damage == "revocation-not-text":
        older["revoked_at"] = None
    else:
        older["expires_at"] = "2026-11-17T12:00Z"
    with pytest.raises(RiskRefused):
        decide(checks, [older, renewal])


@pytest.mark.parametrize(("field", "size", "read"), [
    ("reason", MAX_TEXT, True), ("reason", MAX_TEXT + 1, False), ("approved_by", MAX_TEXT + 1, False),
    ("project_id", MAX_TEXT + 1, False), ("evidence", MAX_ITEMS, True), ("evidence", MAX_ITEMS + 1, False),
    ("environments", MAX_ITEMS + 1, False),
])
def test_an_acceptance_is_read_within_the_contract_s_limits(field, size, read):
    record = deepcopy(VALID_ACCEPTANCE)
    if isinstance(record[field], list):
        record[field] = [*record[field], *(f"item-{index}" for index in range(size - len(record[field])))]
    else:
        record[field] = "r" * size
    if read:
        assert _read_alone(record) == record["finding"]["fingerprint"]
    else:
        with pytest.raises(RiskRefused):
            _read_alone(record)


@pytest.mark.parametrize(("field", "value", "read"), [
    ("package", "p" * MAX_TEXT, True), ("package", "p" * (MAX_TEXT + 1), False),
    ("version", "v" * (MAX_TEXT + 1), False), ("lockfile", "l" * (MAX_TEXT + 1), False),
    ("advisories", ["a" * (MAX_TEXT + 1)], False), ("fixed_versions", ["f" * (MAX_TEXT + 1)], False),
    ("dependency_paths", [f"node_modules/p{index:05d}" for index in range(MAX_ITEMS)], True),
    ("dependency_paths", [f"node_modules/p{index:05d}" for index in range(MAX_ITEMS + 1)], False),
])
def test_a_finding_is_read_within_the_contract_s_limits(field, value, read):
    """The fingerprint is recomputed over the changed identity, so the limit is all that can refuse."""
    from terp.cli.audit_findings import digest

    document = deepcopy(VALID_AUDIT)
    item = document["findings"][0]
    item[field] = value
    if field == "lockfile":
        document["locks"] = {value: next(iter(document["locks"].values()))}
    item["fingerprint"] = digest({key: item[key] for key in dependency_risk.IDENTITY})
    if read:
        assert audit_evidence(document, now=SCANNED)[1] == {item["fingerprint"]: item}
    else:
        with pytest.raises(RiskRefused):
            audit_evidence(document, now=SCANNED)


def _keyword(schema, keyword):
    """Every value *keyword* takes anywhere in *schema*."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == keyword:
                yield value
            else:
                yield from _keyword(value, keyword)
    elif isinstance(schema, list):
        for value in schema:
            yield from _keyword(value, keyword)


def test_the_reader_carries_the_contracts_own_patterns_fields_and_limits():
    """The reader cannot import terp-spec, a development dependency, so it carries the
    schemas' patterns and limits as constants, and their closed field sets. Here those are the
    pinned release's own: a pattern or a limit the release uses and the reader does not carry,
    or the other way round, fails. Where the reader applies each is held by the test below."""
    schemas = (AUDIT_SCHEMA, ACCEPTANCE_SCHEMA)
    carried = (dependency_risk.CONTENT, dependency_risk.DIGEST, dependency_risk.COMMIT, dependency_risk.INSTANT)
    assert {pattern for schema in schemas for pattern in _keyword(schema, "pattern")} == {
        expression.pattern for expression in carried}
    assert {limit for schema in schemas for limit in _keyword(schema, "maxLength")} == {
        MAX_TEXT, dependency_risk.MAX_REVOCATION}
    assert ACCEPTANCE_SCHEMA["properties"]["revoked_at"]["maxLength"] == dependency_risk.MAX_REVOCATION
    assert {limit for schema in schemas for limit in _keyword(schema, "maxItems")} == {MAX_ITEMS}
    item = AUDIT_SCHEMA["properties"]["findings"]["items"]
    assert ACCEPTANCE_SCHEMA["properties"]["finding"] == item
    for fields, closed in ((dependency_risk.AUDIT_FIELDS, AUDIT_SCHEMA), (dependency_risk.FINDING_FIELDS, item),
                           (dependency_risk.ACCEPTANCE_FIELDS, ACCEPTANCE_SCHEMA)):
        assert closed["additionalProperties"] is False
        assert fields == set(closed["required"]) == set(closed["properties"])


# --------------------------------------------------------------------------- #
# every rule of the pinned schemas, at every field
# --------------------------------------------------------------------------- #
def _candidates(value, limits):
    """Values to put where *value* stands: one of each other JSON type, the strings that break a
    pattern this reader knows of, and the lengths and counts just past each *limits* the schema
    sets. Which of them a field may not hold is for the pinned schema to say."""
    texts = ["", " ", "\t", chr(0xA0), chr(0x3000), chr(0xFEFF), "\x00", "x", "X", "-", "0"]
    if isinstance(value, str):
        texts += [value + "\n", value + " ", value.upper(), value[:-1]]
    texts += ["x" * (length + 1) for length in limits["maxLength"]]
    texts += ["x" * (length - 1) for length in limits["minLength"] if length > 1]
    lists = [[], [None], [""], [" "], [chr(0xFEFF)]]
    if isinstance(value, list) and value:
        lists.append([*value, value[0]])
    lists += [[f"entry-{index:05d}" for index in range(count + 1)] for count in limits["maxItems"]]
    return [None, True, 2, 1.5, {}, *texts, *lists]


def _changes(node, limits, path=()):
    """``(path, how, value)`` for one change at each place of *node*: each value replaced by each
    candidate, each field left out, and a field added to each object. A list is entered at its
    first entry."""
    if isinstance(node, dict):
        for key in list(node):
            yield (*path, key), "without", None
            yield from _changes(node[key], limits, (*path, key))
        yield (*path, "undefined-field"), "as", "x"
    elif isinstance(node, list) and node:
        yield from _changes(node[0], limits, (*path, 0))
    for value in _candidates(node, limits):
        yield path, "as", value


def _changed(document, path, how, value):
    """A copy of *document* with one change, and the finding it touches made whole again: its
    fingerprint recomputed, and an audit's lock keyed by its lockfile, so that what the change
    broke is all that can refuse it."""
    if not path:
        return value
    copy = deepcopy(document)
    holder = copy
    for step in path[:-1]:
        holder = holder[step]
    if how == "without":
        del holder[path[-1]]
    else:
        holder[path[-1]] = value
    inside = copy.get("finding") if path[0] == "finding" else copy["findings"][0] if path[:2] == ("findings", 0) else None
    if isinstance(inside, dict) and path[-1] != "fingerprint" and all(key in inside for key in dependency_risk.IDENTITY):
        from terp.cli.audit_findings import digest

        inside["fingerprint"] = digest({key: inside[key] for key in dependency_risk.IDENTITY})
        if path[0] == "findings" and isinstance(inside["lockfile"], str) and inside["lockfile"]:
            copy["locks"] = {inside["lockfile"]: next(iter(VALID_AUDIT["locks"].values()))}
    return copy


def _places(node, path=()):
    """Every place in *node*, as ``_changes`` names them."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield (*path, key)
            yield from _places(value, (*path, key))
    elif isinstance(node, list) and node:
        yield (*path, 0)
        yield from _places(node[0], (*path, 0))


@pytest.mark.parametrize("contract", ["dependency-audit", "dependency-risk-acceptance"])
def test_every_rule_of_the_pinned_schema_is_held_at_every_field(contract):
    """A document the pinned schema refuses is one this reader refuses, at whatever field.

    The valid fixture is changed one place at a time, and the pinned schema, by a full Draft
    2020-12 validator, says which changes break it: a pattern, a length or a count, an enum or
    a const, a type, a required field left out or a field it does not define. Each of those the
    reader must refuse, read alone so that no context can do it instead. A later release that
    puts a rule on another field fails here until the reader applies it there, as long as one of
    the values tried breaks it (``_candidates``)."""
    from jsonschema import Draft202012Validator

    if contract == "dependency-audit":
        schema, valid = AUDIT_SCHEMA, VALID_AUDIT

        def read(document):
            return audit_evidence(document, now=SCANNED)
    else:
        schema, valid, read = ACCEPTANCE_SCHEMA, VALID_ACCEPTANCE, _read_alone
    validator = Draft202012Validator(schema)
    limits = {keyword: set(_keyword(schema, keyword)) for keyword in ("maxLength", "minLength", "maxItems")}
    broken = []
    for path, how, value in _changes(valid, limits):
        document = _changed(valid, path, how, value)
        if any(True for _ in validator.iter_errors(document)):
            broken.append((".".join(map(str, path)) or "$", how, ascii(value)[:48], document))
    # Every place of the valid document was broken at least once, so the walk reached each.
    assert {place for place, _how, _value, _document in broken} >= {
        ".".join(map(str, path)) for path in _places(valid)}
    admitted = []
    for place, how, value, document in broken:
        try:
            read(document)
        except RiskRefused:
            continue
        admitted.append(f"{place} {how} {value}")
    assert admitted == []


def _findings(count):
    """*count* distinct findings of the valid audit's lock, each whole and the contract's."""
    from terp.cli.audit_findings import digest

    template = VALID_AUDIT["findings"][0]
    found = []
    for index in range(count):
        item = {**template, "package": f"example-package-{index:05d}",
                "dependency_paths": [f"node_modules/example-package-{index:05d}"]}
        item["fingerprint"] = digest({key: item[key] for key in dependency_risk.IDENTITY})
        found.append(item)
    return found


def test_an_audit_lists_at_most_the_findings_its_contract_holds():
    """Every one of these findings is whole, distinct and of the audit's own lock: only the
    count can refuse the audit, and the pinned schema refuses it too."""
    from jsonschema import Draft202012Validator

    document = {**deepcopy(VALID_AUDIT), "findings": _findings(MAX_ITEMS)}
    assert len(audit_evidence(document, now=SCANNED)[1]) == MAX_ITEMS
    document["findings"] = _findings(MAX_ITEMS + 1)
    assert any(True for _ in Draft202012Validator(AUDIT_SCHEMA).iter_errors(document))
    with pytest.raises(RiskRefused, match=f"more than {MAX_ITEMS} findings"):
        audit_evidence(document, now=SCANNED)


def test_a_finding_belongs_to_a_lock_its_audit_lists():
    document = deepcopy(VALID_AUDIT)
    document["locks"] = {"site/package-lock.json": next(iter(document["locks"].values()))}
    with pytest.raises(RiskRefused, match="does not belong to this scan"):
        audit_evidence(document, now=SCANNED)


@pytest.mark.parametrize(("field", "value", "said"), [
    ("reason", "r" * (MAX_TEXT + 1), f'acceptance "acceptance-1": reason is longer than {MAX_TEXT} characters'),
    ("approved_by", " ", 'approved_by holds only characters the contract counts as blank'),
    ("id", chr(0xFEFF), "an acceptance's id holds only characters the contract counts as blank"),
    ("evidence", [f"review-{index}" for index in range(MAX_ITEMS + 1)], f"evidence lists more than {MAX_ITEMS} entries"),
    ("evidence", ["review-1", "review-1"], "evidence lists an entry more than once"),
    ("environments", ["production", "production"], "environments lists an entry more than once"),
    ("environments", [], "environments is empty"),
    ("approved_at", "2026-11-18T12:00Z", 'acceptance "acceptance-1": approved_at must be UTC'),
    ("expires_at", "2026-02-30T12:00:00Z", "expires_at is not a date and time"),
    ("revoked_at", None, "revoked_at is not a string of at most"),
    ("commit", "c" * 39, "commit is not a whole commit id"),
])
def test_a_refusal_names_the_field_and_the_rule_it_broke(field, value, said):
    """The refusal reaches the operator, so it says which field broke which rule, of which
    acceptance where the acceptance has an id to name it by."""
    record = deepcopy(VALID_ACCEPTANCE)
    record[field] = value
    with pytest.raises(RiskRefused) as refused:
        _read_alone(record)
    assert said in str(refused.value)


@pytest.mark.parametrize(("field", "value", "said"), [
    ("advisories", ["a" * (MAX_TEXT + 1)], f"a finding's advisories has an entry that is longer than {MAX_TEXT} characters"),
    ("package", "", "a finding's package is empty"),
    ("fixed_versions", ["2.0.0", "1.0.0"], "a finding's fixed_versions is not sorted"),
    ("ecosystem", "maven", "a finding's ecosystem is not npm or pypi"),
])
def test_a_finding_s_refusal_names_the_field_and_the_rule_it_broke(field, value, said):
    from terp.cli.audit_findings import digest

    document = deepcopy(VALID_AUDIT)
    item = document["findings"][0]
    item[field] = value
    item["fingerprint"] = digest({key: item[key] for key in dependency_risk.IDENTITY})
    with pytest.raises(RiskRefused) as refused:
        audit_evidence(document, now=SCANNED)
    assert said in str(refused.value)
    document = deepcopy(VALID_AUDIT)
    document["scanned_at"] = "2026-11-18 12:00:00Z"
    with pytest.raises(RiskRefused, match="a dependency scan's scanned_at must be UTC"):
        audit_evidence(document, now=SCANNED)
