"""Scanner failures cannot be confused with findings eligible for human review."""

import json
import subprocess
from pathlib import Path

import pytest

from terp.cli import verify
from terp.cli.dependency_scan import scan_dependencies

LOCK = 'version = 1\n[[package]]\nname = "example-package"\nversion = "1.0.0"\nsource = {registry = "https://pypi.org/simple"}\n'


def _audit_problems(audit):
    """What the pinned terp-spec's ``dependency-audit`` schema refuses in *audit*, by a full
    Draft 2020-12 validator: every document a scan writes, complete or not, is the contract's."""
    from jsonschema import Draft202012Validator
    from terp_spec import spec_dir

    schema = json.loads((spec_dir() / "dependency-audit.schema.json").read_text(encoding="utf-8"))
    return [error.message for error in Draft202012Validator(schema).iter_errors(audit)]


@pytest.mark.parametrize("mode", ["clean", "finding", "crash", "malformed", "contradiction", "changed-lock", "missing-lock"])
def test_python_scanner_evidence(tmp_path, monkeypatch, mode):
    lock = tmp_path / "uv.lock"
    if mode != "missing-lock":
        lock.write_text(LOCK)
    report = {"dependencies": [{"name": "example-package", "version": "1.0.0", "vulns": []}]}
    if mode == "finding":
        report["dependencies"][0]["vulns"] = [{"id": "PYSEC-2026-1", "aliases": [], "fix_versions": []}]

    def scanner(*args):
        argv = args[0]
        assert "--no-deps" in argv and "--disable-pip" in argv and "tool" in argv
        assert Path(argv[-1]).read_text() == "example-package==1.0.0\n"
        if mode == "changed-lock":
            lock.write_text("version = 2\n")
        code = 2 if mode == "crash" else 1 if mode in {"finding", "contradiction"} else 0
        return subprocess.CompletedProcess(args[0], code, "bad json" if mode == "malformed" else json.dumps(report), "Found vulnerabilities" if mode == "finding" else "No known vulnerabilities found")

    monkeypatch.setattr(verify, "_run_argv", scanner)
    code, _output, extra = scan_dependencies(tmp_path, "pypi")
    audit = extra["dependency_audit"]
    assert _audit_problems(audit) == []
    if mode in {"clean", "finding"}:
        assert audit["complete"] and code == (mode == "finding")
        assert "uv.lock" in audit["locks"]
    else:
        assert code == 2 and audit["complete"] is False


@pytest.mark.parametrize("mode", ["none", "renamed", "symlink", "uninstalled", "root-project", "third-party-skip"])
def test_scan_scope_and_installation_errors(tmp_path, monkeypatch, mode):
    from pathlib import Path

    ecosystem = "npm"
    if mode == "renamed":
        web = tmp_path / "web"
        web.mkdir()
        (web / "package.json").write_text(json.dumps({"dependencies": {"@terpjs/react-core": "1.0.0"}}))
    elif mode == "uninstalled":
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        (frontend / "package.json").write_text('{"dependencies":{"example-package":"1.0.0"}}')
        (frontend / "package-lock.json").write_text('{"packages":{}}')
    elif mode != "none":
        ecosystem = "pypi"
        (tmp_path / "uv.lock").write_text(LOCK + '\n[[package]]\nname = "example-app"\nsource = { editable = "." }\n')
        if mode == "symlink":
            monkeypatch.setattr(Path, "is_symlink", lambda _: True)
        else:
            report = {"dependencies": [{"name": "example-package", "version": "1.0.0", "vulns": []}]}
            if mode == "third-party-skip":
                report["dependencies"][0]["skip_reason"] = "not found"
            monkeypatch.setattr(verify, "_run_argv", lambda *args: subprocess.CompletedProcess(args[0], 0, json.dumps(report), "No known vulnerabilities found"))
    code, output, extra = scan_dependencies(tmp_path, ecosystem)
    assert _audit_problems(extra["dependency_audit"]) == []
    assert extra["dependency_audit"]["complete"] == (mode in {"none", "root-project"})
    assert code == (0 if mode in {"none", "root-project"} else 2)
    if mode == "none":
        assert verify.NOT_APPLICABLE in output


