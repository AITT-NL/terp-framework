"""Audit the exact locked registry versions, independently of the scanner's environment.

Every locked version is checked, including development dependencies and platform
branches. Multiple versions of one package use separate batches because pip-audit
rejects conflicting requirements. No dependency resolution or installation of app
packages is needed. Non-registry third-party sources cannot be certified this way.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

from terp.cli.audit_findings import AuditUnreadable, python_findings
from terp.cli.release._locks import normalise


def audit_python(root: Path, locked: bytes, run) -> subprocess.CompletedProcess:
    packages = tomllib.loads(locked.decode()).get("package")
    if not isinstance(packages, list):
        raise AuditUnreadable("uv.lock has no package inventory")
    versions: dict[str, set[str]] = {}
    for package in packages:
        if not isinstance(package, dict):
            raise AuditUnreadable("uv.lock contains an invalid package")
        source = package.get("source")
        if source in ({"editable": "."}, {"virtual": "."}):
            continue
        name, version = package.get("name"), package.get("version")
        if (not isinstance(source, dict) or set(source) != {"registry"}
                or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
                or not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version)):
            raise AuditUnreadable("a locked third-party package has no auditable registry identity")
        versions.setdefault(normalise(name), set()).add(version)
    ordered = {name: sorted(values) for name, values in versions.items()}
    dependencies, errors = [], []
    code = 0
    with tempfile.TemporaryDirectory(prefix="terp-audit-") as directory:
        requirements = Path(directory) / "requirements.txt"
        for index in range(max(map(len, ordered.values()), default=0)):
            expected = {(name, values[index]) for name, values in ordered.items() if index < len(values)}
            requirements.write_text("".join(f"{name}=={version}\n" for name, version in sorted(expected)), encoding="utf-8")
            argv = ["uv", "tool", "run", "--from", "pip-audit", "pip-audit", "--no-deps", "--disable-pip",
                    "--progress-spinner", "off", "--format", "json", "--requirement", str(requirements)]
            completed = run(argv, root)
            if completed.returncode not in (0, 1):
                return completed
            report = json.loads(completed.stdout)
            findings = python_findings(report)
            observed = {(normalise(dep["name"]), dep["version"]) for dep in report["dependencies"]}
            if observed != expected:
                raise AuditUnreadable("pip-audit did not inspect the complete locked package inventory")
            if (completed.returncode == 1) != bool(findings):
                raise AuditUnreadable("pip-audit exit code contradicts its findings")
            code = max(code, completed.returncode)
            dependencies.extend(report["dependencies"])
            errors.append(completed.stderr)
    return subprocess.CompletedProcess("pip-audit", code, json.dumps({"dependencies": dependencies}), "\n".join(errors))
