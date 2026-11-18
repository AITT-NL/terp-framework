"""Complete dependency evidence for verification and human risk review."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from terp.cli.audit_findings import AuditUnreadable, blocking, npm_findings, python_findings


def scan_dependencies(root: Path, ecosystem: str) -> tuple[int, str, dict]:
    """Run the scanner; an error keeps all evidence explicitly incomplete."""
    from terp.arch.deployment import published_table
    from terp.cli.release._locks import NPM_LOCKS, npm_manifest, npm_workspace
    from terp.cli.release._plan import web_npm_locks
    from terp.cli.verify import NOT_APPLICABLE, _missing_workspace, _node_modules_problem, _run_argv

    evidence = {"version": 1, "complete": False, "scanned_at": datetime.now(UTC).isoformat(),
                "locks": {}, "findings": []}
    logs = []
    check_id = "dependency-audit-npm" if ecosystem == "npm" else "dependency-audit-python"
    if ecosystem == "npm":
        locks = list(dict.fromkeys([*NPM_LOCKS, *web_npm_locks(root, published_table())]))
        commands = []
        for lock in locks:
            if not (root / npm_manifest(lock)).is_file():
                missing = _missing_workspace(root, npm_workspace(lock), check_id)
                if missing and missing[0]:
                    return 2, missing[1], {"dependency_audit": evidence}
                continue
            commands.append((lock, ["npm", "--prefix", npm_workspace(lock), "audit", "--audit-level=high", "--json",
                                    "--include=prod", "--include=dev", "--include=optional", "--include=peer"]))
    else:
        commands = [("uv.lock", [])]
    try:
        for lock, command in commands:
            if (root / lock).is_symlink() or not (root / lock).resolve().is_relative_to(root.resolve()):
                raise AuditUnreadable("dependency locks must be regular files inside the project")
            before = (root / lock).read_bytes()
            if ecosystem == "npm":
                problem = _node_modules_problem(root, npm_workspace(lock))
                if problem is not None:
                    raise AuditUnreadable(problem)
                completed = _run_argv(command, root)
            else:
                from terp.cli.python_audit import audit_python

                completed = audit_python(root, before, _run_argv)
            code, output = completed.returncode, completed.stdout
            logs.append(f"--- {lock}\n{output}\n{completed.stderr}")
            if code not in (0, 1):
                raise AuditUnreadable(f"{check_id} could not complete (exit {code})")
            if (root / lock).read_bytes() != before:
                raise AuditUnreadable("the dependency lock changed during the audit")
            report = json.loads(output)
            if ecosystem == "npm":
                findings = npm_findings(report, json.loads(before), lock)
            else:
                findings = python_findings(report, lock)
            if (code == 1) != any(blocking(item) for item in findings):
                raise AuditUnreadable("the scanner exit code contradicts its dependency findings")
            evidence["locks"][lock] = "sha256:" + hashlib.sha256(before).hexdigest()
            evidence["findings"].extend(findings)
    except (OSError, ValueError) as exc:
        return 2, f"dependency audit incomplete: {exc}\n" + "\n".join(logs), {"dependency_audit": evidence}
    evidence["complete"] = True
    if not commands:
        return 0, f"no npm workspace - {check_id} {NOT_APPLICABLE}", {"dependency_audit": evidence}
    failed = any(blocking(item) for item in evidence["findings"])
    return int(failed), "\n".join(logs), {"dependency_audit": evidence}