def test_python_scan_reaches_the_public_verify_envelope(tmp_path, monkeypatch, capsys):
    from terp.cli import main

    (tmp_path / "pyproject.toml").write_text('[project]\nname="example-app"\nversion="1.0.0"\n')
    (tmp_path / "uv.lock").write_text(LOCK)
    monkeypatch.setattr(verify, "_run_argv", lambda *args: subprocess.CompletedProcess(args[0], 0,
        '{"dependencies":[{"name":"example-package","version":"1.0.0","vulns":[]}]}', "No known vulnerabilities found"))
    with pytest.raises(SystemExit) as exc:
        main(["verify", "--profile", "release", "--root", str(tmp_path), "--only", "dependency-audit-python", "--format", "json"])
    assert exc.value.code == 0
    check, = json.loads(capsys.readouterr().out)["checks"]
    assert check["dependency_audit"]["complete"] and check["ok"]


@pytest.mark.parametrize("damage", ["missing-inventory", "bad-entry", "path-source", "bad-name", "bad-version", "omitted", "wrong-version", "extra-package"])
def test_python_audit_refuses_unverifiable_or_incomplete_inventory(tmp_path, monkeypatch, damage):
    locked = LOCK
    if damage == "missing-inventory":
        locked = "version = 1\n"
    elif damage == "bad-entry":
        locked = "package = [1]\n"
    elif damage == "path-source":
        locked = LOCK.replace('registry = "https://pypi.org/simple"', 'editable = "../package"')
    elif damage == "bad-name":
        locked = LOCK.replace('name = "example-package"', 'name = "--option"')
    elif damage == "bad-version":
        locked = LOCK.replace('version = "1.0.0"', 'version = "1.0.0; extra"')
    report = {"dependencies": [{"name": "example-package", "version": "1.0.0", "vulns": []}]}
    if damage == "omitted":
        report["dependencies"] = []
    elif damage == "wrong-version":
        report["dependencies"][0]["version"] = "2.0.0"
    elif damage == "extra-package":
        report["dependencies"].append({"name": "scanner-dependency", "version": "2.0.0", "vulns": []})
    (tmp_path / "uv.lock").write_text(locked)
    monkeypatch.setattr(verify, "_run_argv", lambda *args: subprocess.CompletedProcess(args[0], 0, json.dumps(report), ""))
    code, _, extra = scan_dependencies(tmp_path, "pypi")
    assert code == 2 and not extra["dependency_audit"]["complete"]


def test_python_audit_covers_each_locked_platform_version(tmp_path, monkeypatch):
    (tmp_path / "uv.lock").write_text(LOCK + LOCK.split("\n", 1)[1].replace('"1.0.0"', '"2.0.0"'))
    asked = []

    def scanner(argv, root):
        name, version = Path(argv[-1]).read_text().strip().split("==")
        asked.append(version)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"dependencies": [{"name": name, "version": version, "vulns": []}]}), "")

    monkeypatch.setattr(verify, "_run_argv", scanner)
    code, _, extra = scan_dependencies(tmp_path, "pypi")
    assert code == 0 and extra["dependency_audit"]["complete"] and asked == ["1.0.0", "2.0.0"]


def test_root_only_python_lock_has_no_registry_dependencies(tmp_path, monkeypatch):
    (tmp_path / "uv.lock").write_text('[[package]]\nname="example-app"\nsource={virtual="."}\n')
    monkeypatch.setattr(verify, "_run_argv", lambda *_: pytest.fail("no third-party dependencies to audit"))
    assert scan_dependencies(tmp_path, "pypi")[0] == 0


