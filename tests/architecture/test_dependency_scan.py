"""Scanner failures cannot be confused with findings eligible for human review."""

import json
import subprocess
from pathlib import Path

import pytest

from terp.cli import verify
from terp.cli.dependency_scan import scan_dependencies

LOCK = 'version = 1\n[[package]]\nname = "example-package"\nversion = "1.0.0"\nsource = {registry = "https://pypi.org/simple"}\n'


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
