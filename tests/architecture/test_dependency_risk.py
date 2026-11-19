"""Risk acceptance cannot hide scan errors or unrelated release failures."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from terp.cli.audit_findings import AuditUnreadable, finding, npm_findings, python_findings
from terp.cli.dependency_risk import RiskRefused, evaluate

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
    ("locks", {}), ("approved_by", ""), ("reason", " "), ("evidence", []),
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


@pytest.mark.parametrize("damage", [None, "signature", "nonce", "expired", "revoked", "wrong-purpose", "unavailable", "no-records", "no-acceptance"])
def test_authority_verifies_fresh_signed_evidence(tmp_path, monkeypatch, damage):
    import json
    import subprocess
    import sys
    from datetime import timedelta

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
        purpose = dsse.PAYLOAD_TYPE if damage == "wrong-purpose" else risk_authority.PAYLOAD_TYPE
        payload = json.dumps(response).encode()
        signer = Ed25519PrivateKey.generate() if damage == "signature" else key
        envelope = dsse.envelope(payload, [dsse.sign_with_key(signer, payload, payload_type=purpose)], payload_type=purpose)
        return subprocess.CompletedProcess(argv, 1 if damage == "unavailable" else 0, json.dumps(envelope).encode(), b"")

    monkeypatch.setattr(risk_authority.subprocess, "run", provider)
    if damage:
        with pytest.raises(RiskRefused):
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