@pytest.mark.parametrize("contradiction", [False, True])
def test_npm_scan_explicitly_includes_every_dependency_type(tmp_path, monkeypatch, contradiction):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{}')
    (frontend / "package-lock.json").write_text('{"packages":{}}')
    monkeypatch.setattr(verify, "_node_modules_problem", lambda *_: None)

    def scanner(argv, root):
        assert {"--include=prod", "--include=dev", "--include=optional", "--include=peer", "--audit-level=high"} <= set(argv)
        return subprocess.CompletedProcess(argv, int(contradiction), json.dumps({"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {"vulnerabilities": {"total": 0}}}), "")

    monkeypatch.setattr(verify, "_run_argv", scanner)
    code, _, extra = scan_dependencies(tmp_path, "npm")
    assert code == (2 if contradiction else 0)
    assert extra["dependency_audit"]["complete"] is not contradiction
    assert _audit_problems(extra["dependency_audit"]) == []


def test_the_evidence_a_scan_writes_is_the_contract_s_and_the_reader_reads_it(tmp_path, monkeypatch):
    """One npm finding end to end: the scan writes the contract's document, and the release
    reader takes from it the locks and the finding it wrote."""
    from datetime import UTC, datetime

    from terp.cli.dependency_risk import audit_evidence

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{}')
    (frontend / "package-lock.json").write_text(json.dumps(
        {"packages": {"node_modules/example-package": {"version": "1.0.0", "dev": True}}}))
    monkeypatch.setattr(verify, "_node_modules_problem", lambda *_: None)
    report = {"auditReportVersion": 2, "metadata": {"vulnerabilities": {"total": 1}}, "vulnerabilities": {
        "example-package": {"via": [{"url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc", "severity": "high"}],
                            "nodes": ["node_modules/example-package"]}}}
    monkeypatch.setattr(verify, "_run_argv", lambda argv, root: subprocess.CompletedProcess(argv, 1, json.dumps(report), ""))
    code, _, extra = scan_dependencies(tmp_path, "npm")
    audit = extra["dependency_audit"]
    assert code == 1 and audit["complete"] and len(audit["findings"]) == 1
    assert _audit_problems(audit) == []
    locks, findings = audit_evidence(audit, now=datetime.now(UTC))
    assert locks == audit["locks"] and list(findings.values()) == audit["findings"]


def test_a_scan_with_more_findings_than_the_contract_holds_is_incomplete(tmp_path, monkeypatch):
    from terp.cli.audit_findings import MAX_ITEMS

    (tmp_path / "uv.lock").write_text(LOCK)
    vulns = [{"id": f"PYSEC-2026-{index}", "aliases": [], "fix_versions": []} for index in range(MAX_ITEMS + 1)]
    report = {"dependencies": [{"name": "example-package", "version": "1.0.0", "vulns": vulns}]}
    monkeypatch.setattr(verify, "_run_argv", lambda *args: subprocess.CompletedProcess(args[0], 1, json.dumps(report), ""))
    code, output, extra = scan_dependencies(tmp_path, "pypi")
    assert code == 2 and extra["dependency_audit"]["complete"] is False
    assert f"more than {MAX_ITEMS}" in output
    assert _audit_problems(extra["dependency_audit"]) == []


_FINDING = {"advisory": "GHSA-aaaa-bbbb-cccc", "aliases": [], "ecosystem": "npm", "package": "example-package",
            "version": "1.0.0", "lockfile": "frontend/package-lock.json", "paths": ["node_modules/example-package"],
            "severity": "high", "fixed": [], "scope": "development"}


@pytest.mark.parametrize("field", ["advisory", "aliases", "package", "version", "lockfile", "paths", "fixed"])
def test_a_finding_longer_than_the_contract_allows_is_never_written(field):
    from terp.cli.audit_findings import MAX_ITEMS, MAX_TEXT, AuditUnreadable, finding

    long = "x" * (MAX_TEXT + 1)
    with pytest.raises(AuditUnreadable, match="dependency-audit contract"):
        finding(**{**_FINDING, field: [long] if isinstance(_FINDING[field], list) else long})
    if isinstance(_FINDING[field], list):
        with pytest.raises(AuditUnreadable, match="dependency-audit contract"):
            finding(**{**_FINDING, field: [f"entry-{index:05d}" for index in range(MAX_ITEMS + 1)]})
    exact = [f"entry-{index:05d}" for index in range(MAX_ITEMS)] if isinstance(_FINDING[field], list) else "x" * MAX_TEXT
    if field == "aliases":
        exact = exact[:-1]  # the advisory itself is the list's other entry
    assert _audit_problems({"version": 1, "complete": True, "scanned_at": "2026-11-18T12:00:00Z", "locks": {},
                            "findings": [finding(**{**_FINDING, field: exact})]}) == []
